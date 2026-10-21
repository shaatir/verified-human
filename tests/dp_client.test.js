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

[0.2, 1, 4].forEach(function (epsilon) {
    const probs = dp.rrProbabilities(epsilon);
    assertClose(probs.p + probs.q, 1, 1e-12, "rr probabilities sum");
    assertClose(probs.p / probs.q, Math.exp(epsilon), 1e-9, "rr likelihood ratio");
});

[0.5, 1, 4].forEach(function (epsilon) {
    const allocated = dp.allocateBudget(epsilon);
    const total = Object.keys(allocated).reduce(function (sum, key) { return sum + allocated[key]; }, 0);
    assertClose(total, epsilon, 1e-12, "budget sums to epsilon");
});

const scale = 1.5;
const rng = mulberry32(20261021);
const draws = [];
for (let i = 0; i < 20000; i++) draws.push(dp.sampleLaplace(scale, rng));
const mean = draws.reduce(function (sum, value) { return sum + value; }, 0) / draws.length;
const variance = draws.reduce(function (sum, value) {
    const delta = value - mean;
    return sum + delta * delta;
}, 0) / draws.length;
assertClose(mean, 0, 0.08, "laplace mean");
assertClose(variance, 2 * scale * scale, 0.35, "laplace variance");

const rate = 0.35;
const epsilon = 1;
const probs = dp.rrProbabilities(epsilon);
const rrRng = mulberry32(99);
const reports = [];
const n = 40000;
for (let i = 0; i < n; i++) {
    const bit = rrRng() < rate ? 1 : 0;
    reports.push(rrRng() < probs.p ? bit : 1 - bit);
}
assertClose(dp.debiasRrMean(reports, epsilon), rate, 0.03, "debiased randomized response");

assert.deepStrictEqual(
    dp.keystrokeProportionHistogram([12.5, 20, 180, 180, 900]),
    [0.4, 0, 0.4, 0, 0.2]
);

const intervals = [12.5, 20, 180, 180, 900];
const release = dp.localRelease({
    paste_detected: true,
    paste_count: 9999,
    focus_paste_coincidence: true,
    tab_switches: 9999,
    time_taken_seconds: 12,
    typing_cadence_variance_ms: 1.25,
    keystroke_intervals_ms: intervals
}, { epsilon: 1, rng: mulberry32(4) });

const blob = JSON.stringify(release);
assert.strictEqual(release.raw_keystrokes_included, false);
assert.ok(!Object.prototype.hasOwnProperty.call(release, "keystroke_intervals_ms"));
assert.ok(blob.indexOf("keystroke_intervals") === -1);
assert.ok(blob.indexOf(JSON.stringify(intervals)) === -1);
assert.strictEqual(release.values.keystroke_histogram.length, 5);
const spent = release.accountant.entries.reduce(function (sum, entry) { return sum + entry.epsilon; }, 0);
assertClose(spent, 1, 1e-12, "local budget spent");
const histogramEntries = release.accountant.entries.filter(function (entry) {
    return entry.name === "keystroke_histogram";
});
assert.strictEqual(histogramEntries.length, 1);
assert.strictEqual(histogramEntries[0].sensitivity, 2);

const quiet = dp.localRelease({
    paste_detected: true,
    paste_count: 9999,
    focus_paste_coincidence: false,
    tab_switches: 9999,
    time_taken_seconds: 100,
    typing_cadence_variance_ms: 40,
    keystroke_intervals_ms: intervals
}, { epsilon: 1e6, rng: mulberry32(5) });
assertClose(quiet.values.paste_count, dp.CONSTANTS.paste_count_clip, 1e-3, "paste clip");
assertClose(quiet.values.tab_switches, dp.CONSTANTS.tab_switch_clip, 1e-3, "tab clip");
const expectedHist = [0.4, 0, 0.4, 0, 0.2];
quiet.values.keystroke_histogram.forEach(function (value, index) {
    assertClose(value, expectedHist[index], 1e-3, "histogram bin " + index);
});

const summary = dp.summarizeRelease(release);
const summaryBlob = JSON.stringify(summary);
assert.ok(summaryBlob.indexOf("not differentially private") !== -1);
assert.ok(summaryBlob.indexOf(JSON.stringify(intervals)) === -1);
assert.ok(summary.rows.length >= 7);

assert.throws(function () { dp.rrProbabilities(0); });
assert.throws(function () { dp.allocateBudget(-1); });

console.log("dp_client.test.js: all checks passed");
