#!/usr/bin/env python3
"""Accuracy versus epsilon for Verified-Human's differential-privacy releases.

The cohort is synthetic and fixed. Each trial redraws only the privacy noise.
Error is against the exact aggregate on that same cohort, not against a sample.
Per-respondent routing is scored on the raw records and does not consume noise,
so its agreement with the non-private pipeline does not depend on epsilon.

Writes docs/dp-evaluation.md and prints the same tables to stdout.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.analytics import (  # noqa: E402
    central_dashboard_release,
    exact_cohort_statistics,
    synthesize_population,
)
from src.dp import (  # noqa: E402
    LOCAL_RR_QUERIES,
    aggregate_local_releases,
    local_contribution,
    local_dp_release,
)
from src.pipeline import process_participant_screening  # noqa: E402

N = 2000
TRIALS = 30
EPSILONS = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)
SEED = 20261021
SMALL_COHORT_TRIALS = 200


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _l1(left: list[float], right: list[float]) -> float:
    return sum(abs(a - b) for a, b in zip(left, right))


def _local_telemetry(person: dict) -> dict:
    return {
        "paste_detected": person["paste_detected"],
        "paste_count": person["paste_count"],
        "focus_paste_coincidence": person["focus_paste_coincidence"],
        "tab_switches": person["tab_switches_during_form"],
        "time_taken_seconds": person["time_taken_seconds"],
        "typing_cadence_variance_ms": person["typing_cadence_variance_ms"],
        "keystroke_intervals_ms": person["keystroke_intervals_ms"],
    }


def _local_truth(population: list[dict]) -> dict[str, object]:
    rates = {name: [] for name in LOCAL_RR_QUERIES}
    paste_counts: list[float] = []
    tab_means: list[float] = []
    histogram = [0.0, 0.0, 0.0, 0.0, 0.0]
    for person in population:
        view = local_contribution(_local_telemetry(person))
        for name in LOCAL_RR_QUERIES:
            rates[name].append(1.0 if view[name] else 0.0)
        paste_counts.append(float(view["paste_count"]))
        tab_means.append(float(view["tab_switches"]))
        for index, value in enumerate(view["histogram"]):  # type: ignore[arg-type]
            histogram[index] += float(value)
    n = len(population)
    return {
        "rates": {name: _mean(values) for name, values in rates.items()},
        "paste_count_mean": _mean(paste_counts),
        "tab_mean": _mean(tab_means),
        "histogram": [value / n for value in histogram],
    }


def _fmt(value: float) -> str:
    return f"{value:.4f}"


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def evaluate() -> str:
    started = time.perf_counter()
    population = synthesize_population(N, random.Random(SEED))
    truth = _local_truth(population)
    decisions = []
    routing_hits = 0
    for person in population:
        decision = process_participant_screening(person)
        decisions.append(decision)
        if decision["status"] == person["expected_status"]:
            routing_hits += 1
    routing_agreement = routing_hits / len(population)
    exact = exact_cohort_statistics(population, decisions)

    local_rows: list[dict[str, float]] = []
    central_rows: list[dict[str, float]] = []
    bias_at_one: dict[str, float] = {}

    for epsilon_index, epsilon in enumerate(EPSILONS):
        local_abs = {
            "paste": [],
            "tabs_flag": [],
            "low_var": [],
            "tab_mean": [],
            "hist": [],
        }
        local_signed = {key: [] for key in local_abs}
        central_abs = {"status_l1": [], "paste": [], "paste_rate": []}
        central_signed = {"paste": []}

        for trial in range(TRIALS):
            rng = random.Random(SEED + 10007 * epsilon_index + trial)
            releases = [
                local_dp_release(_local_telemetry(person), epsilon=epsilon, rng=rng)
                for person in population
            ]
            aggregate = aggregate_local_releases(releases)
            rates = aggregate["randomized_response_rates"]
            paste_error = float(rates["paste_detected"]["debiased_rate"]) - float(truth["rates"]["paste_detected"])  # type: ignore[index]
            tab_flag_error = (
                float(rates["excessive_tab_switches"]["debiased_rate"])
                - float(truth["rates"]["excessive_tab_switches"])  # type: ignore[index]
            )
            low_var_error = (
                float(rates["low_cadence_variance"]["debiased_rate"])
                - float(truth["rates"]["low_cadence_variance"])  # type: ignore[index]
            )
            tab_mean_error = float(aggregate["laplace_means"]["tab_switches"]) - float(truth["tab_mean"])  # type: ignore[arg-type]
            hist_error = _l1(
                list(aggregate["keystroke_histogram_mean"]),  # type: ignore[arg-type]
                list(truth["histogram"]),  # type: ignore[arg-type]
            )
            local_signed["paste"].append(paste_error)
            local_signed["tabs_flag"].append(tab_flag_error)
            local_signed["low_var"].append(low_var_error)
            local_signed["tab_mean"].append(tab_mean_error)
            local_abs["paste"].append(abs(paste_error))
            local_abs["tabs_flag"].append(abs(tab_flag_error))
            local_abs["low_var"].append(abs(low_var_error))
            local_abs["tab_mean"].append(abs(tab_mean_error))
            local_abs["hist"].append(hist_error)

            release = central_dashboard_release(
                population, epsilon=epsilon, rng=rng, decisions=decisions
            )
            stats = release["statistics"]
            status_l1 = _l1(
                list(stats["status_histogram"]["noisy"]),  # type: ignore[index]
                [float(value) for value in exact["status_histogram"]],  # type: ignore[arg-type]
            )
            paste_error_central = float(stats["paste_detected_count"]["noisy"]) - float(exact["paste_detected_count"])  # type: ignore[arg-type]
            central_abs["status_l1"].append(status_l1)
            central_abs["paste"].append(abs(paste_error_central))
            central_abs["paste_rate"].append(abs(paste_error_central) / N)
            central_signed["paste"].append(paste_error_central)

        local_rows.append({
            "epsilon": epsilon,
            "paste": _mean(local_abs["paste"]),
            "tabs_flag": _mean(local_abs["tabs_flag"]),
            "low_var": _mean(local_abs["low_var"]),
            "tab_mean": _mean(local_abs["tab_mean"]),
            "hist": _mean(local_abs["hist"]),
        })
        central_rows.append({
            "epsilon": epsilon,
            "status_l1": _mean(central_abs["status_l1"]),
            "paste": _mean(central_abs["paste"]),
            "paste_rate": _mean(central_abs["paste_rate"]),
        })
        if epsilon == 1.0:
            bias_at_one = {
                "local_paste": _mean(local_signed["paste"]),
                "local_tabs_flag": _mean(local_signed["tabs_flag"]),
                "local_low_var": _mean(local_signed["low_var"]),
                "local_tab_mean": _mean(local_signed["tab_mean"]),
                "central_paste": _mean(central_signed["paste"]),
            }

    with open(os.path.join(ROOT, "data", "participants_mock.json"), encoding="utf-8") as handle:
        mock = json.load(handle)
    mock_exact = exact_cohort_statistics(mock)
    mock_l1 = []
    mock_rng = random.Random(SEED + 99)
    for _ in range(SMALL_COHORT_TRIALS):
        release = central_dashboard_release(mock, epsilon=1.0, rng=mock_rng)
        mock_l1.append(
            _l1(
                list(release["statistics"]["status_histogram"]["noisy"]),  # type: ignore[index]
                [float(value) for value in mock_exact["status_histogram"]],  # type: ignore[arg-type]
            )
        )
    mock_status_l1 = _mean(mock_l1)

    elapsed = time.perf_counter() - started
    at_one_local = next(row for row in local_rows if row["epsilon"] == 1.0)
    at_one_central = next(row for row in central_rows if row["epsilon"] == 1.0)

    local_table = _markdown_table(
        [
            "ε",
            "Paste rate MAE",
            "Excessive-tab rate MAE",
            "Low-variance rate MAE",
            "Mean tab switches MAE",
            "Keystroke histogram L1",
        ],
        [
            [
                _fmt(row["epsilon"]),
                _fmt(row["paste"]),
                _fmt(row["tabs_flag"]),
                _fmt(row["low_var"]),
                _fmt(row["tab_mean"]),
                _fmt(row["hist"]),
            ]
            for row in local_rows
        ],
    )
    central_table = _markdown_table(
        ["ε", "Status histogram L1", "Paste count MAE", "Paste rate MAE"],
        [
            [
                _fmt(row["epsilon"]),
                _fmt(row["status_l1"]),
                _fmt(row["paste"]),
                _fmt(row["paste_rate"]),
            ]
            for row in central_rows
        ],
    )
    bias_table = _markdown_table(
        ["Estimator at ε = 1", "Mean signed error"],
        [
            ["Local paste rate", _fmt(bias_at_one["local_paste"])],
            ["Local excessive-tab rate", _fmt(bias_at_one["local_tabs_flag"])],
            ["Local low-variance rate", _fmt(bias_at_one["local_low_var"])],
            ["Local mean tab switches", _fmt(bias_at_one["local_tab_mean"])],
            ["Central paste count", _fmt(bias_at_one["central_paste"])],
        ],
    )

    role_counts: dict[str, int] = {}
    for person in population:
        role_counts[str(person["role"])] = role_counts.get(str(person["role"]), 0) + 1

    document = f"""# Differential privacy evaluation

Accuracy of the aggregate releases as ε changes. This is not a classifier
accuracy. Individual fraud routing does not read the noisy values, so it stays
aligned with the non-private pipeline at every ε.

Re-run the measurement with:

```bash
python3 scripts/eval_dp_tradeoff.py
```

## Setup

- Cohort: {N} synthetic respondents, seed {SEED}.
- Mix: {role_counts.get("legit", 0)} human, {role_counts.get("bot", 0)} scripted bot, {role_counts.get("llm", 0)} LLM-assisted, {role_counts.get("borderline", 0)} borderline.
- Trials per ε: {TRIALS}. Only the privacy noise is redrawn. The cohort is fixed.
- ε grid: {", ".join(str(value) for value in EPSILONS)}. The same total is split by the default budget shares in `src/dp.py`.
- Local randomized-response error is the mean absolute error of the debiased rate against the true predicate rate.
- Local Laplace error is against the clipped contribution (paste counts are clipped to 5 and tab switches to 10 before noise). The synthetic draws sit inside those clips, so clipping bias is zero here.
- The keystroke figure is the L1 distance between the average noisy per-client histogram and the average true histogram. Empty clients would contribute the zero vector; every synthetic client types.
- Central error uses the unclamped Laplace answers, which are unbiased. The dashboard's published copy clamps negatives at zero. That clamp is post-processing: it stays ε-DP and it adds a little bias on tiny counts.
- Per-respondent routing agreement with the non-private pipeline on this cohort: **{routing_agreement:.0%}** ({routing_hits} / {N}). That figure does not move with ε.

## Local DP

Each client adds their own noise. Averaging {N} clients is what makes the estimates usable. A single export is not a meaningful reading of that person.

{local_table}

At the default local budget **ε = 1**, mean absolute error is about **{_fmt(at_one_local["paste"])}** on the paste rate, **{_fmt(at_one_local["tabs_flag"])}** on the excessive-tab rate, **{_fmt(at_one_local["low_var"])}** on the low-variance rate, **{_fmt(at_one_local["tab_mean"])}** tab switches on the mean, and **{_fmt(at_one_local["hist"])}** L1 on the cadence histogram.

The boolean rates are the local statistics you can actually use at this budget. Paste detection receives 25% of ε, so that bit is released at ε = 0.25. The true paste rate on this cohort is **{_fmt(float(truth["rates"]["paste_detected"]))}**, and the MAE above is the absolute error around it. The magnitude queries are noisier than a quick 1/n argument suggests. Tab switches are clipped at 10, so the local sensitivity is 10, and that query receives only 10% of the budget. The Laplace scale is therefore 100. Averaging independent local noise shrinks error as `1/sqrt(n)`, not `1/n`: the standard deviation of the mean is `scale * sqrt(2/n)`, about 3.2 tab switches here, and the measured MAE is {_fmt(at_one_local["tab_mean"])}. The true mean of clipped tab switches is **{_fmt(float(truth["tab_mean"]))}**, so ε = 1 does not resolve it. The histogram has the same shape of problem. L1 sensitivity 2 and a 10% budget share set the per-bin scale to 20, and the average histogram's L1 error ({_fmt(at_one_local["hist"])}) is larger than a distribution that sums to 1.

Raising the total ε moves every column down. By ε = 8 the mean tab error is about 0.32 and the histogram L1 is about 0.35, small enough to see the shape. That spend is a product choice, and the accountant is where it gets written down. It is also why the same question, asked once at the curator under central DP, is so much more accurate at ε = 1.

## Central DP

The curator holds the rows, scores them exactly, and noises each published query once. Substitution sensitivity is 1 for a boolean count and 2 for a histogram that puts each person in one bin.

{central_table}

At the default central budget **ε = 1**, the status histogram's mean L1 error is about **{_fmt(at_one_central["status_l1"])}** people out of {N} (paste-rate MAE **{_fmt(at_one_central["paste_rate"])}**). The same ε buys a much smaller error than local DP because the noise is added once, not once per client.

On the four-person mock cohort the same ε = 1 status release has mean L1 error **{_fmt(mock_status_l1)}** across {SMALL_COHORT_TRIALS} trials. That is larger than the cohort. The CLI analytics view of the mock data demonstrates the mechanism; it is not a prevalence estimate. Central DP on a handful of rows is honest noise, not a precise dashboard.

## Bias check

Mean signed error at ε = 1. A debiased randomized-response rate and an unclamped Laplace query are unbiased, so these averages should sit near zero. Thirty trials still leave scatter: the local tab-switch mean has a per-trial standard deviation near 3, and the central paste count near 9, so a signed error of a few tenths is Monte Carlo noise rather than a bias in the estimator.

{bias_table}

## How to read this in an interview

- Local DP protects the client from the collector. Utility is an average over many clients. One record is supposed to look wrong.
- Central DP protects a published aggregate from someone who does not also get the microdata or the decision log. It is the higher-utility choice when the curator must already hold the rows in order to approve or reject.
- ε = 1 is the default on both paths. The tables are the reason a product might spend more, and the accountant is where that spend is written down.
- Routing accuracy is not on these curves. Changing ε does not change who is flagged.

Runtime of this script on the machine that generated the tables: {elapsed:.1f}s.
"""
    return document


def main() -> None:
    document = evaluate()
    destination = os.path.join(ROOT, "docs", "dp-evaluation.md")
    with open(destination, "w", encoding="utf-8") as handle:
        handle.write(document)
    sys.stdout.write(document)
    sys.stdout.write(f"\nWrote {destination}\n")


if __name__ == "__main__":
    main()
