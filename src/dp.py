"""Pure ε differential privacy for Verified-Human analytics.

The standard library is enough. Counts, booleans, and a five-bin histogram do not
need NumPy, Opacus, or Google's DP library. The Laplace mechanism and randomized
response are short, and the privacy argument sits next to the code that spends
the budget.

Neighboring relation
--------------------
Local DP. Two inputs are neighbors when they are any two telemetry records one
client might have produced. Noise is added before the record leaves the device.
Raw keystroke intervals are not part of the release.

Central DP. Two datasets are neighbors when they have the same number of rows
and differ in one row (bounded DP, substitution). Cohort size is identical for
neighbors, so it is public and is not noised. A histogram that places each row
in exactly one bin has L1 sensitivity 2. A count of a boolean has sensitivity 1.

Composition
-----------
Sequential composition of pure ε-DP mechanisms is (sum ε)-DP. ``PrivacyAccountant``
records every spend and refuses a query that would exceed the declared budget.
That is basic composition, not zCDP or a privacy-loss distribution. It is
conservative: a tighter accountant would only help utility.

Randomness
----------
The default generator is the operating system's CSPRNG (``random.SystemRandom``).
Laplace or randomized-response noise that an adversary can predict can be
subtracted, which voids the guarantee. Tests inject a seeded ``random.Random``.
A seed chosen by the data collector is not acceptable for a real client.

What this module does not do
----------------------------
It does not privatize an approve / flag / reject decision. That decision is an
action about one person. See ``src/analytics.py`` and the README.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Mapping, Sequence


LOCAL_EPSILON_DEFAULT = 1.0
CENTRAL_EPSILON_DEFAULT = 1.0

# Clips are public. They are the local sensitivity of the numeric queries.
PASTE_COUNT_CLIP = 5.0
TAB_SWITCH_CLIP = 10.0

# Same predicates the Tier 1 rules use. Kept here so a local report can estimate
# how often those rules would fire without shipping the raw magnitudes.
EXCESSIVE_TAB_THRESHOLD = 4
FAST_SUBMISSION_SECONDS = 30.0
LOW_VARIANCE_MS = 5.0

# Inter-key gaps in milliseconds. Five bins: (-inf is rejected), [0, 50), ...
KEYSTROKE_BIN_EDGES_MS: tuple[float, ...] = (50.0, 150.0, 300.0, 600.0)
KEYSTROKE_BIN_LABELS: tuple[str, ...] = (
    "[0, 50)",
    "[50, 150)",
    "[150, 300)",
    "[300, 600)",
    "[600, inf)",
)

# Shares are percents of the caller's epsilon and must sum to 100.
# The last query absorbs the floating-point remainder so the spends add up
# to the declared budget exactly. Order is part of the client contract.
LOCAL_SHARES: tuple[tuple[str, int], ...] = (
    ("paste_detected", 25),
    ("focus_paste_coincidence", 8),
    ("excessive_tab_switches", 20),
    ("fast_submission", 7),
    ("low_cadence_variance", 15),
    ("paste_count", 5),
    ("tab_switches", 10),
    ("keystroke_histogram", 10),
)

CENTRAL_SHARES: tuple[tuple[str, int], ...] = (
    ("status_histogram", 30),
    ("paste_detected_count", 15),
    ("low_variance_count", 15),
    ("excessive_tabs_count", 10),
    ("tab_switch_histogram", 15),
    ("cadence_histogram", 15),
)

LOCAL_RR_QUERIES: tuple[str, ...] = (
    "paste_detected",
    "focus_paste_coincidence",
    "excessive_tab_switches",
    "fast_submission",
    "low_cadence_variance",
)
LOCAL_LAPLACE_SENSITIVITY: dict[str, float] = {
    "paste_count": PASTE_COUNT_CLIP,
    "tab_switches": TAB_SWITCH_CLIP,
}
# A per-client distribution (or the zero vector, if they produced no gaps)
# moves by at most 2 in L1 when the client changes arbitrarily.
KEYSTROKE_HISTOGRAM_L1_SENSITIVITY = 2.0

_SHARE_TABLES = (LOCAL_SHARES, CENTRAL_SHARES)
for _shares in _SHARE_TABLES:
    if sum(share for _, share in _shares) != 100:
        raise RuntimeError("privacy budget shares must sum to 100")


class PrivacyBudgetExceeded(RuntimeError):
    """The next query would exceed the declared pure-ε budget under basic composition."""


@dataclass(frozen=True)
class LedgerEntry:
    name: str
    epsilon: float
    mechanism: str
    sensitivity: float
    note: str = ""

    def as_dict(self) -> dict[str, float | str]:
        return {
            "name": self.name,
            "epsilon": self.epsilon,
            "mechanism": self.mechanism,
            "sensitivity": self.sensitivity,
            "note": self.note,
        }


class PrivacyAccountant:
    """Tracks pure ε spent by basic composition and refuses overspend.

    The accountant only sees queries that pass through it. Two releases that
    each construct a fresh accountant are not automatically composed; the
    caller passes one accountant when those releases will be published together.
    """

    def __init__(self, total_epsilon: float) -> None:
        self.total_epsilon = _require_positive_epsilon(total_epsilon)
        self._spent = 0.0
        self.entries: list[LedgerEntry] = []

    @property
    def spent(self) -> float:
        return self._spent

    @property
    def remaining(self) -> float:
        return self.total_epsilon - self._spent

    def spend(
        self,
        name: str,
        epsilon: float,
        mechanism: str,
        sensitivity: float,
        note: str = "",
    ) -> None:
        if not math.isfinite(epsilon) or epsilon < 0:
            raise ValueError(f"epsilon spend must be finite and >= 0, got {epsilon!r}")
        if not math.isfinite(sensitivity) or sensitivity < 0:
            raise ValueError(f"sensitivity must be finite and >= 0, got {sensitivity!r}")
        if self._spent + epsilon > self.total_epsilon + 1e-9:
            raise PrivacyBudgetExceeded(
                f"query {name!r} needs ε={epsilon:.6g} but only "
                f"ε={self.remaining:.6g} remains of ε={self.total_epsilon:.6g} "
                "under basic composition"
            )
        self._spent += epsilon
        self.entries.append(
            LedgerEntry(
                name=name,
                epsilon=epsilon,
                mechanism=mechanism,
                sensitivity=sensitivity,
                note=note,
            )
        )

    def summary(self) -> dict[str, object]:
        return {
            "composition": "basic",
            "total_epsilon": self.total_epsilon,
            "spent_epsilon": self._spent,
            "remaining_epsilon": self.remaining,
            "entries": [entry.as_dict() for entry in self.entries],
        }


def allocate_budget(
    total_epsilon: float, shares: Sequence[tuple[str, int]]
) -> dict[str, float]:
    """Split ``total_epsilon`` by integer percents. The last share gets the remainder."""
    total_epsilon = _require_positive_epsilon(total_epsilon)
    if sum(share for _, share in shares) != 100:
        raise ValueError("shares must sum to 100")
    if not shares:
        raise ValueError("shares must not be empty")
    allocated: dict[str, float] = {}
    consumed = 0.0
    for name, share in shares[:-1]:
        portion = total_epsilon * share / 100.0
        allocated[name] = portion
        consumed += portion
    last_name, _last_share = shares[-1]
    allocated[last_name] = total_epsilon - consumed
    return allocated


def client_constants() -> dict[str, object]:
    """Constants the browser implementation must match. Compared in tests."""
    return {
        "local_epsilon_default": LOCAL_EPSILON_DEFAULT,
        "paste_count_clip": PASTE_COUNT_CLIP,
        "tab_switch_clip": TAB_SWITCH_CLIP,
        "excessive_tab_threshold": EXCESSIVE_TAB_THRESHOLD,
        "fast_submission_seconds": FAST_SUBMISSION_SECONDS,
        "low_variance_ms": LOW_VARIANCE_MS,
        "keystroke_bin_edges_ms": list(KEYSTROKE_BIN_EDGES_MS),
        "keystroke_histogram_l1_sensitivity": KEYSTROKE_HISTOGRAM_L1_SENSITIVITY,
        "local_shares": [[name, share] for name, share in LOCAL_SHARES],
    }


def rr_probabilities(epsilon: float) -> tuple[float, float]:
    """Return ``(p_truth, p_flip)`` for binary ε-local randomized response.

    ``p_truth / p_flip = exp(ε)``, so every output has likelihood ratio at most
    exp(ε) between the two possible inputs.
    """
    epsilon = _require_positive_epsilon(epsilon)
    # p = 1 / (1 + e^{-ε}) avoids overflow for large ε. Past ε ≈ 700,
    # e^{-ε} underflows and the mechanism reports the truth, which is the
    # correct limit of randomized response.
    if epsilon >= 700:
        return 1.0, 0.0
    exp_neg = math.exp(-epsilon)
    p_truth = 1.0 / (1.0 + exp_neg)
    p_flip = exp_neg / (1.0 + exp_neg)
    return p_truth, p_flip


def randomized_response(bit: bool, epsilon: float, rng: random.Random) -> int:
    """Report the bit truthfully with probability ``e^ε / (e^ε + 1)``."""
    p_truth, _p_flip = rr_probabilities(epsilon)
    value = 1 if bit else 0
    if rng.random() < p_truth:
        return value
    return 1 - value


def debias_rr_mean(reports: Sequence[int], epsilon: float) -> float:
    """Unbiased estimate of the mean of the secret bits.

    If ``Y`` is the randomized response of bit ``B``, then
    ``E[Y] = q + (p - q) B`` with ``p`` the truth probability and ``q = 1 - p``.
    ``(Y - q) / (p - q)`` is therefore unbiased for ``B``, and the average is
    unbiased for the population rate. The correction is post-processing of an
    already private release and spends no further budget. It is high-variance
    when ε is small, because ``p - q = tanh(ε / 2)`` shrinks.
    """
    if not reports:
        raise ValueError("randomized-response debiasing needs at least one report")
    p_truth, p_flip = rr_probabilities(epsilon)
    gap = p_truth - p_flip
    total = 0.0
    for report in reports:
        if report not in (0, 1):
            raise ValueError(f"randomized response must be 0 or 1, got {report!r}")
        total += (report - p_flip) / gap
    return total / len(reports)


def laplace_scale(sensitivity: float, epsilon: float) -> float:
    """Noise scale ``b`` in the density ``(1 / 2b) exp(-|x| / b)``.

    For a query with sensitivity ``Δ``, ``b = Δ / ε``. Adding this noise yields
    pure ε-DP (Dwork, McSherry, Nissim, Smith). Variance of the noise is ``2 b^2``.
    """
    epsilon = _require_positive_epsilon(epsilon)
    if not math.isfinite(sensitivity) or sensitivity < 0:
        raise ValueError(f"sensitivity must be finite and >= 0, got {sensitivity!r}")
    if sensitivity == 0:
        return 0.0
    return sensitivity / epsilon


def sample_laplace(scale: float, rng: random.Random) -> float:
    """Draw from Laplace(0, ``scale``) via the inverse CDF."""
    if not math.isfinite(scale) or scale < 0:
        raise ValueError(f"Laplace scale must be finite and >= 0, got {scale!r}")
    if scale == 0.0:
        return 0.0
    while True:
        probability = rng.random()
        if 0.0 < probability < 1.0:
            break
    if probability < 0.5:
        return scale * math.log(2.0 * probability)
    return -scale * math.log(2.0 * (1.0 - probability))


def laplace_mechanism(
    value: float,
    sensitivity: float,
    epsilon: float,
    rng: random.Random,
) -> float:
    """Add Laplace noise calibrated to ``sensitivity / epsilon``."""
    if not math.isfinite(value):
        raise ValueError(f"query value must be finite, got {value!r}")
    return value + sample_laplace(laplace_scale(sensitivity, epsilon), rng)


def laplace_histogram(
    counts: Sequence[float],
    l1_sensitivity: float,
    epsilon: float,
    rng: random.Random,
) -> list[float]:
    """Vector Laplace mechanism.

    Independent Laplace(``Δ₁ / ε``) noise on each coordinate is ε-DP for a query
    whose L1 sensitivity is ``Δ₁``, not (bins × ε)-DP. Charging ε per bin would
    overstate the privacy loss of this mechanism.
    """
    scale = laplace_scale(l1_sensitivity, epsilon)
    return [float(count) + sample_laplace(scale, rng) for count in counts]


def population_variance(values: Sequence[float]) -> float:
    """Population variance, matching the Tier 1 cadence formula (divide by N)."""
    count = len(values)
    if count == 0:
        return 0.0
    mean = sum(values) / count
    return sum((value - mean) ** 2 for value in values) / count


def keystroke_bin_index(interval_ms: float) -> int:
    if not math.isfinite(interval_ms) or interval_ms < 0:
        raise ValueError(f"keystroke interval must be finite and >= 0, got {interval_ms!r}")
    for index, edge in enumerate(KEYSTROKE_BIN_EDGES_MS):
        if interval_ms < edge:
            return index
    return len(KEYSTROKE_BIN_EDGES_MS)


def keystroke_proportion_histogram(intervals_ms: Sequence[float]) -> list[float]:
    """Per-client cadence distribution.

    No intervals maps to the zero vector, not a uniform guess. The average of
    these vectors estimates the mean per-client distribution; clients who never
    typed pull that average toward zero, and the bin sums estimate the fraction
    of clients who produced at least one interval. L1 sensitivity is 2.
    """
    bins = [0.0] * (len(KEYSTROKE_BIN_EDGES_MS) + 1)
    for interval in intervals_ms:
        bins[keystroke_bin_index(float(interval))] += 1.0
    total = sum(bins)
    if total == 0.0:
        return bins
    return [count / total for count in bins]


def clip(value: float, low: float, high: float) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value


def local_contribution(telemetry: Mapping[str, object]) -> dict[str, object]:
    """Pre-noise contribution of one client.

    Confidential. This is the query the local mechanisms are applied to, including
    clipping. It is not a differentially private release and must not be exported.
    """
    return _local_view(telemetry)


def local_dp_release(
    telemetry: Mapping[str, object],
    epsilon: float = LOCAL_EPSILON_DEFAULT,
    rng: random.Random | None = None,
) -> dict[str, object]:
    """Privatize one client's aggregate telemetry. Raw keystroke gaps are dropped.

    The returned object is the analytics export. It is not an input to fraud
    scoring. Numeric queries are clipped before noise, so the unbiased aggregate
    estimates the clipped population mean, not the unclipped one.
    """
    generator = rng if rng is not None else random.SystemRandom()
    budget = allocate_budget(epsilon, LOCAL_SHARES)
    accountant = PrivacyAccountant(epsilon)
    view = _local_view(telemetry)

    values: dict[str, object] = {}
    rr_parameters: dict[str, dict[str, float]] = {}
    for name in LOCAL_RR_QUERIES:
        query_epsilon = budget[name]
        p_truth, p_flip = rr_probabilities(query_epsilon)
        accountant.spend(
            name,
            query_epsilon,
            "randomized_response",
            1.0,
            note="binary predicate; truth probability e^ε/(e^ε+1)",
        )
        values[name] = randomized_response(bool(view[name]), query_epsilon, generator)
        rr_parameters[name] = {
            "epsilon": query_epsilon,
            "p_truth": p_truth,
            "p_flip": p_flip,
        }

    laplace_parameters: dict[str, dict[str, object]] = {}
    for name, sensitivity in LOCAL_LAPLACE_SENSITIVITY.items():
        query_epsilon = budget[name]
        scale = laplace_scale(sensitivity, query_epsilon)
        accountant.spend(
            name,
            query_epsilon,
            "laplace",
            sensitivity,
            note=f"clipped contribution; scale={scale}",
        )
        values[name] = laplace_mechanism(float(view[name]), sensitivity, query_epsilon, generator)
        laplace_parameters[name] = {
            "epsilon": query_epsilon,
            "sensitivity": sensitivity,
            "scale": scale,
            "clip": [0.0, sensitivity],
        }

    hist_epsilon = budget["keystroke_histogram"]
    hist_scale = laplace_scale(KEYSTROKE_HISTOGRAM_L1_SENSITIVITY, hist_epsilon)
    accountant.spend(
        "keystroke_histogram",
        hist_epsilon,
        "laplace",
        KEYSTROKE_HISTOGRAM_L1_SENSITIVITY,
        note="vector Laplace on the per-client distribution; one charge for all bins",
    )
    values["keystroke_histogram"] = laplace_histogram(
        view["histogram"],  # type: ignore[arg-type]
        KEYSTROKE_HISTOGRAM_L1_SENSITIVITY,
        hist_epsilon,
        generator,
    )
    laplace_parameters["keystroke_histogram"] = {
        "epsilon": hist_epsilon,
        "sensitivity_l1": KEYSTROKE_HISTOGRAM_L1_SENSITIVITY,
        "scale": hist_scale,
        "bin_edges_ms": list(KEYSTROKE_BIN_EDGES_MS),
        "bin_labels": list(KEYSTROKE_BIN_LABELS),
        "estimand": (
            "mean of per-client keystroke-gap distributions; "
            "a client with no gaps contributes the zero vector"
        ),
    }

    return {
        "privacy_model": "local",
        "differentially_private": True,
        "definition": "pure epsilon local differential privacy, basic composition",
        "neighboring_relation": "any two telemetry records from one client",
        "epsilon": epsilon,
        "raw_keystrokes_included": False,
        "individual_decision_included": False,
        "values": values,
        "public_parameters": {
            "rr_probabilities": rr_parameters,
            "laplace": laplace_parameters,
            "thresholds": {
                "excessive_tab_switches": f"> {EXCESSIVE_TAB_THRESHOLD}",
                "fast_submission_seconds": f"< {FAST_SUBMISSION_SECONDS}",
                "low_cadence_variance_ms": f"< {LOW_VARIANCE_MS}",
            },
        },
        "accountant": accountant.summary(),
    }


def aggregate_local_releases(releases: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Debias and average local releases. Post-processing; spends no budget.

    Randomized-response fields are unbiased for the true predicate rate.
    Laplace fields are unbiased for the mean of the clipped contributions.
    The histogram average is unbiased for the mean per-client distribution.
    """
    if not releases:
        raise ValueError("need at least one local release to aggregate")
    count = len(releases)
    first = releases[0]
    rr_meta = first["public_parameters"]["rr_probabilities"]  # type: ignore[index]
    rates: dict[str, dict[str, float]] = {}
    for name in LOCAL_RR_QUERIES:
        epsilon = float(rr_meta[name]["epsilon"])  # type: ignore[index]
        bits = [int(release["values"][name]) for release in releases]  # type: ignore[index]
        rates[name] = {
            "debiased_rate": debias_rr_mean(bits, epsilon),
            "epsilon": epsilon,
        }
    laplace_means = {
        name: sum(float(release["values"][name]) for release in releases) / count  # type: ignore[index]
        for name in LOCAL_LAPLACE_SENSITIVITY
    }
    width = len(KEYSTROKE_BIN_LABELS)
    histogram = [0.0] * width
    for release in releases:
        bins = release["values"]["keystroke_histogram"]  # type: ignore[index]
        if len(bins) != width:  # type: ignore[arg-type]
            raise ValueError("keystroke histogram width does not match the public bins")
        for index, bin_value in enumerate(bins):  # type: ignore[arg-type]
            histogram[index] += float(bin_value)
    histogram = [bin_value / count for bin_value in histogram]
    return {
        "n": count,
        "privacy_spend": 0.0,
        "note": "post-processing of local releases; basic composition is unchanged",
        "randomized_response_rates": rates,
        "laplace_means": laplace_means,
        "keystroke_histogram_mean": histogram,
    }


def _local_view(telemetry: Mapping[str, object]) -> dict[str, object]:
    paste_detected = _as_bool(telemetry.get("paste_detected", False), "paste_detected")
    if telemetry.get("paste_count") is None:
        paste_count = 1.0 if paste_detected else 0.0
    else:
        paste_count = _finite(telemetry["paste_count"], "paste_count")
    focus_paste = _as_bool(
        telemetry.get("focus_paste_coincidence", False), "focus_paste_coincidence"
    )
    if "tab_switches" in telemetry and telemetry.get("tab_switches") is not None:
        tab_switches = _finite(telemetry["tab_switches"], "tab_switches")
    else:
        tab_switches = _finite(telemetry.get("tab_switches_during_form", 0), "tab_switches")

    raw_intervals = telemetry.get("keystroke_intervals_ms", [])
    if raw_intervals is None:
        raw_intervals = []
    if not isinstance(raw_intervals, (list, tuple)):
        raise TypeError("keystroke_intervals_ms must be a list of millisecond gaps")
    intervals = [_finite(value, "keystroke interval") for value in raw_intervals]

    if telemetry.get("typing_cadence_variance_ms") is not None:
        variance: float | None = _finite(
            telemetry["typing_cadence_variance_ms"], "typing_cadence_variance_ms"
        )
    elif len(intervals) >= 2:
        variance = population_variance(intervals)
    else:
        variance = None

    time_taken = telemetry.get("time_taken_seconds", telemetry.get("time"))
    if time_taken is None:
        fast_submission = False
    else:
        fast_submission = _finite(time_taken, "time_taken_seconds") < FAST_SUBMISSION_SECONDS

    return {
        "paste_detected": paste_detected,
        "paste_count": clip(paste_count, 0.0, PASTE_COUNT_CLIP),
        "focus_paste_coincidence": focus_paste,
        "tab_switches": clip(tab_switches, 0.0, TAB_SWITCH_CLIP),
        "excessive_tab_switches": tab_switches > EXCESSIVE_TAB_THRESHOLD,
        "fast_submission": fast_submission,
        "low_cadence_variance": False if variance is None else variance < LOW_VARIANCE_MS,
        "histogram": keystroke_proportion_histogram(intervals),
    }


def _require_positive_epsilon(epsilon: float) -> float:
    if isinstance(epsilon, bool) or not isinstance(epsilon, (int, float)):
        raise ValueError(f"epsilon must be a positive number, got {epsilon!r}")
    epsilon = float(epsilon)
    if not math.isfinite(epsilon) or epsilon <= 0:
        raise ValueError(f"epsilon must be finite and > 0, got {epsilon!r}")
    return epsilon


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number, got {value!r}")
    return number


def _as_bool(value: object, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    raise ValueError(f"{label} must be a boolean, got {value!r}")
