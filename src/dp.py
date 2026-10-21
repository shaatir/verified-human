"""Pure ε differential privacy for Verified-Human analytics.

Integer counts use the discrete Laplace (two-sided geometric) mechanism.
Booleans use randomized response. The keystroke histogram uses optimized
unary encoding (OUE). Nothing here adds a continuous Laplace draw to a
secret and rounds it.

Floating-point Laplace (Mironov, 2012)
---------------------------------------
Sampling Laplace noise in IEEE-754 and adding it to a secret does not
implement the Laplace mechanism. The representable outputs have gaps that
depend on the magnitude of the secret, so the likelihood ratio can be
infinite even when the scale is sensitivity/ε. A 32-bit uniform fed through
the inverse CDF makes this worse: only 2^32 noise values exist, and the
tails are truncated. This module does not do that. Discrete Laplace returns
an integer, and the secret is added with integer arithmetic. The support is
every integer, because the geometric sampler is a Bernoulli loop with no
hard cap.

Privacy unit
------------
Local privacy is one device-day, not one button click. The first export of
a day draws the noise and stores it (RAPPOR-style permanent randomized
response). Later exports that day replay the same answers, so averaging
repeats does not cancel the noise. Replays spend no extra epsilon. A daily
transmission cap and a lifetime epsilon cap are enforced by ``DeviceLedger``.

Central privacy is one dataset ledger. A publication is stored with its
spend. Re-running it replays the stored noisy values. A new batch that would
exceed the remaining budget is refused and charges nothing.

Individual approve / flag / reject decisions are not differentially private.
"""

from __future__ import annotations

import math
import random
from typing import Mapping, Sequence


LOCAL_EPSILON_DEFAULT = 1.0
CENTRAL_EPSILON_DEFAULT = 1.0
DATASET_EPSILON_BUDGET = 1.0

# One device may transmit the day's memoized report this many times.
# Further transmissions are refused. They are not a fresh mechanism.
DAILY_EXPORT_CAP = 2
# Basic composition across days. After this much lifetime spend, the device
# stops exporting. Eight days at ε = 1.
LIFETIME_EPSILON_CAP = 8.0

PASTE_COUNT_CLIP = 5
TAB_SWITCH_CLIP = 4

EXCESSIVE_TAB_THRESHOLD = 4
FAST_SUBMISSION_SECONDS = 30.0
LOW_VARIANCE_MS = 5.0

# Three cadence bins plus an explicit unknown bin. One sampled gap per client,
# not a noisy copy of the whole timing vector.
KEYSTROKE_BIN_EDGES_MS: tuple[float, ...] = (80.0, 250.0)
KEYSTROKE_BIN_LABELS: tuple[str, ...] = (
    "[0, 80)",
    "[80, 250)",
    "[250, inf)",
    "unknown",
)

# Percents of the device-day epsilon. The last share absorbs the remainder.
# Tab switches and the histogram get enough of the budget to be usable at
# n = 2000. The fraud predicates keep the rest.
LOCAL_SHARES: tuple[tuple[str, int], ...] = (
    ("paste_detected", 22),
    ("focus_paste_coincidence", 4),
    ("excessive_tab_switches", 8),
    ("fast_submission", 4),
    ("low_cadence_variance", 12),
    ("paste_count", 8),
    ("tab_switches", 22),
    ("keystroke_histogram", 20),
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
LOCAL_DISCRETE_LAPLACE: dict[str, int] = {
    "paste_count": PASTE_COUNT_CLIP,
    "tab_switches": TAB_SWITCH_CLIP,
}

# Sketch sizes used only by the comparison benchmark, not by the release.
CMS_WIDTH = 32
CMS_DEPTH = 8
HCMS_WIDTH = 8

_SHARE_TABLES = (LOCAL_SHARES, CENTRAL_SHARES)
for _shares in _SHARE_TABLES:
    if sum(share for _, share in _shares) != 100:
        raise RuntimeError("privacy budget shares must sum to 100")


class PrivacyBudgetExceeded(RuntimeError):
    """The batch would exceed the declared budget. Nothing was charged."""


class ExportCapExceeded(RuntimeError):
    """The device already transmitted today's memoized report the allowed number of times."""


def allocate_budget(
    total_epsilon: float, shares: Sequence[tuple[str, int]]
) -> dict[str, float]:
    """Split ``total_epsilon`` by integer percents. The last share gets the remainder."""
    total_epsilon = _require_positive_epsilon(total_epsilon)
    if sum(share for _, share in shares) != 100:
        raise ValueError("shares must sum to 100")
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
    """Values ``web/dp.js`` must match."""
    return {
        "local_epsilon_default": LOCAL_EPSILON_DEFAULT,
        "daily_export_cap": DAILY_EXPORT_CAP,
        "lifetime_epsilon_cap": LIFETIME_EPSILON_CAP,
        "paste_count_clip": PASTE_COUNT_CLIP,
        "tab_switch_clip": TAB_SWITCH_CLIP,
        "excessive_tab_threshold": EXCESSIVE_TAB_THRESHOLD,
        "fast_submission_seconds": FAST_SUBMISSION_SECONDS,
        "low_variance_ms": LOW_VARIANCE_MS,
        "keystroke_bin_edges_ms": list(KEYSTROKE_BIN_EDGES_MS),
        "keystroke_bin_labels": list(KEYSTROKE_BIN_LABELS),
        "local_shares": [[name, share] for name, share in LOCAL_SHARES],
    }


def rr_probabilities(epsilon: float) -> tuple[float, float]:
    """Return ``(p_truth, p_flip)`` for binary ε-local randomized response."""
    epsilon = _require_positive_epsilon(epsilon)
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
    """Unbiased estimate of the mean of the secret bits. Post-processing."""
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


def _geometric_failures(success_probability: float, rng: random.Random) -> int:
    """Failures before the first success. Support is every non-negative integer.

    Inverse CDF: ``floor(log(U) / log(1 - p))`` for ``U`` uniform on (0, 1).
    There is no cutoff such as ``|Z| <= K``. A cutoff would put probability 0
    on integers the mechanism has to be able to emit, and pure DP would fail.
    A float64 uniform cannot represent values below about ``1e-323``; that is
    the same granularity as a Bernoulli loop that compares floats to ``p``.
    The secret is never added to this float. This is not the continuous Laplace
    inverse CDF that Mironov (2012) showed can leak an integer query.
    """
    if not 0.0 < success_probability <= 1.0:
        raise ValueError(f"success probability must be in (0, 1], got {success_probability!r}")
    if success_probability >= 1.0:
        return 0
    uniform = rng.random()
    while uniform <= 0.0:
        uniform = rng.random()
    failures = math.floor(math.log(uniform) / math.log1p(-success_probability))
    if failures < 0:
        return 0
    return int(failures)


def sample_discrete_laplace(epsilon: float, sensitivity: int, rng: random.Random) -> int:
    """Two-sided geometric noise.

    ``P(Z = k) = ((α - 1) / (α + 1)) α^{-|k|}`` with ``α = exp(ε / Δ)``.
    Sampled as the difference of two geometric random variables with success
    probability ``1 - exp(-ε / Δ)``. Adding this integer to an integer query
    is the discrete Laplace mechanism, which is ε-DP for integer sensitivity Δ.
    """
    epsilon = _require_positive_epsilon(epsilon)
    if not isinstance(sensitivity, int) or isinstance(sensitivity, bool) or sensitivity < 0:
        raise ValueError(f"sensitivity must be a non-negative integer, got {sensitivity!r}")
    if sensitivity == 0:
        return 0
    success = -math.expm1(-epsilon / sensitivity)
    if success >= 1.0:
        return 0
    if success <= 0.0:
        raise ValueError("discrete Laplace success probability collapsed")
    return _geometric_failures(success, rng) - _geometric_failures(success, rng)


def discrete_laplace_variance(epsilon: float, sensitivity: int) -> float:
    """Exact variance of the two-sided geometric noise, ``2 (1 - p) / p^2``."""
    success = -math.expm1(-epsilon / sensitivity)
    if success <= 0.0 or success > 1.0:
        raise ValueError("variance is undefined for this epsilon and sensitivity")
    return 2.0 * (1.0 - success) / (success * success)


def discrete_laplace_mechanism(
    value: int, sensitivity: int, epsilon: float, rng: random.Random
) -> int:
    """Integer query plus discrete Laplace noise. No float addition."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"discrete Laplace query must be an int, got {value!r}")
    return value + sample_discrete_laplace(epsilon, sensitivity, rng)


def oue_probabilities(epsilon: float) -> tuple[float, float]:
    """Optimized unary encoding (Wang et al., USENIX Security 2017).

    ``p = P(1 | 1) = 1/2`` and ``q = P(1 | 0) = 1 / (e^ε + 1)``.
    These satisfy ``ln(p (1 - q) / ((1 - p) q)) = ε``.
    """
    epsilon = _require_positive_epsilon(epsilon)
    if epsilon >= 700:
        return 0.5, 0.0
    return 0.5, 1.0 / (math.exp(epsilon) + 1.0)


def oue_encode(index: int, domain: int, epsilon: float, rng: random.Random) -> list[int]:
    """Perturb a one-hot vector of width ``domain``."""
    if domain < 1 or not 0 <= index < domain:
        raise ValueError(f"OUE index {index} is outside domain {domain}")
    p_keep, q_flip = oue_probabilities(epsilon)
    encoded: list[int] = []
    for position in range(domain):
        if position == index:
            encoded.append(1 if rng.random() < p_keep else 0)
        else:
            encoded.append(1 if rng.random() < q_flip else 0)
    return encoded


def oue_debias_mean(reports: Sequence[Sequence[int]], epsilon: float) -> list[float]:
    """Unbiased estimate of the mean one-hot vector. Post-processing."""
    if not reports:
        raise ValueError("OUE debiasing needs at least one report")
    p_keep, q_flip = oue_probabilities(epsilon)
    gap = p_keep - q_flip
    width = len(reports[0])
    totals = [0.0] * width
    for report in reports:
        if len(report) != width:
            raise ValueError("OUE reports must share a domain")
        for position, bit in enumerate(report):
            if bit not in (0, 1):
                raise ValueError("OUE bits must be 0 or 1")
            totals[position] += bit
    count = float(len(reports))
    return [(total / count - q_flip) / gap for total in totals]


def keystroke_bin_index(interval_ms: float) -> int:
    if not math.isfinite(interval_ms) or interval_ms < 0:
        raise ValueError(f"keystroke interval must be finite and >= 0, got {interval_ms!r}")
    for index, edge in enumerate(KEYSTROKE_BIN_EDGES_MS):
        if interval_ms < edge:
            return index
    return len(KEYSTROKE_BIN_EDGES_MS)


def sample_keystroke_item(intervals_ms: Sequence[float], rng: random.Random) -> int:
    """One uniform gap, or the unknown bin when the client typed nothing.

    One item per client is what OUE expects. Subsampling is part of the query,
    chosen without looking at the gap values beyond drawing an index, so it
    does not spend privacy on its own. The estimand is the mean of the
    per-client distributions.
    """
    if not intervals_ms:
        return len(KEYSTROKE_BIN_EDGES_MS)
    choice = intervals_ms[rng.randrange(len(intervals_ms))]
    return keystroke_bin_index(float(choice))


def local_contribution(telemetry: Mapping[str, object], rng: random.Random) -> dict[str, object]:
    """Pre-noise contribution. Confidential. Not a release.

    Missing time, variance, and tab counts are unknown. Unknown predicates are
    false. They are not imputed to the suspicious side of a threshold.
    A missing tab count contributes the non-suspicious endpoint 0 to the
    clipped integer query; the excessive-tab predicate stays false.
    """
    view = _local_view(telemetry)
    view["keystroke_item"] = sample_keystroke_item(view["intervals"], rng)  # type: ignore[arg-type]
    return view


def local_dp_mechanism(
    telemetry: Mapping[str, object],
    epsilon: float = LOCAL_EPSILON_DEFAULT,
    rng: random.Random | None = None,
) -> dict[str, object]:
    """One fresh local report. Callers that export to a collector must memoize it.

    Repeating this function on the same input draws independent noise. Averaging
    those draws removes the noise and is not what a device ledger does.
    """
    generator = rng if rng is not None else random.SystemRandom()
    budget = allocate_budget(epsilon, LOCAL_SHARES)
    view = _local_view(telemetry)
    values: dict[str, object] = {}
    rr_parameters: dict[str, dict[str, float]] = {}
    for name in LOCAL_RR_QUERIES:
        query_epsilon = budget[name]
        p_truth, p_flip = rr_probabilities(query_epsilon)
        values[name] = randomized_response(bool(view[name]), query_epsilon, generator)
        rr_parameters[name] = {
            "epsilon": query_epsilon,
            "p_truth": p_truth,
            "p_flip": p_flip,
        }

    laplace_parameters: dict[str, dict[str, object]] = {}
    for name, sensitivity in LOCAL_DISCRETE_LAPLACE.items():
        query_epsilon = budget[name]
        values[name] = discrete_laplace_mechanism(
            int(view[name]), sensitivity, query_epsilon, generator
        )
        laplace_parameters[name] = {
            "epsilon": query_epsilon,
            "sensitivity": sensitivity,
            "clip": [0, sensitivity],
            "distribution": "discrete_laplace",
        }

    hist_epsilon = budget["keystroke_histogram"]
    item = sample_keystroke_item(view["intervals"], generator)  # type: ignore[arg-type]
    values["keystroke_histogram"] = oue_encode(
        item, len(KEYSTROKE_BIN_LABELS), hist_epsilon, generator
    )
    p_keep, q_flip = oue_probabilities(hist_epsilon)
    return {
        "privacy_model": "local",
        "differentially_private": True,
        "definition": "pure epsilon local DP, basic composition, one draw",
        "neighboring_relation": "any two telemetry records from one client",
        "epsilon": float(epsilon),
        "memoized": False,
        "raw_keystrokes_included": False,
        "individual_decision_included": False,
        "values": values,
        "public_parameters": {
            "rr_probabilities": rr_parameters,
            "discrete_laplace": laplace_parameters,
            "keystroke_histogram": {
                "mechanism": "oue",
                "epsilon": hist_epsilon,
                "p_keep_one": p_keep,
                "q_flip_zero": q_flip,
                "bin_labels": list(KEYSTROKE_BIN_LABELS),
                "estimand": (
                    "mean of per-client cadence distributions, "
                    "one uniformly sampled gap per client; "
                    "no gaps is the unknown bin"
                ),
            },
            "thresholds": {
                "excessive_tab_switches": f"> {EXCESSIVE_TAB_THRESHOLD}",
                "fast_submission_seconds": f"< {FAST_SUBMISSION_SECONDS}",
                "low_cadence_variance_ms": f"< {LOW_VARIANCE_MS}",
                "missing": "unknown predicates are false and are not treated as suspicious",
            },
        },
        "accountant": _local_ledger(epsilon, budget),
    }


def aggregate_local_reports(reports: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Debias a batch of local reports. Post-processing; spends no budget.

    Repeats of one memoized report must not be passed in as if they were
    independent clients. They are the same draw.
    """
    if not reports:
        raise ValueError("need at least one local report")
    count = len(reports)
    first = reports[0]
    rr_meta = first["public_parameters"]["rr_probabilities"]  # type: ignore[index]
    rates: dict[str, dict[str, float]] = {}
    for name in LOCAL_RR_QUERIES:
        query_epsilon = float(rr_meta[name]["epsilon"])  # type: ignore[index]
        bits = [int(report["values"][name]) for report in reports]  # type: ignore[index]
        rates[name] = {
            "debiased_rate": debias_rr_mean(bits, query_epsilon),
            "epsilon": query_epsilon,
        }
    means = {
        name: sum(int(report["values"][name]) for report in reports) / count  # type: ignore[index]
        for name in LOCAL_DISCRETE_LAPLACE
    }
    hist_epsilon = float(first["public_parameters"]["keystroke_histogram"]["epsilon"])  # type: ignore[index]
    vectors = [report["values"]["keystroke_histogram"] for report in reports]  # type: ignore[index]
    return {
        "n": count,
        "privacy_spend": 0.0,
        "note": "post-processing; do not feed repeated memoized exports in as new clients",
        "randomized_response_rates": rates,
        "discrete_laplace_means": means,
        "keystroke_histogram_mean": oue_debias_mean(vectors, hist_epsilon),  # type: ignore[arg-type]
    }


def basic_composition(releases: int, epsilon: float) -> float:
    """k-fold pure composition. The ledger uses this."""
    if releases < 0:
        raise ValueError("releases must be >= 0")
    return releases * _require_positive_epsilon(epsilon) if releases else 0.0


def advanced_composition(releases: int, epsilon: float, delta: float) -> float:
    """Generic advanced composition (Dwork, Rothblum, Vadhan).

    k pure ε-DP mechanisms are ``(ε', δ)``-DP for
    ``ε' = sqrt(2 k ln(1/δ)) ε + k ε (e^ε - 1)``.
    The bound is often *looser* than basic composition when ε is not small.
    """
    epsilon = _require_positive_epsilon(epsilon)
    delta = _require_delta(delta)
    if releases <= 0:
        return 0.0
    return (
        math.sqrt(2.0 * releases * math.log(1.0 / delta)) * epsilon
        + releases * epsilon * (math.exp(epsilon) - 1.0)
    )


def zcdp_to_approximate(releases: int, epsilon: float, delta: float) -> float:
    """Convert the zCDP bound implied by pure DP (Bun, Steinke).

    ε-DP implies ρ-zCDP with ``ρ = ε² / 2``. k-fold zCDP adds ρ.
    ``ρ + 2 sqrt(ρ ln(1/δ))`` is an approximate-DP epsilon.
    """
    epsilon = _require_positive_epsilon(epsilon)
    delta = _require_delta(delta)
    if releases <= 0:
        return 0.0
    rho = releases * epsilon * epsilon / 2.0
    return rho + 2.0 * math.sqrt(rho * math.log(1.0 / delta))


def rdp_to_approximate(releases: int, epsilon: float, delta: float) -> float:
    """Minimize the RDP conversion of the same pure-DP curve over the order α.

    ε-DP implies (α, α ε² / 2)-RDP. The k-fold curve adds. Conversion is
    ``k α ε² / 2 + ln(1/δ) / (α - 1)``. This is the tight conversion of that
    upper bound, not a mechanism-specific RDP accountant.
    """
    epsilon = _require_positive_epsilon(epsilon)
    delta = _require_delta(delta)
    if releases <= 0:
        return 0.0
    log_term = math.log(1.0 / delta)
    best = float("inf")
    # Grid plus a refinement around the best point.
    for alpha in _rdp_orders():
        candidate = releases * alpha * epsilon * epsilon / 2.0 + log_term / (alpha - 1.0)
        if candidate < best:
            best = candidate
    return best


def shuffle_central_epsilon(epsilon_local: float, n: int, delta: float) -> float | None:
    """Central ε from shuffling n copies of an ε_local-LDP report.

    Numeric solution of Theorem 5.3 in Balle, Bell, Gascón, and Nissim,
    "The Privacy Blanket of the Shuffle Model" (CRYPTO 2019). ``C = 1 - e^{-2}``.
    Returns ``None`` when the bound does not prove any central epsilon at most
    the local one. This is an upper bound for a shuffled batch. This repository
    does not run a shuffler; the number is what the batch would be worth if the
    collector saw the reports without user identifiers.
    """
    epsilon_local = _require_positive_epsilon(epsilon_local)
    delta = _require_delta(delta)
    if n < 1:
        raise ValueError("shuffle amplification needs at least one report")
    constant = 1.0 - math.exp(-2.0)
    local_gap = math.exp(epsilon_local) - math.exp(-epsilon_local)

    def holds(epsilon_central: float) -> bool:
        ee = math.exp(epsilon_central)
        minus = ee - 1.0
        plus = ee + 1.0
        fraction = (minus * minus) / (plus * plus * local_gap * local_gap)
        inside = min(math.exp(-epsilon_local), fraction)
        prefactor = (plus * plus * local_gap * local_gap) / (4.0 * n * minus)
        return prefactor * math.exp(-constant * n * inside) <= delta

    if not holds(epsilon_local):
        return None
    low = 1e-12
    high = epsilon_local
    for _ in range(70):
        mid = 0.5 * (low + high)
        if holds(mid):
            high = mid
        else:
            low = mid
    return high


def audit_epsilon_from_outputs(
    outputs_a: Sequence[object],
    outputs_b: Sequence[object],
    min_count: int = 20,
) -> float:
    """Lower-bound style empirical epsilon from two neighboring input runs.

    For every output that appears at least ``min_count`` times under both
    inputs, take ``|log(rate_a / rate_b)|``. The maximum is the estimated ε.
    Sparse outputs are ignored so a single unlucky bin does not invent an
    infinite ratio. The estimate is a bit low when the true worst-case output
    is rare; the tests check a mechanism whose worst case is common.
    """
    if not outputs_a or not outputs_b:
        raise ValueError("audit needs samples from both neighboring inputs")
    counts_a: dict[object, int] = {}
    counts_b: dict[object, int] = {}
    for output in outputs_a:
        key = _audit_key(output)
        counts_a[key] = counts_a.get(key, 0) + 1
    for output in outputs_b:
        key = _audit_key(output)
        counts_b[key] = counts_b.get(key, 0) + 1
    total_a = float(len(outputs_a))
    total_b = float(len(outputs_b))
    estimated = 0.0
    seen = False
    for key, count_a in counts_a.items():
        count_b = counts_b.get(key, 0)
        if count_a < min_count or count_b < min_count:
            continue
        seen = True
        ratio = math.log((count_a / total_a) / (count_b / total_b))
        estimated = max(estimated, abs(ratio))
    if not seen:
        raise ValueError("audit found no output with enough samples on both sides")
    return estimated


def cms_encode(
    item: int,
    domain: int,
    epsilon: float,
    rng: random.Random,
    width: int = CMS_WIDTH,
    depth: int = CMS_DEPTH,
) -> tuple[int, list[int]]:
    """Apple-style count-mean sketch client for one domain element.

    Pick one of ``depth`` hash functions, one-hot encode into ``width`` buckets,
    and flip every bit with probability ``1 / (1 + e^{ε/2})``. The ε/2 in the
    flip probability is the symmetric randomized response Apple uses so the
    vector plus the hash index is ε-LDP. This is a benchmark, not the release.
    """
    if not 0 <= item < domain:
        raise ValueError("CMS item is outside the domain")
    row = rng.randrange(depth)
    bucket = _hash_bucket(row, item, width)
    flip = 1.0 / (1.0 + math.exp(epsilon / 2.0))
    vector: list[int] = []
    for index in range(width):
        truth = 1 if index == bucket else 0
        vector.append(1 - truth if rng.random() < flip else truth)
    return row, vector


def cms_debias_frequencies(
    reports: Sequence[tuple[int, Sequence[int]]],
    domain: int,
    epsilon: float,
    width: int = CMS_WIDTH,
    depth: int = CMS_DEPTH,
) -> list[float]:
    """Average debiased CMS counters into a frequency estimate on ``domain``."""
    flip = 1.0 / (1.0 + math.exp(epsilon / 2.0))
    keep = 1.0 - flip
    gap = keep - flip
    sums = [[0.0 for _ in range(width)] for _ in range(depth)]
    users = [0 for _ in range(depth)]
    for row, vector in reports:
        users[row] += 1
        for index, bit in enumerate(vector):
            sums[row][index] += (bit - flip) / gap
    if not reports:
        raise ValueError("CMS debiasing needs reports")
    frequencies = [0.0] * domain
    for item in range(domain):
        total = 0.0
        for row in range(depth):
            if users[row] == 0:
                continue
            bucket = _hash_bucket(row, item, width)
            total += sums[row][bucket] / users[row]
        frequencies[item] = total / depth
    return frequencies


def hcms_encode(
    item: int,
    domain: int,
    epsilon: float,
    rng: random.Random,
    width: int = HCMS_WIDTH,
) -> tuple[int, int]:
    """Hadamard count-mean sketch: one Hadamard row and one randomized bit.

    ``width`` is a power of two and at least the domain. The client sends the
    row index and a symmetric-RR bit of the Hadamard entry, which is the
    compression step in Apple's HCMS. Benchmark only.
    """
    if width < domain or width & (width - 1):
        raise ValueError("HCMS width must be a power of two and at least the domain")
    if not 0 <= item < domain:
        raise ValueError("HCMS item is outside the domain")
    row = rng.randrange(width)
    entry = _hadamard_sign(row, item)
    truth = 1 if entry > 0 else 0
    flip = 1.0 / (1.0 + math.exp(epsilon / 2.0))
    bit = 1 - truth if rng.random() < flip else truth
    return row, bit


def hcms_debias_frequencies(
    reports: Sequence[tuple[int, int]],
    domain: int,
    epsilon: float,
    width: int = HCMS_WIDTH,
) -> list[float]:
    """Reconstruct frequencies from HCMS (row, bit) reports."""
    flip = 1.0 / (1.0 + math.exp(epsilon / 2.0))
    keep = 1.0 - flip
    gap = keep - flip
    frequencies = [0.0] * domain
    count = len(reports)
    if count == 0:
        raise ValueError("HCMS debiasing needs reports")
    for item in range(domain):
        total = 0.0
        for row, bit in reports:
            debiased = (bit - flip) / gap
            # Map {0, 1} back toward {-1, +1} and multiply by the Hadamard sign.
            centered = 2.0 * debiased - 1.0
            total += centered * _hadamard_sign(row, item)
        frequencies[item] = total / count
    return frequencies


def _local_view(telemetry: Mapping[str, object]) -> dict[str, object]:
    paste_detected = _optional_bool(telemetry, "paste_detected")
    if paste_detected is None:
        paste_detected = False
    if _present(telemetry, "paste_count"):
        paste_count = int(round(_finite(telemetry["paste_count"], "paste_count")))
    else:
        paste_count = 1 if paste_detected else 0
    focus_paste = _optional_bool(telemetry, "focus_paste_coincidence")
    if focus_paste is None:
        focus_paste = False

    if _present(telemetry, "tab_switches"):
        tab_switches: int | None = int(round(_finite(telemetry["tab_switches"], "tab_switches")))
    elif _present(telemetry, "tab_switches_during_form"):
        tab_switches = int(round(_finite(telemetry["tab_switches_during_form"], "tab_switches")))
    else:
        tab_switches = None

    raw_intervals = telemetry.get("keystroke_intervals_ms", [])
    if raw_intervals is None:
        raw_intervals = []
    if not isinstance(raw_intervals, (list, tuple)):
        raise TypeError("keystroke_intervals_ms must be a list of millisecond gaps")
    intervals = [_finite(value, "keystroke interval") for value in raw_intervals]

    if _present(telemetry, "typing_cadence_variance_ms"):
        variance: float | None = _finite(
            telemetry["typing_cadence_variance_ms"], "typing_cadence_variance_ms"
        )
    elif len(intervals) >= 2:
        variance = _population_variance(intervals)
    else:
        variance = None

    if _present(telemetry, "time_taken_seconds"):
        fast_submission = _finite(telemetry["time_taken_seconds"], "time_taken_seconds") < FAST_SUBMISSION_SECONDS
    elif _present(telemetry, "time"):
        fast_submission = _finite(telemetry["time"], "time_taken_seconds") < FAST_SUBMISSION_SECONDS
    else:
        fast_submission = False

    excessive = False if tab_switches is None else tab_switches > EXCESSIVE_TAB_THRESHOLD
    # Unknown tab counts contribute the non-suspicious endpoint, not a large count.
    clipped_tabs = 0 if tab_switches is None else _clip_int(tab_switches, 0, TAB_SWITCH_CLIP)
    return {
        "paste_detected": paste_detected,
        "paste_count": _clip_int(paste_count, 0, PASTE_COUNT_CLIP),
        "focus_paste_coincidence": focus_paste,
        "tab_switches": clipped_tabs,
        "tab_switches_known": tab_switches is not None,
        "excessive_tab_switches": excessive,
        "fast_submission": fast_submission,
        "low_cadence_variance": False if variance is None else variance < LOW_VARIANCE_MS,
        "variance_known": variance is not None,
        "intervals": intervals,
    }


def _local_ledger(epsilon: float, budget: Mapping[str, float]) -> dict[str, object]:
    entries = []
    for name in LOCAL_RR_QUERIES:
        entries.append({
            "name": name,
            "epsilon": budget[name],
            "mechanism": "randomized_response",
            "sensitivity": 1,
            "note": "permanent randomized response; replay does not redraw",
        })
    for name, sensitivity in LOCAL_DISCRETE_LAPLACE.items():
        entries.append({
            "name": name,
            "epsilon": budget[name],
            "mechanism": "discrete_laplace",
            "sensitivity": sensitivity,
            "note": "integer geometric mechanism",
        })
    entries.append({
        "name": "keystroke_histogram",
        "epsilon": budget["keystroke_histogram"],
        "mechanism": "oue",
        "sensitivity": 1,
        "note": "one sampled cadence bin; optimized unary encoding",
    })
    spent = sum(float(entry["epsilon"]) for entry in entries)
    return {
        "composition": "basic",
        "total_epsilon": epsilon,
        "spent_epsilon": spent,
        "remaining_epsilon": epsilon - spent,
        "entries": entries,
    }


def _population_variance(values: Sequence[float]) -> float:
    count = len(values)
    mean = sum(values) / count
    return sum((value - mean) ** 2 for value in values) / count


def _clip_int(value: int, low: int, high: int) -> int:
    if value < low:
        return low
    if value > high:
        return high
    return value


def _hash_bucket(row: int, item: int, width: int) -> int:
    # Odd slope so the map is a permutation when width is a power of two,
    # and still a reasonable hash otherwise.
    slope = 2 * row + 1
    return (slope * (item + 1) + row * 17) % width


def _hadamard_sign(row: int, column: int) -> int:
    return 1 if (row & column).bit_count() % 2 == 0 else -1


def _rdp_orders() -> list[float]:
    orders = [1.5, 1.75, 2, 2.5, 3, 4, 5, 6, 8, 10, 12, 16, 24, 32, 48, 64, 96, 128, 256]
    return [float(order) for order in orders]


def _audit_key(output: object) -> object:
    if isinstance(output, list):
        return tuple(output)
    return output


def _require_positive_epsilon(epsilon: float) -> float:
    if isinstance(epsilon, bool) or not isinstance(epsilon, (int, float)):
        raise ValueError(f"epsilon must be a positive number, got {epsilon!r}")
    epsilon = float(epsilon)
    if not math.isfinite(epsilon) or epsilon <= 0:
        raise ValueError(f"epsilon must be finite and > 0, got {epsilon!r}")
    return epsilon


def _require_delta(delta: float) -> float:
    if isinstance(delta, bool) or not isinstance(delta, (int, float)):
        raise ValueError(f"delta must be in (0, 1), got {delta!r}")
    delta = float(delta)
    if not math.isfinite(delta) or not 0.0 < delta < 1.0:
        raise ValueError(f"delta must be in (0, 1), got {delta!r}")
    return delta


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number, got {value!r}")
    return number


def _present(telemetry: Mapping[str, object], key: str) -> bool:
    return key in telemetry and telemetry[key] is not None


def _optional_bool(telemetry: Mapping[str, object], key: str) -> bool | None:
    if not _present(telemetry, key):
        return None
    value = telemetry[key]
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    raise ValueError(f"{key} must be a boolean, got {value!r}")
