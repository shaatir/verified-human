/* Statistical checks for the browser local-DP module. Run with: node tests/dp_client.test.js */
"use strict";

const assert = require("assert");
const dp = require("../web/dp.js");

function mulberry32(seed) {
    let state = seed >>> 0;
    return function () {
        state = (state + 0x6D2B79F5) >>> 0;
        let mixed = Math.imul(state ^ (state >>> 15), 1 | state);
        mixed = (mixed + Math.imul(mixed ^ (mixed >>> 7), 61 | mixed)) ^ mixed;
        return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296;
    };
}

function assertClose(actual, expected, tolerance, label) {
    assert.ok(
        Math.abs(actual - expected) <= tolerance,
        label + ": expected " + expected + " ± " + tolerance + ", got " + actual
    );
}

const shareSum = dp.CONSTANTS.local_shares.reduce(function (sum, pair) { return sum + pair[1]; }, 0);
assert.strictEqual(shareSum, 100);
assert.strictEqual(dp.CONSTANTS.tab_switch_clip, 4);
assert.strictEqual(dp.CONSTANTS.daily_export_cap, 2);
assert.strictEqual(dp.CONSTANTS.lifetime_epsilon_cap, 8);
assert.deepStrictEqual(dp.BIN_LABELS, ["[0, 80)", "[80, 250)", "[250, inf)", "unknown"]);
assert.strictEqual(typeof dp.sampleLaplace, "undefined");

[0.2, 1, 4].forEach(function (epsilon) {
    const probs = dp.rrProbabilities(epsilon);
    assertClose(probs.p + probs.q, 1, 1e-12, "rr probabilities sum");
    assertClose(probs.p / probs.q, Math.exp(epsilon), 1e-9, "rr likelihood ratio");
    const oue = dp.oueProbabilities(epsilon);
    const ratio = Math.log((oue.p * (1 - oue.q)) / ((1 - oue.p) * oue.q));
    assertClose(ratio, epsilon, 1e-9, "oue privacy ratio");
});

[0.5, 1, 4].forEach(function (epsilon) {
    const allocated = dp.allocateBudget(epsilon);
    const total = Object.keys(allocated).reduce(function (sum, key) { return sum + allocated[key]; }, 0);
    assertClose(total, epsilon, 1e-12, "budget sums to epsilon");
});

const rng = mulberry32(20261021);
const draws = [];
for (let i = 0; i < 20000; i++) draws.push(dp.sampleDiscreteLaplace(1, 1, rng));
const mean = draws.reduce(function (sum, value) { return sum + value; }, 0) / draws.length;
const variance = draws.reduce(function (sum, value) {
    const delta = value - mean;
    return sum + delta * delta;
}, 0) / draws.length;
const success = -Math.expm1(-1);
const expectedVariance = 2 * (1 - success) / (success * success);
assertClose(mean, 0, 0.08, "discrete laplace mean");
assertClose(variance, expectedVariance, 0.35, "discrete laplace variance");

const rate = 0.35;
const epsilon = 4;
const probs = dp.rrProbabilities(epsilon);
const rrRng = mulberry32(99);
const reports = [];
const n = 8000;
for (let i = 0; i < n; i++) {
    const bit = rrRng() < rate ? 1 : 0;
    reports.push(rrRng() < probs.p ? bit : 1 - bit);
}
assertClose(dp.debiasRrMean(reports, epsilon), rate, 0.06, "debiased randomized response");

const missing = dp.localRelease({
    paste_detected: false,
    keystroke_intervals_ms: []
}, { epsilon: 1, rng: mulberry32(2) });
assert.strictEqual(missing.values.fast_submission === 0 || missing.values.fast_submission === 1, true);
assert.strictEqual(missing.public_parameters.thresholds.missing.indexOf("unknown") >= 0, true);

const calls = { n: 0 };
function countingRng() {
    calls.n += 1;
    return mulberry32(4)();
}
const storage = dp.memoryStorage();
const telemetry = {
    paste_detected: true,
    paste_count: 9999,
    focus_paste_coincidence: true,
    tab_switches: 9999,
    time_taken_seconds: 12,
    typing_cadence_variance_ms: 1.25,
    keystroke_intervals_ms: [12.5, 90, 400]
};
const first = dp.exportForDevice(telemetry, {
    deviceId: "browser-a",
    today: "2026-10-21",
    storage: storage,
    rng: countingRng
});
const used = calls.n;
const second = dp.exportForDevice({
    paste_detected: false,
    tab_switches: null,
    time_taken_seconds: null,
    typing_cadence_variance_ms: null
}, {
    deviceId: "browser-a",
    today: "2026-10-21",
    storage: storage,
    rng: countingRng
});
assert.strictEqual(calls.n, used);
assert.deepStrictEqual(first.values, second.values);
assert.strictEqual(second.privacy_spend_this_call, 0);
assert.strictEqual(second.transmission, 2);
assert.throws(function () {
    dp.exportForDevice(telemetry, {
        deviceId: "browser-a",
        today: "2026-10-21",
        storage: storage,
        rng: countingRng
    });
}, function (error) { return error.name === "ExportCapExceeded"; });

const quiet = dp.localRelease({
    paste_detected: true,
    paste_count: 9999,
    tab_switches: 9999,
    time_taken_seconds: 100,
    typing_cadence_variance_ms: 40,
    keystroke_intervals_ms: [12.5, 90, 400]
}, { epsilon: 1e6, rng: mulberry32(5) });
assert.strictEqual(quiet.values.paste_count, dp.CONSTANTS.paste_count_clip);
assert.strictEqual(quiet.values.tab_switches, dp.CONSTANTS.tab_switch_clip);

const blob = JSON.stringify(first);
assert.strictEqual(first.raw_keystrokes_included, false);
assert.strictEqual(blob.indexOf("keystroke_intervals"), -1);
assert.strictEqual(first.values.keystroke_histogram.length, 4);
assert.strictEqual(first.public_parameters.keystroke_histogram.mechanism, "oue");

const unknownTime = dp.localRelease({
    paste_detected: false,
    time_taken_seconds: null,
    typing_cadence_variance_ms: null,
    tab_switches: null
}, { epsilon: 1e6, rng: mulberry32(6) });
assert.strictEqual(unknownTime.values.fast_submission, 0);
assert.strictEqual(unknownTime.values.low_cadence_variance, 0);
assert.strictEqual(unknownTime.values.excessive_tab_switches, 0);
assert.strictEqual(unknownTime.values.tab_switches, 0);

const summary = dp.summarizeRelease(first);
const summaryBlob = JSON.stringify(summary);
assert.ok(summaryBlob.indexOf("not differentially private") !== -1);
assert.ok(summaryBlob.indexOf("discrete Laplace") !== -1);
assert.ok(summary.rows.length >= 7);

assert.throws(function () { dp.rrProbabilities(0); });
assert.throws(function () { dp.allocateBudget(-1); });

console.log("dp_client.test.js: all checks passed");
