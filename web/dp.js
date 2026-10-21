/* Local differential privacy for telemetry that leaves the browser.

   Mirrors src/dp.py. Tests fail if the public constants or the budget split drift.
   The fraud score does not read this output. Raw keystroke intervals are used
   only to fill a histogram and are not copied into the release.

   Default coins come from crypto.getRandomValues. Predictable noise can be
   subtracted by a collector who knows the seed, which removes the guarantee.
*/
(function (root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) {
        module.exports = api;
    }
    if (root) {
        root.VerifiedHumanDP = api;
    }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
    "use strict";

    const CONSTANTS = {
        local_epsilon_default: 1.0,
        paste_count_clip: 5.0,
        tab_switch_clip: 10.0,
        excessive_tab_threshold: 4,
        fast_submission_seconds: 30.0,
        low_variance_ms: 5.0,
        keystroke_bin_edges_ms: [50.0, 150.0, 300.0, 600.0],
        keystroke_histogram_l1_sensitivity: 2.0,
        local_shares: [
            ["paste_detected", 25],
            ["focus_paste_coincidence", 8],
            ["excessive_tab_switches", 20],
            ["fast_submission", 7],
            ["low_cadence_variance", 15],
            ["paste_count", 5],
            ["tab_switches", 10],
            ["keystroke_histogram", 10]
        ]
    };

    const BIN_LABELS = ["[0, 50)", "[50, 150)", "[150, 300)", "[300, 600)", "[600, inf)"];
    const RR_QUERIES = CONSTANTS.local_shares
        .map(function (pair) { return pair[0]; })
        .filter(function (name) {
            return name !== "paste_count" && name !== "tab_switches" && name !== "keystroke_histogram";
        });

    function assertShareSum() {
        const sum = CONSTANTS.local_shares.reduce(function (total, pair) {
            return total + pair[1];
        }, 0);
        if (sum !== 100) {
            throw new Error("local DP shares must sum to 100");
        }
    }
    assertShareSum();

    function requireEpsilon(epsilon) {
        if (typeof epsilon !== "number" || !isFinite(epsilon) || epsilon <= 0) {
            throw new Error("epsilon must be finite and > 0");
        }
        return epsilon;
    }

    function allocateBudget(totalEpsilon, shares) {
        const total = requireEpsilon(totalEpsilon);
        const table = shares || CONSTANTS.local_shares;
        const sum = table.reduce(function (acc, pair) { return acc + pair[1]; }, 0);
        if (sum !== 100) {
            throw new Error("shares must sum to 100");
        }
        const allocated = {};
        let consumed = 0;
        for (let i = 0; i < table.length - 1; i++) {
            const portion = total * table[i][1] / 100;
            allocated[table[i][0]] = portion;
            consumed += portion;
        }
        const last = table[table.length - 1];
        allocated[last[0]] = total - consumed;
        return allocated;
    }

    function defaultRng() {
        const buffer = new Uint32Array(1);
        const webCrypto = (typeof crypto !== "undefined" && crypto.getRandomValues)
            ? crypto
            : null;
        if (!webCrypto) {
            throw new Error("crypto.getRandomValues is required for DP noise");
        }
        return function () {
            webCrypto.getRandomValues(buffer);
            return buffer[0] / 4294967296;
        };
    }

    function rrProbabilities(epsilon) {
        requireEpsilon(epsilon);
        // p = 1 / (1 + e^{-ε}) matches src/dp.py and stays finite for large ε.
        if (epsilon >= 700) {
            return { p: 1, q: 0 };
        }
        const expNeg = Math.exp(-epsilon);
        return {
            p: 1 / (1 + expNeg),
            q: expNeg / (1 + expNeg)
        };
    }

    function randomizedResponse(bit, epsilon, rng) {
        const probs = rrProbabilities(epsilon);
        const value = bit ? 1 : 0;
        if (rng() < probs.p) {
            return value;
        }
        return 1 - value;
    }

    function debiasRrMean(reports, epsilon) {
        if (!reports.length) {
            throw new Error("randomized-response debiasing needs at least one report");
        }
        const probs = rrProbabilities(epsilon);
        const gap = probs.p - probs.q;
        let total = 0;
        for (let i = 0; i < reports.length; i++) {
            if (reports[i] !== 0 && reports[i] !== 1) {
                throw new Error("randomized response must be 0 or 1");
            }
            total += (reports[i] - probs.q) / gap;
        }
        return total / reports.length;
    }

    function laplaceScale(sensitivity, epsilon) {
        requireEpsilon(epsilon);
        if (!isFinite(sensitivity) || sensitivity < 0) {
            throw new Error("sensitivity must be finite and >= 0");
        }
        if (sensitivity === 0) {
            return 0;
        }
        return sensitivity / epsilon;
    }

    function sampleLaplace(scale, rng) {
        if (!isFinite(scale) || scale < 0) {
            throw new Error("Laplace scale must be finite and >= 0");
        }
        if (scale === 0) {
            return 0;
        }
        let probability = 0;
        do {
            probability = rng();
        } while (!(probability > 0 && probability < 1));
        if (probability < 0.5) {
            return scale * Math.log(2 * probability);
        }
        return -scale * Math.log(2 * (1 - probability));
    }

    function clip(value, low, high) {
        if (value < low) return low;
        if (value > high) return high;
        return value;
    }

    function finite(value, label) {
        if (typeof value !== "number" || !isFinite(value)) {
            throw new Error(label + " must be a finite number");
        }
        return value;
    }

    function asBool(value, label) {
        if (typeof value === "boolean") return value;
        if (value === 0 || value === 1) return Boolean(value);
        throw new Error(label + " must be a boolean");
    }

    function populationVariance(values) {
        if (!values.length) return 0;
        let mean = 0;
        for (let i = 0; i < values.length; i++) mean += values[i];
        mean /= values.length;
        let sum = 0;
        for (let i = 0; i < values.length; i++) {
            const delta = values[i] - mean;
            sum += delta * delta;
        }
        return sum / values.length;
    }

    function keystrokeBinIndex(intervalMs) {
        if (!isFinite(intervalMs) || intervalMs < 0) {
            throw new Error("keystroke interval must be finite and >= 0");
        }
        const edges = CONSTANTS.keystroke_bin_edges_ms;
        for (let i = 0; i < edges.length; i++) {
            if (intervalMs < edges[i]) return i;
        }
        return edges.length;
    }

    function keystrokeProportionHistogram(intervals) {
        const bins = [0, 0, 0, 0, 0];
        for (let i = 0; i < intervals.length; i++) {
            bins[keystrokeBinIndex(intervals[i])] += 1;
        }
        const total = bins.reduce(function (sum, count) { return sum + count; }, 0);
        if (total === 0) return bins.map(function () { return 0; });
        return bins.map(function (count) { return count / total; });
    }

    function localView(telemetry) {
        const pasteDetected = asBool(telemetry.paste_detected || false, "paste_detected");
        const pasteCount = telemetry.paste_count == null
            ? (pasteDetected ? 1 : 0)
            : finite(telemetry.paste_count, "paste_count");
        const focus = asBool(telemetry.focus_paste_coincidence || false, "focus_paste_coincidence");
        const tabs = telemetry.tab_switches != null
            ? finite(telemetry.tab_switches, "tab_switches")
            : finite(telemetry.tab_switches_during_form || 0, "tab_switches");
        const rawIntervals = telemetry.keystroke_intervals_ms || [];
        if (!Array.isArray(rawIntervals)) {
            throw new Error("keystroke_intervals_ms must be a list");
        }
        const intervals = rawIntervals.map(function (value) {
            return finite(value, "keystroke interval");
        });
        let variance = null;
        if (telemetry.typing_cadence_variance_ms != null) {
            variance = finite(telemetry.typing_cadence_variance_ms, "typing_cadence_variance_ms");
        } else if (intervals.length >= 2) {
            variance = populationVariance(intervals);
        }
        const timeTaken = telemetry.time_taken_seconds != null
            ? telemetry.time_taken_seconds
            : telemetry.time;
        const fast = timeTaken == null
            ? false
            : finite(timeTaken, "time_taken_seconds") < CONSTANTS.fast_submission_seconds;
        return {
            paste_detected: pasteDetected,
            paste_count: clip(pasteCount, 0, CONSTANTS.paste_count_clip),
            focus_paste_coincidence: focus,
            tab_switches: clip(tabs, 0, CONSTANTS.tab_switch_clip),
            excessive_tab_switches: tabs > CONSTANTS.excessive_tab_threshold,
            fast_submission: fast,
            low_cadence_variance: variance == null ? false : variance < CONSTANTS.low_variance_ms,
            histogram: keystrokeProportionHistogram(intervals)
        };
    }

    function localRelease(telemetry, options) {
        const settings = options || {};
        const epsilon = settings.epsilon == null ? CONSTANTS.local_epsilon_default : settings.epsilon;
        requireEpsilon(epsilon);
        const rng = settings.rng || defaultRng();
        const budget = allocateBudget(epsilon, CONSTANTS.local_shares);
        const view = localView(telemetry);
        const entries = [];
        let spent = 0;
        function spend(name, queryEpsilon, mechanism, sensitivity, note) {
            if (spent + queryEpsilon > epsilon + 1e-9) {
                throw new Error("privacy budget exceeded on " + name);
            }
            spent += queryEpsilon;
            entries.push({
                name: name,
                epsilon: queryEpsilon,
                mechanism: mechanism,
                sensitivity: sensitivity,
                note: note
            });
        }

        const values = {};
        const rrParameters = {};
        RR_QUERIES.forEach(function (name) {
            const queryEpsilon = budget[name];
            const probs = rrProbabilities(queryEpsilon);
            spend(name, queryEpsilon, "randomized_response", 1, "binary predicate; truth probability e^ε/(e^ε+1)");
            values[name] = randomizedResponse(view[name], queryEpsilon, rng);
            rrParameters[name] = {
                epsilon: queryEpsilon,
                p_truth: probs.p,
                p_flip: probs.q
            };
        });

        const laplaceParameters = {};
        [
            ["paste_count", CONSTANTS.paste_count_clip],
            ["tab_switches", CONSTANTS.tab_switch_clip]
        ].forEach(function (spec) {
            const name = spec[0];
            const sensitivity = spec[1];
            const queryEpsilon = budget[name];
            const scale = laplaceScale(sensitivity, queryEpsilon);
            spend(name, queryEpsilon, "laplace", sensitivity, "clipped contribution");
            values[name] = view[name] + sampleLaplace(scale, rng);
            laplaceParameters[name] = {
                epsilon: queryEpsilon,
                sensitivity: sensitivity,
                scale: scale,
                clip: [0, sensitivity]
            };
        });

        const histEpsilon = budget.keystroke_histogram;
        const histSensitivity = CONSTANTS.keystroke_histogram_l1_sensitivity;
        const histScale = laplaceScale(histSensitivity, histEpsilon);
        spend(
            "keystroke_histogram",
            histEpsilon,
            "laplace",
            histSensitivity,
            "vector Laplace on the per-client distribution; one charge for all bins"
        );
        values.keystroke_histogram = view.histogram.map(function (count) {
            return count + sampleLaplace(histScale, rng);
        });
        laplaceParameters.keystroke_histogram = {
            epsilon: histEpsilon,
            sensitivity_l1: histSensitivity,
            scale: histScale,
            bin_edges_ms: CONSTANTS.keystroke_bin_edges_ms.slice(),
            bin_labels: BIN_LABELS.slice(),
            estimand: "mean of per-client keystroke-gap distributions; a client with no gaps contributes the zero vector"
        };

        return {
            privacy_model: "local",
            differentially_private: true,
            definition: "pure epsilon local differential privacy, basic composition",
            neighboring_relation: "any two telemetry records from one client",
            epsilon: epsilon,
            raw_keystrokes_included: false,
            individual_decision_included: false,
            values: values,
            public_parameters: {
                rr_probabilities: rrParameters,
                laplace: laplaceParameters,
                thresholds: {
                    excessive_tab_switches: "> " + CONSTANTS.excessive_tab_threshold,
                    fast_submission_seconds: "< " + CONSTANTS.fast_submission_seconds,
                    low_cadence_variance_ms: "< " + CONSTANTS.low_variance_ms
                }
            },
            accountant: {
                composition: "basic",
                total_epsilon: epsilon,
                spent_epsilon: spent,
                remaining_epsilon: epsilon - spent,
                entries: entries
            }
        };
    }

    function formatNumber(value) {
        const rounded = Math.round(value * 100) / 100;
        return (Object.is(rounded, -0) ? 0 : rounded).toFixed(2);
    }

    function summarizeRelease(release) {
        const histogram = release.values.keystroke_histogram;
        const labels = release.public_parameters.laplace.keystroke_histogram.bin_labels;
        const rows = [
            { label: "Paste bit (randomized response)", value: String(release.values.paste_detected) },
            { label: "Paste count (Laplace)", value: formatNumber(release.values.paste_count) },
            { label: "Focus-paste bit (randomized response)", value: String(release.values.focus_paste_coincidence) },
            { label: "Tab switches (Laplace)", value: formatNumber(release.values.tab_switches) },
            { label: "Excessive tabs bit (randomized response)", value: String(release.values.excessive_tab_switches) },
            { label: "Fast submission bit (randomized response)", value: String(release.values.fast_submission) },
            { label: "Low cadence-variance bit (randomized response)", value: String(release.values.low_cadence_variance) }
        ];
        labels.forEach(function (label, index) {
            rows.push({
                label: "Keystroke gaps " + label,
                value: formatNumber(histogram[index])
            });
        });
        return {
            headline: "Local DP export, ε=" + formatNumber(release.epsilon) + " (basic composition)",
            decision_note: "The risk score is an exact decision about this respondent and is not differentially private.",
            export_note: "These values are the record that would leave the device for aggregate analytics. One person's noisy record is not their true behavior. Raw keystroke intervals are not included.",
            rows: rows
        };
    }

    return {
        CONSTANTS: CONSTANTS,
        BIN_LABELS: BIN_LABELS,
        allocateBudget: allocateBudget,
        rrProbabilities: rrProbabilities,
        randomizedResponse: randomizedResponse,
        debiasRrMean: debiasRrMean,
        laplaceScale: laplaceScale,
        sampleLaplace: sampleLaplace,
        keystrokeProportionHistogram: keystrokeProportionHistogram,
        localRelease: localRelease,
        summarizeRelease: summarizeRelease
    };
});
