/* Local differential privacy for telemetry that leaves the browser.

   Mirrors src/dp.py. Tests fail if the public constants or the budget split drift.
   The fraud score does not read this output. Raw keystroke intervals are used
   only to sample one cadence bin and are not copied into the release.

   Integer counts use discrete Laplace (a difference of two geometric draws).
   Adding continuous Laplace noise, especially from one 32-bit uniform, can
   leak an integer query because the gaps between representable floats depend
   on the secret (Mironov, 2012). This file does not sample continuous Laplace.
   The geometric inverse CDF uses a uniform in (0, 1) and returns an integer.
   The secret is added with integer arithmetic. There is no hard cap on the
   integer. The production coin uses 53 bits from crypto.getRandomValues, not
   one uint32, so the geometric tail is not chopped at 2^32.

   The device ledger memoizes the whole report for a UTC day (permanent
   randomized response). A later export that day replays it and spends nothing.
   Averaging repeats therefore does not remove the noise. The daily cap is a
   transmission limit. The lifetime cap composes days by basic composition.
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
        daily_export_cap: 2,
        lifetime_epsilon_cap: 8.0,
        paste_count_clip: 5,
        tab_switch_clip: 4,
        excessive_tab_threshold: 4,
        fast_submission_seconds: 30.0,
        low_variance_ms: 5.0,
        keystroke_bin_edges_ms: [80.0, 250.0],
        keystroke_bin_labels: ["[0, 80)", "[80, 250)", "[250, inf)", "unknown"],
        local_shares: [
            ["paste_detected", 22],
            ["focus_paste_coincidence", 4],
            ["excessive_tab_switches", 8],
            ["fast_submission", 4],
            ["low_cadence_variance", 12],
            ["paste_count", 8],
            ["tab_switches", 22],
            ["keystroke_histogram", 20]
        ]
    };

    const BIN_LABELS = CONSTANTS.keystroke_bin_labels;
    const STORAGE_PREFIX = "verified-human-dp-ledger:";
    const RR_QUERIES = [
        "paste_detected",
        "focus_paste_coincidence",
        "excessive_tab_switches",
        "fast_submission",
        "low_cadence_variance"
    ];

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
        const buffer = new Uint32Array(2);
        const webCrypto = (typeof crypto !== "undefined" && crypto.getRandomValues)
            ? crypto
            : null;
        if (!webCrypto) {
            throw new Error("crypto.getRandomValues is required for DP noise");
        }
        return function () {
            webCrypto.getRandomValues(buffer);
            // 53-bit uniform in [0, 1). One uint32 would cap a geometric tail.
            const hi = buffer[0] >>> 5;
            const lo = buffer[1] >>> 6;
            return (hi * 67108864 + lo) / 9007199254740992;
        };
    }

    function namedError(name, message) {
        const error = new Error(message);
        error.name = name;
        return error;
    }

    function rrProbabilities(epsilon) {
        requireEpsilon(epsilon);
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

    function geometricFailures(successProbability, rng) {
        if (!(successProbability > 0 && successProbability <= 1)) {
            throw new Error("success probability must be in (0, 1]");
        }
        if (successProbability >= 1) {
            return 0;
        }
        let uniform = 0;
        do {
            uniform = rng();
        } while (!(uniform > 0));
        const failures = Math.floor(Math.log(uniform) / Math.log1p(-successProbability));
        return failures < 0 ? 0 : failures;
    }

    function sampleDiscreteLaplace(epsilon, sensitivity, rng) {
        requireEpsilon(epsilon);
        if ((sensitivity | 0) !== sensitivity || sensitivity < 0) {
            throw new Error("sensitivity must be a non-negative integer");
        }
        if (sensitivity === 0) {
            return 0;
        }
        const success = -Math.expm1(-epsilon / sensitivity);
        if (success >= 1) {
            return 0;
        }
        if (!(success > 0)) {
            throw new Error("discrete Laplace success probability collapsed");
        }
        return geometricFailures(success, rng) - geometricFailures(success, rng);
    }

    function discreteLaplaceMechanism(value, sensitivity, epsilon, rng) {
        if ((value | 0) !== value) {
            throw new Error("discrete Laplace query must be an integer");
        }
        return value + sampleDiscreteLaplace(epsilon, sensitivity, rng);
    }

    function oueProbabilities(epsilon) {
        requireEpsilon(epsilon);
        if (epsilon >= 700) {
            return { p: 0.5, q: 0 };
        }
        return { p: 0.5, q: 1 / (Math.exp(epsilon) + 1) };
    }

    function oueEncode(index, domain, epsilon, rng) {
        if (domain < 1 || index < 0 || index >= domain) {
            throw new Error("OUE index is outside the domain");
        }
        const probs = oueProbabilities(epsilon);
        const encoded = [];
        for (let position = 0; position < domain; position++) {
            if (position === index) {
                encoded.push(rng() < probs.p ? 1 : 0);
            } else {
                encoded.push(rng() < probs.q ? 1 : 0);
            }
        }
        return encoded;
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

    function present(telemetry, key) {
        return telemetry[key] != null;
    }

    function asBool(value, label) {
        if (typeof value === "boolean") return value;
        if (value === 0 || value === 1) return Boolean(value);
        throw new Error(label + " must be a boolean");
    }

    function populationVariance(values) {
        const count = values.length;
        let mean = 0;
        for (let i = 0; i < count; i++) mean += values[i];
        mean /= count;
        let sum = 0;
        for (let i = 0; i < count; i++) {
            const delta = values[i] - mean;
            sum += delta * delta;
        }
        return sum / count;
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

    function sampleKeystrokeItem(intervals, rng) {
        if (!intervals.length) {
            return CONSTANTS.keystroke_bin_edges_ms.length;
        }
        const choice = intervals[Math.floor(rng() * intervals.length)];
        return keystrokeBinIndex(choice);
    }

    function localView(telemetry) {
        const pasteDetected = present(telemetry, "paste_detected")
            ? asBool(telemetry.paste_detected, "paste_detected")
            : false;
        const pasteCount = present(telemetry, "paste_count")
            ? finite(telemetry.paste_count, "paste_count")
            : (pasteDetected ? 1 : 0);
        const focus = present(telemetry, "focus_paste_coincidence")
            ? asBool(telemetry.focus_paste_coincidence, "focus_paste_coincidence")
            : false;
        let tabSwitches = null;
        if (present(telemetry, "tab_switches")) {
            tabSwitches = finite(telemetry.tab_switches, "tab_switches");
        } else if (present(telemetry, "tab_switches_during_form")) {
            tabSwitches = finite(telemetry.tab_switches_during_form, "tab_switches");
        }
        const rawIntervals = telemetry.keystroke_intervals_ms == null
            ? []
            : telemetry.keystroke_intervals_ms;
        if (!Array.isArray(rawIntervals)) {
            throw new Error("keystroke_intervals_ms must be a list");
        }
        const intervals = rawIntervals.map(function (value) {
            return finite(value, "keystroke interval");
        });
        let variance = null;
        if (present(telemetry, "typing_cadence_variance_ms")) {
            variance = finite(telemetry.typing_cadence_variance_ms, "typing_cadence_variance_ms");
        } else if (intervals.length >= 2) {
            variance = populationVariance(intervals);
        }
        let fast = false;
        if (present(telemetry, "time_taken_seconds")) {
            fast = finite(telemetry.time_taken_seconds, "time_taken_seconds") < CONSTANTS.fast_submission_seconds;
        } else if (present(telemetry, "time")) {
            fast = finite(telemetry.time, "time_taken_seconds") < CONSTANTS.fast_submission_seconds;
        }
        return {
            paste_detected: pasteDetected,
            paste_count: Math.round(clip(pasteCount, 0, CONSTANTS.paste_count_clip)),
            focus_paste_coincidence: focus,
            tab_switches: tabSwitches == null
                ? 0
                : Math.round(clip(tabSwitches, 0, CONSTANTS.tab_switch_clip)),
            excessive_tab_switches: tabSwitches == null
                ? false
                : tabSwitches > CONSTANTS.excessive_tab_threshold,
            fast_submission: fast,
            low_cadence_variance: variance == null ? false : variance < CONSTANTS.low_variance_ms,
            intervals: intervals
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
                throw namedError("PrivacyBudgetExceeded", "privacy budget exceeded on " + name);
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
            spend(name, queryEpsilon, "randomized_response", 1, "permanent randomized response; replay does not redraw");
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
            spend(name, queryEpsilon, "discrete_laplace", sensitivity, "integer geometric mechanism");
            values[name] = discreteLaplaceMechanism(view[name], sensitivity, queryEpsilon, rng);
            laplaceParameters[name] = {
                epsilon: queryEpsilon,
                sensitivity: sensitivity,
                clip: [0, sensitivity],
                distribution: "discrete_laplace"
            };
        });

        const histEpsilon = budget.keystroke_histogram;
        const item = sampleKeystrokeItem(view.intervals, rng);
        spend(
            "keystroke_histogram",
            histEpsilon,
            "oue",
            1,
            "one sampled cadence bin; optimized unary encoding"
        );
        values.keystroke_histogram = oueEncode(item, BIN_LABELS.length, histEpsilon, rng);
        const oue = oueProbabilities(histEpsilon);

        return {
            privacy_model: "local",
            differentially_private: true,
            definition: "pure epsilon local DP, basic composition, one draw",
            neighboring_relation: "any two telemetry records from one client",
            epsilon: epsilon,
            memoized: false,
            raw_keystrokes_included: false,
            individual_decision_included: false,
            values: values,
            public_parameters: {
                rr_probabilities: rrParameters,
                discrete_laplace: laplaceParameters,
                keystroke_histogram: {
                    mechanism: "oue",
                    epsilon: histEpsilon,
                    p_keep_one: oue.p,
                    q_flip_zero: oue.q,
                    bin_labels: BIN_LABELS.slice(),
                    estimand: "mean of per-client cadence distributions, one uniformly sampled gap; no gaps is the unknown bin"
                },
                thresholds: {
                    excessive_tab_switches: "> " + CONSTANTS.excessive_tab_threshold,
                    fast_submission_seconds: "< " + CONSTANTS.fast_submission_seconds,
                    low_cadence_variance_ms: "< " + CONSTANTS.low_variance_ms,
                    missing: "unknown predicates are false and are not treated as suspicious"
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

    function memoryStorage() {
        const data = {};
        return {
            get: function (key) {
                return Object.prototype.hasOwnProperty.call(data, key) ? data[key] : null;
            },
            set: function (key, value) {
                data[key] = String(value);
            }
        };
    }

    function browserStorage() {
        if (typeof localStorage === "undefined") {
            return memoryStorage();
        }
        return {
            get: function (key) { return localStorage.getItem(key); },
            set: function (key, value) { localStorage.setItem(key, value); }
        };
    }

    function utcDay(date) {
        const value = date || new Date();
        return value.toISOString().slice(0, 10);
    }

    function exportForDevice(telemetry, options) {
        const settings = options || {};
        const deviceId = settings.deviceId || "browser";
        const today = settings.today || utcDay();
        const epsilon = settings.epsilon == null ? CONSTANTS.local_epsilon_default : settings.epsilon;
        requireEpsilon(epsilon);
        const storage = settings.storage || browserStorage();
        const key = STORAGE_PREFIX + deviceId;
        const raw = storage.get(key);
        const state = raw ? JSON.parse(raw) : { lifetime_epsilon_spent: 0, days: {} };
        const days = state.days;
        if (days[today]) {
            const day = days[today];
            if (day.transmissions >= CONSTANTS.daily_export_cap) {
                throw namedError(
                    "ExportCapExceeded",
                    "device already transmitted the " + today + " report " + CONSTANTS.daily_export_cap + " times"
                );
            }
            day.transmissions += 1;
            storage.set(key, JSON.stringify(state));
            const replayed = JSON.parse(JSON.stringify(day.report));
            replayed.memoized = true;
            replayed.transmission = day.transmissions;
            replayed.privacy_spend_this_call = 0;
            return replayed;
        }
        if (state.lifetime_epsilon_spent + epsilon > CONSTANTS.lifetime_epsilon_cap + 1e-9) {
            throw namedError(
                "PrivacyBudgetExceeded",
                "lifetime epsilon cap would be exceeded; this day was not created"
            );
        }
        const report = localRelease(telemetry, { epsilon: epsilon, rng: settings.rng });
        report.memoized = true;
        report.transmission = 1;
        report.privacy_spend_this_call = epsilon;
        report.memoization = "permanent randomized response for this UTC day; later changes to the telemetry do not redraw the answers";
        state.lifetime_epsilon_spent += epsilon;
        days[today] = {
            epsilon: epsilon,
            transmissions: 1,
            report: report
        };
        storage.set(key, JSON.stringify(state));
        return JSON.parse(JSON.stringify(report));
    }

    function formatNumber(value) {
        const rounded = Math.round(value * 100) / 100;
        return (Object.is(rounded, -0) ? 0 : rounded).toFixed(2);
    }

    function summarizeRelease(release) {
        const histogram = release.values.keystroke_histogram;
        const labels = release.public_parameters.keystroke_histogram.bin_labels;
        const rows = [
            { label: "Paste bit (randomized response)", value: String(release.values.paste_detected) },
            { label: "Paste count (discrete Laplace)", value: String(release.values.paste_count) },
            { label: "Focus-paste bit (randomized response)", value: String(release.values.focus_paste_coincidence) },
            { label: "Tab switches (discrete Laplace)", value: String(release.values.tab_switches) },
            { label: "Excessive tabs bit (randomized response)", value: String(release.values.excessive_tab_switches) },
            { label: "Fast submission bit (randomized response)", value: String(release.values.fast_submission) },
            { label: "Low cadence-variance bit (randomized response)", value: String(release.values.low_cadence_variance) }
        ];
        labels.forEach(function (label, index) {
            rows.push({
                label: "Keystroke OUE bit " + label,
                value: String(histogram[index])
            });
        });
        let memo = " This draw has not been stored on a device ledger yet.";
        if (release.memoized && release.privacy_spend_this_call > 0) {
            memo = " Stored for this UTC day. This export spent ε " + formatNumber(release.privacy_spend_this_call) + ". A later export today resends these answers and spends ε 0.";
        } else if (release.memoized) {
            memo = " Memoized for this UTC day. This repeat sends the same answers and spends ε 0.";
        }
        return {
            headline: "Local DP export, ε=" + formatNumber(release.epsilon) + " (basic composition)",
            decision_note: "The risk score is an exact decision about this respondent and is not differentially private.",
            export_note: "These values are the record that would leave the device for aggregate analytics. One person's noisy record is not their true behavior. Raw keystroke intervals are not included." + memo,
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
        sampleDiscreteLaplace: sampleDiscreteLaplace,
        discreteLaplaceMechanism: discreteLaplaceMechanism,
        oueProbabilities: oueProbabilities,
        oueEncode: oueEncode,
        localRelease: localRelease,
        exportForDevice: exportForDevice,
        memoryStorage: memoryStorage,
        summarizeRelease: summarizeRelease
    };
});
