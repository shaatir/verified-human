# Differential privacy evaluation

Accuracy of the aggregate releases as ε changes. This is not a classifier
accuracy. Individual fraud routing does not read the noisy values, so it stays
aligned with the non-private pipeline at every ε.

Re-run the measurement with:

```bash
python3 scripts/eval_dp_tradeoff.py
```

## Setup

- Cohort: 2000 synthetic respondents, seed 20261021.
- Mix: 1200 human, 300 scripted bot, 300 LLM-assisted, 200 borderline.
- Trials per ε: 30. Only the privacy noise is redrawn. The cohort is fixed.
- ε grid: 0.25, 0.5, 1.0, 2.0, 4.0, 8.0. The same total is split by the default budget shares in `src/dp.py`.
- Local randomized-response error is the mean absolute error of the debiased rate against the true predicate rate.
- Local Laplace error is against the clipped contribution (paste counts are clipped to 5 and tab switches to 10 before noise). The synthetic draws sit inside those clips, so clipping bias is zero here.
- The keystroke figure is the L1 distance between the average noisy per-client histogram and the average true histogram. Empty clients would contribute the zero vector; every synthetic client types.
- Central error uses the unclamped Laplace answers, which are unbiased. The dashboard's published copy clamps negatives at zero. That clamp is post-processing: it stays ε-DP and it adds a little bias on tiny counts.
- Per-respondent routing agreement with the non-private pipeline on this cohort: **100%** (2000 / 2000). That figure does not move with ε.

## Local DP

Each client adds their own noise. Averaging 2000 clients is what makes the estimates usable. A single export is not a meaningful reading of that person.

| ε | Paste rate MAE | Excessive-tab rate MAE | Low-variance rate MAE | Mean tab switches MAE | Keystroke histogram L1 |
| --- | --- | --- | --- | --- | --- |
| 0.2500 | 0.2726 | 0.3127 | 0.5018 | 11.1368 | 10.1749 |
| 0.5000 | 0.1839 | 0.1988 | 0.1857 | 5.6581 | 5.0351 |
| 1.0000 | 0.0768 | 0.0730 | 0.1140 | 2.4943 | 2.6800 |
| 2.0000 | 0.0365 | 0.0463 | 0.0600 | 1.1509 | 1.2636 |
| 4.0000 | 0.0177 | 0.0247 | 0.0292 | 0.6956 | 0.6002 |
| 8.0000 | 0.0075 | 0.0112 | 0.0174 | 0.3183 | 0.3466 |

At the default local budget **ε = 1**, mean absolute error is about **0.0768** on the paste rate, **0.0730** on the excessive-tab rate, **0.1140** on the low-variance rate, **2.4943** tab switches on the mean, and **2.6800** L1 on the cadence histogram.

The boolean rates are the local statistics you can actually use at this budget. Paste detection receives 25% of ε, so that bit is released at ε = 0.25. The true paste rate on this cohort is **0.3000**, and the MAE above is the absolute error around it. The magnitude queries are noisier than a quick 1/n argument suggests. Tab switches are clipped at 10, so the local sensitivity is 10, and that query receives only 10% of the budget. The Laplace scale is therefore 100. Averaging independent local noise shrinks error as `1/sqrt(n)`, not `1/n`: the standard deviation of the mean is `scale * sqrt(2/n)`, about 3.2 tab switches here, and the measured MAE is 2.4943. The true mean of clipped tab switches is **2.2275**, so ε = 1 does not resolve it. The histogram has the same shape of problem. L1 sensitivity 2 and a 10% budget share set the per-bin scale to 20, and the average histogram's L1 error (2.6800) is larger than a distribution that sums to 1.

Raising the total ε moves every column down. By ε = 8 the mean tab error is about 0.32 and the histogram L1 is about 0.35, small enough to see the shape. That spend is a product choice, and the accountant is where it gets written down. It is also why the same question, asked once at the curator under central DP, is so much more accurate at ε = 1.

## Central DP

The curator holds the rows, scores them exactly, and noises each published query once. Substitution sensitivity is 1 for a boolean count and 2 for a histogram that puts each person in one bin.

| ε | Status histogram L1 | Paste count MAE | Paste rate MAE |
| --- | --- | --- | --- |
| 0.2500 | 81.6432 | 20.6592 | 0.0103 |
| 0.5000 | 33.9379 | 19.9720 | 0.0100 |
| 1.0000 | 19.9584 | 7.9446 | 0.0040 |
| 2.0000 | 9.8245 | 3.4413 | 0.0017 |
| 4.0000 | 5.0469 | 1.7067 | 0.0009 |
| 8.0000 | 2.4282 | 0.7887 | 0.0004 |

At the default central budget **ε = 1**, the status histogram's mean L1 error is about **19.9584** people out of 2000 (paste-rate MAE **0.0040**). The same ε buys a much smaller error than local DP because the noise is added once, not once per client.

On the four-person mock cohort the same ε = 1 status release has mean L1 error **19.5097** across 200 trials. That is larger than the cohort. The CLI analytics view of the mock data demonstrates the mechanism; it is not a prevalence estimate. Central DP on a handful of rows is honest noise, not a precise dashboard.

## Bias check

Mean signed error at ε = 1. A debiased randomized-response rate and an unclamped Laplace query are unbiased, so these averages should sit near zero. Thirty trials still leave scatter: the local tab-switch mean has a per-trial standard deviation near 3, and the central paste count near 9, so a signed error of a few tenths is Monte Carlo noise rather than a bias in the estimator.

| Estimator at ε = 1 | Mean signed error |
| --- | --- |
| Local paste rate | 0.0185 |
| Local excessive-tab rate | 0.0114 |
| Local low-variance rate | -0.0100 |
| Local mean tab switches | -0.7146 |
| Central paste count | -0.6325 |

## How to read this in an interview

- Local DP protects the client from the collector. Utility is an average over many clients. One record is supposed to look wrong.
- Central DP protects a published aggregate from someone who does not also get the microdata or the decision log. It is the higher-utility choice when the curator must already hold the rows in order to approve or reject.
- ε = 1 is the default on both paths. The tables are the reason a product might spend more, and the accountant is where that spend is written down.
- Routing accuracy is not on these curves. Changing ε does not change who is flagged.

Runtime of this script on the machine that generated the tables: 14.0s.
