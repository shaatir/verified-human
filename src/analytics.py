"""Cohort analytics for Verified-Human.

Two paths, deliberately separate:

1. Individual risk decisions from ``process_participant_screening``. Exact.
   Not differentially private. The operator has to act on a named person, and
   noise would change who is approved. Publishing that decision tells the
   recipient about that person no matter how the aggregates are noised.

2. Aggregate statistics. Central ε-DP under substitution neighbors, with a
   basic-composition accountant. This is the release a transparency report or
   a downstream analyst can see without receiving the row-level table.

Local DP is computed on the client (``local_dp_release`` / ``web/dp.js``) and
is not reconstructed here. The curator of this module is assumed to already
hold the rows, because the fraud decision required them. Central DP protects
the published aggregates against someone who does not also receive the
decisions or the microdata. Giving both to the same party does not make the
decisions private.
"""

from __future__ import annotations

import math
import random
from typing import Mapping, Sequence

from src.dp import (
    CENTRAL_EPSILON_DEFAULT,
    CENTRAL_SHARES,
    EXCESSIVE_TAB_THRESHOLD,
    LOW_VARIANCE_MS,
    PrivacyAccountant,
    allocate_budget,
    laplace_histogram,
    laplace_mechanism,
    laplace_scale,
)
from src.pipeline import process_participant_screening


STATUS_BINS: tuple[str, ...] = ("APPROVED", "FLAGGED_FOR_REVIEW", "AUTO_REJECTED")
TAB_SWITCH_BIN_LABELS: tuple[str, ...] = ("0", "1-2", "3-4", "5-8", "9+")
CADENCE_BIN_LABELS: tuple[str, ...] = ("[0, 5)", "[5, 15)", "[15, 40)", "[40, inf)")

# Why each path is or is not differentially private. Tests lock these flags.
PRIVACY_PATHS: dict[str, dict[str, object]] = {
    "individual_risk_decision": {
        "differentially_private": False,
        "mechanism": None,
        "reason": (
            "Approve, flag, and reject are decisions about one respondent. "
            "Differential privacy bounds what a statistic reveals about a person; "
            "it does not hide an action you still take on them. Noise on the "
            "score would also change who is stopped, including false approvals "
            "of scripted submissions. The score therefore stays exact, and it "
            "is not part of the DP release."
        ),
    },
    "local_aggregate_export": {
        "differentially_private": True,
        "mechanism": "local randomized response and Laplace",
        "reason": (
            "Before aggregate telemetry leaves the device, predicates are passed "
            "through randomized response and clipped counts and the keystroke-gap "
            "histogram are passed through the Laplace mechanism. Raw inter-key "
            "intervals are not in that export. This protects a client from the "
            "analytics collector. It is not an anti-fraud control: a modified "
            "client can skip the noise or lie."
        ),
    },
    "central_dashboard_aggregates": {
        "differentially_private": True,
        "mechanism": "central Laplace, basic composition",
        "reason": (
            "The curator holds row-level records in order to score them. "
            "Published counts and histograms add Laplace noise calibrated to "
            "substitution sensitivity, and the accountant sums the epsilons. "
            "The guarantee applies to that aggregate release, not to the "
            "decision log."
        ),
    },
}

_LEGIT_TRAP = (
    "CSS does not have memory leaks. There is no such thing as a CSS memory leak; "
    "memory leaks happen in JavaScript when DOM nodes are retained."
)
_BOT_TRAP = (
    "To fix CSS memory leaks, optimize selectors and remove unused classes. "
    "Inspect heap snapshots to see where styles are hogging memory."
)
_LLM_TRAP = (
    "First and foremost, it is crucial to note that CSS memory leaks degrade performance.\n"
    "- First, analyze selector complexity.\n"
    "- Second, minimize heavy dynamic properties.\n"
    "- Third, clean up dynamic class injections.\n"
    "In conclusion, addressing CSS memory leaks is vital."
)
_BORDER_TRAP = (
    "I don't think CSS files themselves have memory leaks. Memory leaks occur in "
    "JS logic. You can't leak memory in CSS rules."
)


def screen_cohort(participants: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Exact per-respondent decisions. Not differentially private."""
    return [process_participant_screening(dict(participant)) for participant in participants]


def exact_cohort_statistics(
    participants: Sequence[Mapping[str, object]],
    decisions: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Non-private answers to the dashboard queries.

    This is the curator-side function the noisy release is built from. It is
    not a publication. Do not ship it with the aggregate release.
    """
    if decisions is None:
        decisions = screen_cohort(participants)
    if len(decisions) != len(participants):
        raise ValueError("decisions and participants must have the same length")

    status_counts = [0] * len(STATUS_BINS)
    tab_counts = [0] * len(TAB_SWITCH_BIN_LABELS)
    cadence_counts = [0] * len(CADENCE_BIN_LABELS)
    paste = 0
    low_variance = 0
    excessive_tabs = 0

    for participant, decision in zip(participants, decisions):
        status = str(decision["status"])
        try:
            status_counts[STATUS_BINS.index(status)] += 1
        except ValueError as exc:
            raise ValueError(f"unknown routing status {status!r}") from exc

        pasted = bool(participant.get("paste_detected", False))
        if pasted:
            paste += 1
        variance = float(participant.get("typing_cadence_variance_ms", 0.0))
        if variance < LOW_VARIANCE_MS:
            low_variance += 1
        tabs = int(participant.get("tab_switches_during_form", 0))
        if tabs > EXCESSIVE_TAB_THRESHOLD:
            excessive_tabs += 1
        tab_counts[_tab_bin(tabs)] += 1
        cadence_counts[_cadence_bin(variance)] += 1

    return {
        "cohort_size": len(participants),
        "status_histogram": status_counts,
        "paste_detected_count": paste,
        "low_variance_count": low_variance,
        "excessive_tabs_count": excessive_tabs,
        "tab_switch_histogram": tab_counts,
        "cadence_histogram": cadence_counts,
    }


def central_dashboard_release(
    participants: Sequence[Mapping[str, object]],
    epsilon: float = CENTRAL_EPSILON_DEFAULT,
    rng: random.Random | None = None,
    accountant: PrivacyAccountant | None = None,
    decisions: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Noisy counts and histograms for one dashboard publication.

    ``epsilon`` is the privacy budget of this publication. Pass the same
    ``PrivacyAccountant`` into later publications to compose them. A fresh
    accountant is created when the caller does not supply one; that does not
    compose with any previous release.

    The returned object contains noisy values only. Exact query answers and
    row-level fields are not included.
    """
    generator = rng if rng is not None else random.SystemRandom()
    budget = allocate_budget(epsilon, CENTRAL_SHARES)
    if accountant is None:
        accountant = PrivacyAccountant(epsilon)
    exact = exact_cohort_statistics(participants, decisions)

    statistics: dict[str, object] = {
        "status_histogram": _noise_histogram(
            name="status_histogram",
            labels=STATUS_BINS,
            counts=exact["status_histogram"],  # type: ignore[arg-type]
            epsilon=budget["status_histogram"],
            rng=generator,
            accountant=accountant,
            note="each respondent has one status; substitution L1 sensitivity is 2",
        ),
        "paste_detected_count": _noise_count(
            name="paste_detected_count",
            true_count=int(exact["paste_detected_count"]),  # type: ignore[arg-type]
            epsilon=budget["paste_detected_count"],
            rng=generator,
            accountant=accountant,
            note="boolean predicate; substitution sensitivity is 1",
        ),
        "low_variance_count": _noise_count(
            name="low_variance_count",
            true_count=int(exact["low_variance_count"]),  # type: ignore[arg-type]
            epsilon=budget["low_variance_count"],
            rng=generator,
            accountant=accountant,
            note=f"count of cadence variance < {LOW_VARIANCE_MS}ms; sensitivity 1",
        ),
        "excessive_tabs_count": _noise_count(
            name="excessive_tabs_count",
            true_count=int(exact["excessive_tabs_count"]),  # type: ignore[arg-type]
            epsilon=budget["excessive_tabs_count"],
            rng=generator,
            accountant=accountant,
            note=f"count of tab switches > {EXCESSIVE_TAB_THRESHOLD}; sensitivity 1",
        ),
        "tab_switch_histogram": _noise_histogram(
            name="tab_switch_histogram",
            labels=TAB_SWITCH_BIN_LABELS,
            counts=exact["tab_switch_histogram"],  # type: ignore[arg-type]
            epsilon=budget["tab_switch_histogram"],
            rng=generator,
            accountant=accountant,
            note="one bin per respondent; substitution L1 sensitivity is 2",
        ),
        "cadence_histogram": _noise_histogram(
            name="cadence_histogram",
            labels=CADENCE_BIN_LABELS,
            counts=exact["cadence_histogram"],  # type: ignore[arg-type]
            epsilon=budget["cadence_histogram"],
            rng=generator,
            accountant=accountant,
            note="one bin per respondent; substitution L1 sensitivity is 2",
        ),
    }

    return {
        "privacy_model": "central",
        "differentially_private": True,
        "definition": "pure epsilon central differential privacy, basic composition",
        "neighboring_relation": "substitution",
        "cohort_size": len(participants),
        "cohort_size_is_public": True,
        "cohort_size_reason": (
            "Substitution neighbors have the same number of rows, so cohort size "
            "is invariant and is not given Laplace noise."
        ),
        "epsilon": float(epsilon),
        "individual_decisions_included": False,
        "statistics": statistics,
        "accountant": accountant.summary(),
    }


def cohort_privacy_report(
    participants: Sequence[Mapping[str, object]],
    epsilon: float = CENTRAL_EPSILON_DEFAULT,
    rng: random.Random | None = None,
    accountant: PrivacyAccountant | None = None,
) -> dict[str, object]:
    """Exact decisions beside one central DP aggregate release.

    The two objects are separate so a publisher can hand out the aggregate
    without handing out the decision log. Scoring does not read the noisy
    statistics.
    """
    decisions = screen_cohort(participants)
    aggregate = central_dashboard_release(
        participants,
        epsilon=epsilon,
        rng=rng,
        accountant=accountant,
        decisions=decisions,
    )
    return {
        "individual_decisions": {
            "differentially_private": False,
            "reason": PRIVACY_PATHS["individual_risk_decision"]["reason"],
            "results": decisions,
        },
        "local_export": {
            "differentially_private": True,
            "model": "local",
            "computed_here": False,
            "note": (
                "Local DP runs on the client before export. This curator-side "
                "report does not rebuild it and does not contain raw keystroke intervals."
            ),
        },
        "aggregate_release": aggregate,
    }


def synthesize_population(n: int, rng: random.Random) -> list[dict[str, object]]:
    """Synthetic cohort whose telemetry stays inside one routing region per role.

    Used by the accuracy evaluation and by regression tests. Draws are clamped
    so a legit record cannot wander across a Tier 1 threshold. ``expected_status``
    is an evaluation label; the DP release does not read it.
    """
    if n < 4:
        raise ValueError("synthesize_population needs at least 4 respondents")
    n_bot = int(round(n * 0.15))
    n_llm = int(round(n * 0.15))
    n_border = int(round(n * 0.10))
    n_legit = n - n_bot - n_llm - n_border
    roles = (
        [("legit", n_legit), ("bot", n_bot), ("llm", n_llm), ("borderline", n_border)]
    )
    population: list[dict[str, object]] = []
    index = 0
    for role, count in roles:
        for _ in range(count):
            population.append(_synthetic_person(role, index, rng))
            index += 1
    return population


def _synthetic_person(role: str, index: int, rng: random.Random) -> dict[str, object]:
    if role == "legit":
        tabs = rng.randint(0, 2)
        person: dict[str, object] = {
            "participant_id": f"syn_{index}",
            "name": f"Legit {index}",
            "time_taken_seconds": rng.uniform(90.0, 160.0),
            "typing_cadence_variance_ms": rng.uniform(25.0, 60.0),
            "paste_detected": False,
            "paste_count": 0,
            "focus_paste_coincidence": False,
            "tab_switches_during_form": tabs,
            "trap_question_response": _LEGIT_TRAP,
            "other_responses": ["I write CSS and JavaScript for a product team."],
            "github_account_age_days": rng.randint(400, 2000),
            "github_public_repos": rng.randint(5, 30),
            "github_followers": rng.randint(3, 40),
            "keystroke_intervals_ms": _human_intervals(rng, rng.randint(12, 40)),
            "expected_status": "APPROVED",
            "role": role,
        }
        return person
    if role == "bot":
        return {
            "participant_id": f"syn_{index}",
            "name": f"Bot {index}",
            "time_taken_seconds": rng.uniform(4.0, 20.0),
            "typing_cadence_variance_ms": rng.uniform(0.2, 2.0),
            "paste_detected": True,
            "paste_count": rng.randint(1, 3),
            "focus_paste_coincidence": False,
            "tab_switches_during_form": 0,
            "trap_question_response": _BOT_TRAP,
            "other_responses": ["I am a software engineer."],
            "github_account_age_days": rng.randint(1, 10),
            "github_public_repos": 0,
            "github_followers": 0,
            "keystroke_intervals_ms": [rng.uniform(12.0, 35.0) for _ in range(rng.randint(8, 24))],
            "expected_status": "AUTO_REJECTED",
            "role": role,
        }
    if role == "llm":
        tabs = rng.randint(6, 9)
        return {
            "participant_id": f"syn_{index}",
            "name": f"LLM {index}",
            "time_taken_seconds": rng.uniform(50.0, 80.0),
            "typing_cadence_variance_ms": rng.uniform(18.0, 35.0),
            "paste_detected": True,
            "paste_count": rng.randint(1, 4),
            "focus_paste_coincidence": True,
            "tab_switches_during_form": tabs,
            "trap_question_response": _LLM_TRAP,
            "other_responses": ["I have extensive expertise in modern fullstack web architectures."],
            "github_account_age_days": rng.randint(40, 90),
            "github_public_repos": 0,
            "github_followers": 0,
            "keystroke_intervals_ms": _human_intervals(rng, rng.randint(6, 16)),
            "expected_status": "AUTO_REJECTED",
            "role": role,
        }
    if role == "borderline":
        return {
            "participant_id": f"syn_{index}",
            "name": f"Border {index}",
            "time_taken_seconds": rng.uniform(35.0, 50.0),
            "typing_cadence_variance_ms": rng.uniform(12.0, 25.0),
            "paste_detected": False,
            "paste_count": 0,
            "focus_paste_coincidence": False,
            "tab_switches_during_form": 5,
            "trap_question_response": _BORDER_TRAP,
            "other_responses": ["I am a junior web designer."],
            "github_account_age_days": rng.randint(10, 25),
            "github_public_repos": rng.randint(1, 3),
            "github_followers": rng.randint(1, 2),
            "keystroke_intervals_ms": _human_intervals(rng, rng.randint(8, 20)),
            "expected_status": "FLAGGED_FOR_REVIEW",
            "role": role,
        }
    raise ValueError(f"unknown synthetic role {role!r}")


def _human_intervals(rng: random.Random, count: int) -> list[float]:
    gaps: list[float] = []
    for _ in range(count):
        gap = math.exp(rng.gauss(math.log(180.0), 0.35))
        gaps.append(min(900.0, max(40.0, gap)))
    return gaps


def _noise_count(
    name: str,
    true_count: int,
    epsilon: float,
    rng: random.Random,
    accountant: PrivacyAccountant,
    note: str,
) -> dict[str, object]:
    sensitivity = 1.0
    scale = laplace_scale(sensitivity, epsilon)
    accountant.spend(name, epsilon, "laplace", sensitivity, note=note)
    noisy = laplace_mechanism(float(true_count), sensitivity, epsilon, rng)
    return {
        "mechanism": "laplace",
        "epsilon": epsilon,
        "sensitivity": sensitivity,
        "scale": scale,
        "noisy": noisy,
        "published": max(0.0, noisy),
    }


def _noise_histogram(
    name: str,
    labels: Sequence[str],
    counts: Sequence[int],
    epsilon: float,
    rng: random.Random,
    accountant: PrivacyAccountant,
    note: str,
) -> dict[str, object]:
    sensitivity = 2.0
    scale = laplace_scale(sensitivity, epsilon)
    accountant.spend(name, epsilon, "laplace", sensitivity, note=note)
    noisy = laplace_histogram([float(count) for count in counts], sensitivity, epsilon, rng)
    return {
        "bins": list(labels),
        "mechanism": "laplace",
        "epsilon": epsilon,
        "sensitivity_l1": sensitivity,
        "scale": scale,
        "noisy": noisy,
        "published": [max(0.0, value) for value in noisy],
    }


def _tab_bin(tabs: int) -> int:
    if tabs <= 0:
        return 0
    if tabs <= 2:
        return 1
    if tabs <= 4:
        return 2
    if tabs <= 8:
        return 3
    return 4


def _cadence_bin(variance: float) -> int:
    if variance < 5.0:
        return 0
    if variance < 15.0:
        return 1
    if variance < 40.0:
        return 2
    return 3
