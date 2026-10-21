"""Persistent privacy ledgers.

Local privacy is one device-day. The first export of a UTC day draws the
local mechanism once and stores the whole report. Later exports that day
replay those answers, so averaging repeats does not cancel the noise.
Replays spend no epsilon. A daily transmission cap and a lifetime epsilon
cap are enforced here. The memo is the report, not the true telemetry:
if the underlying answers change later the same day, the stored answers
are what gets sent. That is permanent randomized response. It can be stale.

Central privacy is one file per dataset. A publication is stored with its
spend. Asking for it again returns the stored noisy values and charges
nothing. A batch that does not fit in the remaining budget raises
``PrivacyBudgetExceeded`` and leaves the file unchanged.

The write replaces the file with ``os.replace`` while holding ``fcntl.flock``.
The noisy release is written in the same replacement as the spend. If that
replacement fails, the caller must discard the sample. Charging on a crash
after a successful replacement is acceptable. Returning a sample that was
never recorded is not.
"""

from __future__ import annotations

import copy
import fcntl
import json
import os
import tempfile
from typing import Callable, Mapping

from src.dp import (
    DAILY_EXPORT_CAP,
    DATASET_EPSILON_BUDGET,
    LIFETIME_EPSILON_CAP,
    LOCAL_EPSILON_DEFAULT,
    ExportCapExceeded,
    PrivacyBudgetExceeded,
    local_dp_mechanism,
)


_TOLERANCE = 1e-9


class DatasetLedger:
    """File-backed accountant for one dataset. There is no in-memory default."""

    def __init__(self, path: str, total_epsilon: float | None = None) -> None:
        if not path:
            raise ValueError("a dataset ledger needs a file path")
        self.path = path
        self.total_epsilon = (
            float(DATASET_EPSILON_BUDGET) if total_epsilon is None else float(total_epsilon)
        )
        if self.total_epsilon <= 0:
            raise ValueError("dataset epsilon budget must be > 0")

    def spent(self) -> float:
        state = self._read()
        return _spent(state)

    def remaining(self) -> float:
        return self.total_epsilon - self.spent()

    def get_publication(self, name: str) -> dict | None:
        state = self._read()
        stored = state["publications"].get(name)
        if stored is None:
            return None
        release = copy.deepcopy(stored["release"])
        release["replayed"] = True
        return release

    def commit_publication(
        self,
        name: str,
        entries: list[dict],
        release: Mapping[str, object],
    ) -> dict:
        """Store ``release`` if ``name`` is new and the spend fits.

        A name that is already stored is returned as-is and is not charged
        again. The caller's sample is discarded in that case; callers should
        return this function's result, not the sample they just drew.
        """
        if not name:
            raise ValueError("a publication needs a name")
        spend = _entry_spend(entries)

        def mutate(state: dict) -> tuple[dict | None, dict]:
            publications = state["publications"]
            if name in publications:
                stored = copy.deepcopy(publications[name]["release"])
                stored["replayed"] = True
                return None, stored
            already = _spent(state)
            if already + spend > float(state["total_epsilon"]) + _TOLERANCE:
                raise PrivacyBudgetExceeded(
                    f"publication {name!r} needs ε={spend:.6f} but only "
                    f"ε={float(state['total_epsilon']) - already:.6f} remains; nothing was charged"
                )
            body = copy.deepcopy(dict(release))
            body["replayed"] = False
            accountant = body.get("accountant")
            if isinstance(accountant, dict):
                accountant["dataset_budget"] = float(state["total_epsilon"])
                accountant["spent_epsilon"] = already + spend
                accountant["remaining_epsilon"] = float(state["total_epsilon"]) - already - spend
            publications[name] = {
                "epsilon": spend,
                "entries": copy.deepcopy(entries),
                "release": body,
            }
            return state, copy.deepcopy(body)

        return self._update(mutate)

    def _update(self, mutate: Callable[[dict], tuple[dict | None, dict]]) -> dict:
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        lock_path = self.path + ".lock"
        with open(lock_path, "a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                state = self._read()
                new_state, result = mutate(state)
                if new_state is not None:
                    _atomic_write(self.path, new_state)
                return result
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _read(self) -> dict:
        if not os.path.exists(self.path):
            return {"total_epsilon": self.total_epsilon, "publications": {}}
        with open(self.path, encoding="utf-8") as handle:
            state = json.load(handle)
        if "publications" not in state:
            raise ValueError(f"ledger {self.path} has no publications")
        return state


class DeviceLedger:
    """Per-device daily memo and lifetime cap. ``path`` may be omitted in tests."""

    def __init__(
        self,
        path: str | None = None,
        epsilon: float = LOCAL_EPSILON_DEFAULT,
    ) -> None:
        self.path = path
        self.epsilon = float(epsilon)
        if self.epsilon <= 0:
            raise ValueError("device epsilon must be > 0")
        self._memory: dict | None = None if path else {
            "lifetime_epsilon_spent": 0.0,
            "days": {},
        }

    def export(self, telemetry: Mapping[str, object], today: str, rng: object | None = None) -> dict:
        """Return today's memoized local report, or refuse without changing state."""
        if not today:
            raise ValueError("export needs a UTC day such as 2026-10-21")

        def mutate(state: dict) -> tuple[dict | None, dict]:
            days = state["days"]
            if today in days:
                day = days[today]
                if int(day["transmissions"]) >= DAILY_EXPORT_CAP:
                    raise ExportCapExceeded(
                        f"device already transmitted the {today} report "
                        f"{DAILY_EXPORT_CAP} times"
                    )
                day["transmissions"] = int(day["transmissions"]) + 1
                return state, _replay(day["report"], int(day["transmissions"]))
            if float(state["lifetime_epsilon_spent"]) + self.epsilon > LIFETIME_EPSILON_CAP + _TOLERANCE:
                raise PrivacyBudgetExceeded(
                    "lifetime epsilon cap would be exceeded; this day was not created"
                )
            report = local_dp_mechanism(telemetry, epsilon=self.epsilon, rng=rng)
            report["memoized"] = True
            report["transmission"] = 1
            report["privacy_spend_this_call"] = self.epsilon
            report["memoization"] = (
                "permanent randomized response for this UTC day; "
                "later changes to the telemetry do not redraw the answers"
            )
            state["lifetime_epsilon_spent"] = float(state["lifetime_epsilon_spent"]) + self.epsilon
            days[today] = {
                "epsilon": self.epsilon,
                "transmissions": 1,
                "report": copy.deepcopy(report),
            }
            return state, copy.deepcopy(report)

        if self.path is None:
            assert self._memory is not None
            new_state, result = mutate(self._memory)
            if new_state is not None:
                self._memory = new_state
            return result
        return self._update_file(mutate)

    def lifetime_spent(self) -> float:
        return float(self._state()["lifetime_epsilon_spent"])

    def transmissions(self, today: str) -> int:
        day = self._state()["days"].get(today)
        if day is None:
            return 0
        return int(day["transmissions"])

    def _state(self) -> dict:
        if self.path is None:
            assert self._memory is not None
            return self._memory
        if not os.path.exists(self.path):
            return {"lifetime_epsilon_spent": 0.0, "days": {}}
        with open(self.path, encoding="utf-8") as handle:
            return json.load(handle)

    def _update_file(self, mutate: Callable[[dict], tuple[dict | None, dict]]) -> dict:
        directory = os.path.dirname(os.path.abspath(self.path or ""))
        os.makedirs(directory, exist_ok=True)
        lock_path = str(self.path) + ".lock"
        with open(lock_path, "a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                state = self._state()
                new_state, result = mutate(state)
                if new_state is not None:
                    _atomic_write(str(self.path), new_state)
                return result
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _replay(report: Mapping[str, object], transmission: int) -> dict:
    replayed = copy.deepcopy(dict(report))
    replayed["memoized"] = True
    replayed["transmission"] = transmission
    replayed["privacy_spend_this_call"] = 0.0
    return replayed


def _spent(state: Mapping[str, object]) -> float:
    publications = state["publications"]
    total = 0.0
    for publication in publications.values():  # type: ignore[union-attr]
        total += float(publication["epsilon"])
    return total


def _entry_spend(entries: list[dict]) -> float:
    if not entries:
        raise ValueError("a publication needs at least one accountant entry")
    return sum(float(entry["epsilon"]) for entry in entries)


def _atomic_write(path: str, state: Mapping[str, object]) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".ledger-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
