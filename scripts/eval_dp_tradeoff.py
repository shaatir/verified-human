#!/usr/bin/env python3
"""Measure aggregate error against epsilon and write the evaluation note.

The cohort is fixed (seed 20261021, n = 2000). Each trial draws fresh mechanism
noise. A device ledger would memoize a client, so this script calls each local
mechanism once per client per trial and does not average repeats of one draw.
Central trials use a fresh temporary ledger only as the required accountant;
each trial is one publication, not a sequence of publications of the same cohort.

Outputs:
  docs/dp-evaluation.md
  docs/charts/error_vs_epsilon.svg
  docs/charts/composition.svg
"""

from __future__ import annotations

import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.analytics import exact_cohort_statistics, screen_cohort, synthesize_population
from src.dp import (
    CENTRAL_SHARES,
    KEYSTROKE_BIN_EDGES_MS,
    KEYSTROKE_BIN_LABELS,
    LOCAL_SHARES,
    TAB_SWITCH_CLIP,
    advanced_composition,
    allocate_budget,
    basic_composition,
    cms_debias_frequencies,
    cms_encode,
    debias_rr_mean,
    discrete_laplace_mechanism,
    hcms_debias_frequencies,
    hcms_encode,
    keystroke_bin_index,
    oue_debias_mean,
    oue_encode,
    rdp_to_approximate,
    randomized_response,
    sample_keystroke_item,
    shuffle_central_epsilon,
    zcdp_to_approximate,
)

N = 2000
TRIALS = 200
SKETCH_TRIALS = 40
EPSILONS = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)
SEED = 20261021
DELTA = 1e-6
COMPOSITION_EPSILONS = (0.1, 1.0)
COMPOSITION_RELEASES = (1, 2, 4, 8, 16, 32, 64, 128)

CHART_DIR = os.path.join(ROOT, "docs", "charts")
DOC_PATH = os.path.join(ROOT, "docs", "dp-evaluation.md")


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _l1(left: list[float], right: list[float]) -> float:
    return sum(abs(a - b) for a, b in zip(left, right))


def _client_histogram(population: list[dict]) -> list[float]:
    """Mean of the per-client gap distributions. One uniform gap is unbiased for this."""
    width = len(KEYSTROKE_BIN_LABELS)
    totals = [0.0] * width
    unknown = len(KEYSTROKE_BIN_EDGES_MS)
    for person in population:
        intervals = person["keystroke_intervals_ms"]
        if not intervals:
            totals[unknown] += 1.0
            continue
        counts = [0] * width
        for gap in intervals:
            counts[keystroke_bin_index(float(gap))] += 1
        scale = float(len(intervals))
        for index, count in enumerate(counts):
            totals[index] += count / scale
    return [value / len(population) for value in totals]


def _measure(population: list[dict], decisions: list[dict]) -> dict:
    exact = exact_cohort_statistics(population, decisions)
    n = len(population)
    paste = [bool(person["paste_detected"]) for person in population]
    low_var = [float(person["typing_cadence_variance_ms"]) < 5.0 for person in population]
    tabs = [int(person["tab_switches_during_form"]) for person in population]
    excessive = [value > 4 for value in tabs]
    clipped = [min(TAB_SWITCH_CLIP, max(0, value)) for value in tabs]
    intervals = [person["keystroke_intervals_ms"] for person in population]
    return {
        "n": n,
        "paste_rate": sum(paste) / n,
        "low_var_rate": sum(low_var) / n,
        "excessive_rate": sum(excessive) / n,
        "clipped_tab_mean": sum(clipped) / n,
        "unclipped_tab_mean": sum(tabs) / n,
        "histogram": _client_histogram(population),
        "paste": paste,
        "low_var": low_var,
        "excessive": excessive,
        "clipped": clipped,
        "intervals": intervals,
        "exact": exact,
        "routing_matches": sum(
            decision["status"] == person["expected_status"]
            for decision, person in zip(decisions, population)
        ),
    }


def _run_trials(truth: dict, rng: random.Random) -> dict[float, dict[str, float]]:
    n = truth["n"]
    results: dict[float, dict[str, float]] = {}
    for epsilon in EPSILONS:
        local = allocate_budget(epsilon, LOCAL_SHARES)
        central = allocate_budget(epsilon, CENTRAL_SHARES)
        paste_mae = 0.0
        excessive_mae = 0.0
        low_mae = 0.0
        tab_mae = 0.0
        hist_l1 = 0.0
        central_paste_mae = 0.0
        central_status_l1 = 0.0
        central_low_mae = 0.0
        central_excessive_mae = 0.0
        for _ in range(TRIALS):
            paste_bits = [
                randomized_response(bit, local["paste_detected"], rng) for bit in truth["paste"]
            ]
            excessive_bits = [
                randomized_response(bit, local["excessive_tab_switches"], rng)
                for bit in truth["excessive"]
            ]
            low_bits = [
                randomized_response(bit, local["low_cadence_variance"], rng)
                for bit in truth["low_var"]
            ]
            tab_sum = 0
            for value in truth["clipped"]:
                tab_sum += discrete_laplace_mechanism(
                    value, TAB_SWITCH_CLIP, local["tab_switches"], rng
                )
            vectors = []
            for gaps in truth["intervals"]:
                item = sample_keystroke_item(gaps, rng)
                vectors.append(oue_encode(item, len(KEYSTROKE_BIN_LABELS), local["keystroke_histogram"], rng))
            paste_mae += abs(debias_rr_mean(paste_bits, local["paste_detected"]) - truth["paste_rate"])
            excessive_mae += abs(
                debias_rr_mean(excessive_bits, local["excessive_tab_switches"]) - truth["excessive_rate"]
            )
            low_mae += abs(debias_rr_mean(low_bits, local["low_cadence_variance"]) - truth["low_var_rate"])
            tab_mae += abs(tab_sum / n - truth["clipped_tab_mean"])
            hist_l1 += _l1(oue_debias_mean(vectors, local["keystroke_histogram"]), truth["histogram"])

            noisy_paste = discrete_laplace_mechanism(
                int(truth["exact"]["paste_detected_count"]),
                1,
                central["paste_detected_count"],
                rng,
            )
            noisy_low = discrete_laplace_mechanism(
                int(truth["exact"]["low_variance_count"]),
                1,
                central["low_variance_count"],
                rng,
            )
            noisy_excessive = discrete_laplace_mechanism(
                int(truth["exact"]["excessive_tabs_count"]),
                1,
                central["excessive_tabs_count"],
                rng,
            )
            status_l1 = 0.0
            for count in truth["exact"]["status_histogram"]:
                noisy = discrete_laplace_mechanism(int(count), 2, central["status_histogram"], rng)
                status_l1 += abs(noisy - int(count))
            central_paste_mae += abs(noisy_paste / n - truth["paste_rate"])
            central_low_mae += abs(noisy_low / n - truth["low_var_rate"])
            central_excessive_mae += abs(noisy_excessive / n - truth["excessive_rate"])
            central_status_l1 += status_l1
        scale = float(TRIALS)
        results[epsilon] = {
            "local_paste_mae": paste_mae / scale,
            "local_excessive_mae": excessive_mae / scale,
            "local_low_mae": low_mae / scale,
            "local_tab_mae": tab_mae / scale,
            "local_hist_l1": hist_l1 / scale,
            "central_paste_mae": central_paste_mae / scale,
            "central_low_mae": central_low_mae / scale,
            "central_excessive_mae": central_excessive_mae / scale,
            "central_status_l1": central_status_l1 / scale,
        }
    return results


def _sketch_comparison(truth: dict, rng: random.Random) -> dict[str, float]:
    epsilon = allocate_budget(1.0, LOCAL_SHARES)["keystroke_histogram"]
    domain = len(KEYSTROKE_BIN_LABELS)
    totals = {"oue": 0.0, "cms": 0.0, "hcms": 0.0}
    for _ in range(SKETCH_TRIALS):
        items = [sample_keystroke_item(gaps, rng) for gaps in truth["intervals"]]
        target = [0.0] * domain
        for item in items:
            target[item] += 1.0
        target = [value / truth["n"] for value in target]
        oue = [oue_encode(item, domain, epsilon, rng) for item in items]
        cms = [cms_encode(item, domain, epsilon, rng) for item in items]
        hcms = [hcms_encode(item, domain, epsilon, rng) for item in items]
        totals["oue"] += _l1(oue_debias_mean(oue, epsilon), target)
        totals["cms"] += _l1(cms_debias_frequencies(cms, domain, epsilon), target)
        totals["hcms"] += _l1(hcms_debias_frequencies(hcms, domain, epsilon), target)
    return {name: value / SKETCH_TRIALS for name, value in totals.items()} | {"epsilon": epsilon}


def _fmt(value: float) -> str:
    return f"{value:.4f}"


def _svg_error(results: dict[float, dict[str, float]]) -> str:
    series = [
        ("Local paste rate", "#1f6feb", "local_paste_mae"),
        ("Local tab mean", "#9a6700", "local_tab_mae"),
        ("Local histogram L1", "#8250df", "local_hist_l1"),
        ("Central paste rate", "#1a7f37", "central_paste_mae"),
        ("Central status L1 / n", "#cf222e", "central_status_l1"),
    ]
    points: dict[str, list[tuple[float, float]]] = {}
    for name, _color, key in series:
        points[name] = []
        for eps in EPSILONS:
            value = results[eps][key]
            if key == "central_status_l1":
                value = value / N
            points[name].append((eps, max(value, 1e-6)))
    return _loglog_svg(
        [(name, color, points[name]) for name, color, _key in series],
        "Mean absolute error versus epsilon",
        "epsilon",
        "mean absolute error",
    )


def _loglog_svg(series: list[tuple[str, str, list[tuple[float, float]]]], title: str, xlabel: str, ylabel: str) -> str:
    width, height = 780, 520
    left, right, top, bottom = 78, 24, 46, 108
    xs = [math.log10(x) for _name, _color, pts in series for x, _y in pts]
    ys = [math.log10(y) for _name, _color, pts in series for _x, y in pts]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    pad_x = (max_x - min_x) * 0.08 or 0.1
    pad_y = (max_y - min_y) * 0.12 or 0.1
    min_x -= pad_x
    max_x += pad_x
    min_y -= pad_y
    max_y += pad_y

    def xy(x: float, y: float) -> tuple[float, float]:
        px = left + (math.log10(x) - min_x) / (max_x - min_x) * (width - left - right)
        py = top + (max_y - math.log10(y)) / (max_y - min_y) * (height - top - bottom)
        return px, py

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{width / 2}" y="28" text-anchor="middle" font-family="ui-sans-serif, sans-serif" font-size="16">{title}</text>',
    ]
    for decade in (0.25, 0.5, 1, 2, 4, 8):
        if min_x <= math.log10(decade) <= max_x:
            px, _ = xy(decade, 10 ** min_y)
            parts.append(f'<line x1="{px:.1f}" y1="{top}" x2="{px:.1f}" y2="{height - bottom}" stroke="#eaeef2"/>')
            parts.append(
                f'<text x="{px:.1f}" y="{height - bottom + 18}" text-anchor="middle" font-size="11" font-family="ui-sans-serif, sans-serif" fill="#57606a">{decade:g}</text>'
            )
    y_ticks = _log_ticks(10 ** min_y, 10 ** max_y)
    for tick in y_ticks:
        if min_y <= math.log10(tick) <= max_y:
            _, py = xy(10 ** min_x, tick)
            parts.append(f'<line x1="{left}" y1="{py:.1f}" x2="{width - right}" y2="{py:.1f}" stroke="#eaeef2"/>')
            parts.append(
                f'<text x="{left - 8}" y="{py + 4:.1f}" text-anchor="end" font-size="11" font-family="ui-sans-serif, sans-serif" fill="#57606a">{tick:g}</text>'
            )
        parts.append(
            f'<text x="{width / 2}" y="{height - bottom + 36}" text-anchor="middle" font-size="12" font-family="ui-sans-serif, sans-serif">{xlabel} (log)</text>'
        )
    parts.append(
        f'<text x="18" y="{height / 2}" text-anchor="middle" font-size="12" font-family="ui-sans-serif, sans-serif" transform="rotate(-90 18 {height / 2})">{ylabel} (log)</text>'
    )
    for index, (name, color, pts) in enumerate(series):
        path = " ".join(
            ("M" if i == 0 else "L") + f"{xy(x, y)[0]:.1f},{xy(x, y)[1]:.1f}" for i, (x, y) in enumerate(pts)
        )
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2"/>')
        for x, y in pts:
            px, py = xy(x, y)
            parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="{color}"/>')
        column = index % 3
        row = index // 3
        legend_x = 90 + column * 220
        legend_y = height - 36 + row * 18
        parts.append(f'<rect x="{legend_x}" y="{legend_y - 9}" width="12" height="12" fill="{color}"/>')
        parts.append(
            f'<text x="{legend_x + 18}" y="{legend_y}" font-size="12" font-family="ui-sans-serif, sans-serif">{name}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def _log_ticks(low: float, high: float) -> list[float]:
    ticks = []
    decade = 10 ** math.floor(math.log10(low))
    while decade <= high * 1.01:
        for factor in (1, 2, 5):
            tick = decade * factor
            if low / 1.2 <= tick <= high * 1.2:
                ticks.append(tick)
        decade *= 10
    return ticks


def _svg_composition() -> str:
    width, height = 920, 460
    panels = []
    for epsilon in COMPOSITION_EPSILONS:
        curves = {
            "basic": [basic_composition(k, epsilon) for k in COMPOSITION_RELEASES],
            "advanced": [advanced_composition(k, epsilon, DELTA) for k in COMPOSITION_RELEASES],
            "zCDP": [zcdp_to_approximate(k, epsilon, DELTA) for k in COMPOSITION_RELEASES],
            "RDP": [rdp_to_approximate(k, epsilon, DELTA) for k in COMPOSITION_RELEASES],
        }
        panels.append((epsilon, curves))
    colors = {"basic": "#1f6feb", "advanced": "#cf222e", "zCDP": "#1a7f37", "RDP": "#8250df"}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="460" y="26" text-anchor="middle" font-family="ui-sans-serif, sans-serif" font-size="16">'
        f'Generic composition bounds, δ = {DELTA:g}</text>',
    ]
    panel_width = 430
    for panel_index, (epsilon, curves) in enumerate(panels):
        origin_x = 50 + panel_index * 460
        top, bottom = 58, 48
        plot_w, plot_h = panel_width - 70, height - top - bottom
        max_y = max(max(values) for values in curves.values()) * 1.08
        last_index = max(1, len(COMPOSITION_RELEASES) - 1)

        def xy(index: int, value: float) -> tuple[float, float]:
            px = origin_x + (index / last_index) * plot_w
            py = top + (1 - value / max_y) * plot_h
            return px, py

        parts.append(
            f'<text x="{origin_x + plot_w / 2}" y="48" text-anchor="middle" font-size="13" font-family="ui-sans-serif, sans-serif">per-release ε = {epsilon:g}</text>'
        )
        for index, k in enumerate(COMPOSITION_RELEASES):
            px, _ = xy(index, 0)
            parts.append(f'<line x1="{px:.1f}" y1="{top}" x2="{px:.1f}" y2="{height - bottom}" stroke="#eaeef2"/>')
            parts.append(
                f'<text x="{px:.1f}" y="{height - bottom + 16}" text-anchor="middle" font-size="10" font-family="ui-sans-serif, sans-serif" fill="#57606a">{k}</text>'
            )
        for name, values in curves.items():
            path = " ".join(
                ("M" if i == 0 else "L") + f"{xy(i, value)[0]:.1f},{xy(i, value)[1]:.1f}"
                for i, value in enumerate(values)
            )
            parts.append(f'<path d="{path}" fill="none" stroke="{colors[name]}" stroke-width="2"/>')
        if panel_index == 0:
            for index, name in enumerate(curves):
                y = top + 16 + index * 16
                parts.append(f'<rect x="{origin_x + 8}" y="{y - 9}" width="12" height="12" fill="{colors[name]}"/>')
                parts.append(
                    f'<text x="{origin_x + 24}" y="{y}" font-size="12" font-family="ui-sans-serif, sans-serif">{name}</text>'
                )
    parts.append(
        '<text x="460" y="448" text-anchor="middle" font-size="12" font-family="ui-sans-serif, sans-serif">number of releases k</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def _composition_rows() -> list[str]:
    rows = [
        "| k | per-release ε | basic | advanced | zCDP | RDP |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for epsilon in COMPOSITION_EPSILONS:
        for k in COMPOSITION_RELEASES:
            rows.append(
                "| {k} | {eps:g} | {basic} | {advanced} | {zcdp} | {rdp} |".format(
                    k=k,
                    eps=epsilon,
                    basic=_fmt(basic_composition(k, epsilon)),
                    advanced=_fmt(advanced_composition(k, epsilon, DELTA)),
                    zcdp=_fmt(zcdp_to_approximate(k, epsilon, DELTA)),
                    rdp=_fmt(rdp_to_approximate(k, epsilon, DELTA)),
                )
            )
    return rows


def _write_doc(truth: dict, results: dict[float, dict[str, float]], sketches: dict[str, float], shuffle: float | None) -> None:
    at_one = results[1.0]
    lines = [
        "# Differential privacy evaluation",
        "",
        f"Synthetic cohort of {N} respondents, seed `{SEED}`, {TRIALS} independent noise trials.",
        "Per-respondent routing agreed with the labeled role on "
        f"**{truth['routing_matches']} / {N}** records. The scorer does not read the noisy values, so that agreement does not depend on epsilon.",
        "",
        "Each local trial draws the mechanism once per client. A device ledger would store that draw for the UTC day and replay it. Repeats are not averaged here, because averaging memoized answers would not remove noise and averaging fresh draws would.",
        "",
        "Central trials are separate single publications. They are not sequential spends of one dataset ledger. The default dataset budget is ε = 1, so one dashboard publication exhausts it and a rerun replays the stored integers.",
        "",
        "Error on a mean of n local reports falls like `1/sqrt(n)`, not `1/n`. Discrete Laplace on a clipped integer has variance `2(1-p)/p²` with `p = 1 - exp(-ε/Δ)`. The standard deviation of the mean is that standard deviation divided by `sqrt(n)`.",
        "",
        "## Accuracy versus epsilon",
        "",
        "Local tab error is against the mean after clipping to `[0, 4]`. "
        f"The clipped mean is **{_fmt(truth['clipped_tab_mean'])}**. "
        f"The unclipped mean is **{_fmt(truth['unclipped_tab_mean'])}**. "
        "Values above the clip, including the synthetic LLM and borderline tab counts, are biased downward on purpose so the sensitivity stays finite.",
        "",
        f"True paste rate **{_fmt(truth['paste_rate'])}**, excessive-tab rate **{_fmt(truth['excessive_rate'])}**, low-variance rate **{_fmt(truth['low_var_rate'])}**.",
        "",
        "| ε | local paste MAE | local excessive-tab MAE | local low-variance MAE | local tab MAE | local histogram L1 | central paste MAE | central status L1 |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for epsilon in EPSILONS:
        row = results[epsilon]
        lines.append(
            f"| {epsilon:g} | {_fmt(row['local_paste_mae'])} | {_fmt(row['local_excessive_mae'])} | "
            f"{_fmt(row['local_low_mae'])} | {_fmt(row['local_tab_mae'])} | {_fmt(row['local_hist_l1'])} | "
            f"{_fmt(row['central_paste_mae'])} | {_fmt(row['central_status_l1'])} |"
        )
    lines.extend([
        "",
        "![Error versus epsilon](charts/error_vs_epsilon.svg)",
        "",
        "The chart is log-log. Central status error is plotted as L1 divided by cohort size so it shares an axis with the rates. The table keeps the L1 in people.",
        "",
        f"At the default ε = 1 the local paste MAE is **{_fmt(at_one['local_paste_mae'])}**, "
        f"the clipped tab-switch MAE is **{_fmt(at_one['local_tab_mae'])}**, "
        f"and the keystroke histogram L1 is **{_fmt(at_one['local_hist_l1'])}**. "
        f"Central paste-rate MAE is **{_fmt(at_one['central_paste_mae'])}** and the status histogram L1 is **{_fmt(at_one['central_status_l1'])}** people.",
        "",
        "## Histogram mechanisms",
        "",
        "The release uses optimized unary encoding (Wang, Zheng, Wu, Zhao, USENIX Security 2017) on four bins: `[0, 80)`, `[80, 250)`, `[250, ∞)`, and `unknown`. One uniformly sampled gap per client. No gaps is the unknown bin. The estimand is the mean of the per-client distributions.",
        "",
        f"Count-mean sketch and Hadamard count-mean sketch (Apple, Learning with Privacy at Scale) are a benchmark at the histogram's share of ε = 1, which is ε = {_fmt(sketches['epsilon'])}. "
        f"{SKETCH_TRIALS} trials, same sampled items, error against that empirical one-hot mean:",
        "",
        "| mechanism | L1 |",
        "| --- | ---: |",
        f"| OUE (the release) | {_fmt(sketches['oue'])} |",
        f"| CMS, width 32, depth 8 | {_fmt(sketches['cms'])} |",
        f"| HCMS, width 8 | {_fmt(sketches['hcms'])} |",
        "",
        "CMS lands next to OUE. HCMS is worse: a Hadamard row is a compression step for a large domain, and four bins do not need it. The release stays OUE.",
        "",
        "## Composition",
        "",
        "These are generic bounds for composing pure ε-DP mechanisms. They are not a privacy-loss distribution of discrete Laplace. δ = 1e-6.",
        "",
        "Basic composition is `kε`. Advanced composition (Dwork, Rothblum, Vadhan) is `sqrt(2 k ln(1/δ)) ε + k ε (e^ε - 1)`. "
        "At ε = 1 that bound is looser than basic composition, including at k = 1. "
        "zCDP (Bun, Steinke) uses ρ = ε²/2 per release. RDP uses the same pure-DP curve, (α, α ε²/2), minimized over α. "
        "When the per-release epsilon is small, zCDP and RDP beat basic composition as k grows. The dataset ledger still records basic composition, which is valid at the default ε = 1 and does not depend on a δ.",
        "",
        *_composition_rows(),
        "",
        "![Composition bounds](charts/composition.svg)",
        "",
        "## Amplification by shuffling",
        "",
        "This repository does not shuffle reports. The bound below is what Theorem 5.3 of Balle, Bell, Gascón, and Nissim (CRYPTO 2019, The Privacy Blanket of the Shuffle Model) proves for a shuffled batch of n ε-local reports, with C = 1 - e^{-2}. It is an upper bound on a central epsilon, solved numerically. It is not a property of the server.",
        "",
    ])
    if shuffle is None:
        lines.append(
            f"For the composed local report at ε = 1, n = {N}, δ = {DELTA:g}, the bound does not prove a central epsilon at most 1."
        )
    else:
        lines.append(
            f"For the composed local report at ε = 1, n = {N}, δ = {DELTA:g}, the numeric bound is central **ε ≤ {_fmt(shuffle)}**."
        )
    lines.extend([
        "",
        "The whole local report is one ε-local message under basic composition of its queries, so the local epsilon in the formula is 1, not the share of a single predicate.",
        "",
        "## Mechanisms and the float issue",
        "",
        "Integer counts use discrete Laplace: the difference of two geometric random variables, added to the integer query with integer arithmetic. "
        "Sampling continuous Laplace noise in floating point and adding it to a secret does not implement the Laplace mechanism. "
        "The gaps between representable values depend on the magnitude of the secret, so the likelihood ratio can be infinite (Mironov, 2012). "
        "A single 32-bit uniform through the inverse CDF makes the support finite as well. This code does not do that.",
        "",
        "Missing time, missing variance, and a missing tab count are unknown. In the local predicates they are not treated as fast, low-variance, or excessive. "
        "In the central histograms they fall in an explicit unknown bin. The exact fraud scorer still uses its own defaults and can flag a missing field. Those paths are different on purpose.",
        "",
    ])
    os.makedirs(os.path.dirname(DOC_PATH), exist_ok=True)
    with open(DOC_PATH, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> None:
    rng = random.Random(SEED)
    population = synthesize_population(N, rng)
    decisions = screen_cohort(population)
    truth = _measure(population, decisions)
    # The truth measurement consumed `rng` only for synthesis. Restart the noise stream
    # from a fixed offset so the tables do not depend on how many random calls synthesis used.
    noise = random.Random(SEED + 1)
    results = _run_trials(truth, noise)
    sketches = _sketch_comparison(truth, random.Random(SEED + 2))
    shuffle = shuffle_central_epsilon(1.0, N, DELTA)
    os.makedirs(CHART_DIR, exist_ok=True)
    with open(os.path.join(CHART_DIR, "error_vs_epsilon.svg"), "w", encoding="utf-8") as handle:
        handle.write(_svg_error(results))
    with open(os.path.join(CHART_DIR, "composition.svg"), "w", encoding="utf-8") as handle:
        handle.write(_svg_composition())
    _write_doc(truth, results, sketches, shuffle)
    at_one = results[1.0]
    print(
        f"eps=1 local paste {_fmt(at_one['local_paste_mae'])} "
        f"tabs {_fmt(at_one['local_tab_mae'])} hist {_fmt(at_one['local_hist_l1'])} "
        f"central paste {_fmt(at_one['central_paste_mae'])} status L1 {_fmt(at_one['central_status_l1'])}"
    )
    print(
        f"sketch oue {_fmt(sketches['oue'])} cms {_fmt(sketches['cms'])} hcms {_fmt(sketches['hcms'])} "
        f"shuffle {shuffle}"
    )
    print(f"wrote {DOC_PATH}")


if __name__ == "__main__":
    main()
