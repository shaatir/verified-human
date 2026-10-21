"""Statistical and regression tests for the differential-privacy layer.

Seeded PRNGs keep the Monte Carlo checks stable. Tolerances sit several standard
errors out, so a correct sampler passes and a wrong scale or a biased debiasing
formula fails.
"""

from __future__ import annotations

import json
import math
import os
import random
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.analytics import (  # noqa: E402
    PRIVACY_PATHS,
    central_dashboard_release,
    cohort_privacy_report,
    exact_cohort_statistics,
    synthesize_population,
)
from src.dp import (  # noqa: E402
    CENTRAL_SHARES,
    KEYSTROKE_BIN_LABELS,
    LOCAL_EPSILON_DEFAULT,
    LOCAL_RR_QUERIES,
    LOCAL_SHARES,
    PASTE_COUNT_CLIP,
    TAB_SWITCH_CLIP,
    PrivacyAccountant,
    PrivacyBudgetExceeded,
    aggregate_local_releases,
    allocate_budget,
    client_constants,
    debias_rr_mean,
    keystroke_proportion_histogram,
    laplace_mechanism,
    laplace_scale,
    local_contribution,
    local_dp_release,
    rr_probabilities,
    sample_laplace,
)
from src.pipeline import process_participant_screening  # noqa: E402


def _load_mock() -> list[dict]:
    with open(os.path.join(ROOT, "data", "participants_mock.json"), encoding="utf-8") as handle:
        return json.load(handle)


class LaplaceMechanismTests(unittest.TestCase):
    def test_scale_is_sensitivity_over_epsilon(self) -> None:
        self.assertEqual(laplace_scale(2.0, 0.5), 4.0)
        self.assertEqual(laplace_scale(1.0, 1.0), 1.0)
        self.assertEqual(laplace_scale(0.0, 1.0), 0.0)
        self.assertAlmostEqual(laplace_scale(TAB_SWITCH_CLIP, 0.1), TAB_SWITCH_CLIP / 0.1)

    def test_scale_rejects_non_positive_epsilon(self) -> None:
        for epsilon in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                laplace_scale(1.0, epsilon)

    def test_noise_is_zero_mean_with_variance_2_b_squared(self) -> None:
        scale = 1.5
        rng = random.Random(20261021)
        draws = [sample_laplace(scale, rng) for _ in range(20000)]
        mean = sum(draws) / len(draws)
        variance = sum((draw - mean) ** 2 for draw in draws) / len(draws)
        # Standard error of the mean is scale * sqrt(2 / n) ≈ 0.015.
        self.assertAlmostEqual(mean, 0.0, delta=0.08)
        self.assertAlmostEqual(variance, 2 * scale * scale, delta=0.35)
        self.assertTrue(any(draw > 0 for draw in draws[:50]))
        self.assertTrue(any(draw < 0 for draw in draws[:50]))

    def test_mechanism_is_unbiased_for_the_query(self) -> None:
        truth = 40.0
        sensitivity = 1.0
        epsilon = 1.0
        rng = random.Random(11)
        draws = [
            laplace_mechanism(truth, sensitivity, epsilon, rng) for _ in range(8000)
        ]
        mean = sum(draws) / len(draws)
        self.assertAlmostEqual(mean, truth, delta=0.08)
        self.assertEqual(laplace_scale(sensitivity, epsilon), sensitivity / epsilon)


class RandomizedResponseTests(unittest.TestCase):
    def test_likelihood_ratio_equals_exp_epsilon(self) -> None:
        for epsilon in (0.2, 1.0, 4.0):
            p_truth, p_flip = rr_probabilities(epsilon)
            self.assertAlmostEqual(p_truth + p_flip, 1.0)
            self.assertAlmostEqual(p_truth / p_flip, math.exp(epsilon))
            self.assertGreater(p_truth, p_flip)

    def test_debiased_mean_matches_the_secret_rate(self) -> None:
        epsilon = 1.0
        rate = 0.35
        rng = random.Random(99)
        n = 40000
        p_truth, _p_flip = rr_probabilities(epsilon)
        reports = []
        for _ in range(n):
            bit = 1 if rng.random() < rate else 0
            if rng.random() < p_truth:
                reports.append(bit)
            else:
                reports.append(1 - bit)
        estimate = debias_rr_mean(reports, epsilon)
        # Standard error is about 0.005 at this n and ε. 0.03 is far outside it.
        self.assertAlmostEqual(estimate, rate, delta=0.03)

    def test_aggregate_of_local_releases_is_unbiased(self) -> None:
        epsilon = 4.0
        rng = random.Random(123)
        releases = []
        truths = []
        for index in range(8000):
            pasted = index % 5 == 0
            truths.append(pasted)
            releases.append(
                local_dp_release(
                    {
                        "paste_detected": pasted,
                        "paste_count": 0,
                        "focus_paste_coincidence": False,
                        "tab_switches": 0,
                        "time_taken_seconds": 90,
                        "typing_cadence_variance_ms": 30.0,
                        "keystroke_intervals_ms": [],
                    },
                    epsilon=epsilon,
                    rng=rng,
                )
            )
        estimate = aggregate_local_releases(releases)["randomized_response_rates"]["paste_detected"][
            "debiased_rate"
        ]
        self.assertAlmostEqual(estimate, sum(truths) / len(truths), delta=0.06)


class AccountantTests(unittest.TestCase):
    def test_basic_composition_sums_and_refuses_overspend(self) -> None:
        accountant = PrivacyAccountant(1.0)
        accountant.spend("status", 0.3, "laplace", 2.0)
        accountant.spend("paste", 0.3, "laplace", 1.0)
        accountant.spend("tabs", 0.4, "laplace", 1.0)
        self.assertAlmostEqual(accountant.spent, 1.0)
        self.assertAlmostEqual(accountant.remaining, 0.0)
        self.assertEqual(accountant.summary()["composition"], "basic")
        with self.assertRaises(PrivacyBudgetExceeded):
            accountant.spend("extra", 0.01, "laplace", 1.0)
        self.assertAlmostEqual(accountant.spent, 1.0)

    def test_allocate_budget_sums_to_epsilon(self) -> None:
        for epsilon in (0.25, 1.0, 4.0):
            allocated = allocate_budget(epsilon, CENTRAL_SHARES)
            self.assertAlmostEqual(sum(allocated.values()), epsilon)

    def test_two_dashboard_releases_compose_on_one_accountant(self) -> None:
        participants = _load_mock()
        accountant = PrivacyAccountant(1.0)
        central_dashboard_release(
            participants, epsilon=0.6, rng=random.Random(1), accountant=accountant
        )
        central_dashboard_release(
            participants, epsilon=0.4, rng=random.Random(2), accountant=accountant
        )
        self.assertAlmostEqual(accountant.spent, 1.0)
        with self.assertRaises(PrivacyBudgetExceeded):
            central_dashboard_release(
                participants, epsilon=0.1, rng=random.Random(3), accountant=accountant
            )


class LocalReleaseTests(unittest.TestCase):
    def _telemetry(self) -> dict:
        return {
            "paste_detected": True,
            "paste_count": 9999,
            "focus_paste_coincidence": True,
            "tab_switches": 9999,
            "time_taken_seconds": 12.0,
            "typing_cadence_variance_ms": 1.25,
            "keystroke_intervals_ms": [12.5, 20.0, 180.0, 180.0, 900.0],
        }

    def test_release_drops_raw_keystrokes_and_spends_the_budget_once(self) -> None:
        telemetry = self._telemetry()
        release = local_dp_release(telemetry, epsilon=LOCAL_EPSILON_DEFAULT, rng=random.Random(4))
        blob = json.dumps(release)
        self.assertNotIn("keystroke_intervals", blob)
        self.assertNotIn(json.dumps(telemetry["keystroke_intervals_ms"]), blob)
        self.assertFalse(release["raw_keystrokes_included"])
        self.assertFalse(release["individual_decision_included"])
        self.assertTrue(release["differentially_private"])
        self.assertEqual(len(release["values"]["keystroke_histogram"]), len(KEYSTROKE_BIN_LABELS))
        spent = sum(entry["epsilon"] for entry in release["accountant"]["entries"])
        self.assertAlmostEqual(spent, LOCAL_EPSILON_DEFAULT)
        self.assertAlmostEqual(release["accountant"]["spent_epsilon"], LOCAL_EPSILON_DEFAULT)
        histogram_entries = [
            entry for entry in release["accountant"]["entries"] if entry["name"] == "keystroke_histogram"
        ]
        self.assertEqual(len(histogram_entries), 1)
        self.assertAlmostEqual(histogram_entries[0]["sensitivity"], 2.0)

    def test_clipping_bounds_the_contribution_before_noise(self) -> None:
        contribution = local_contribution(self._telemetry())
        self.assertEqual(contribution["paste_count"], PASTE_COUNT_CLIP)
        self.assertEqual(contribution["tab_switches"], TAB_SWITCH_CLIP)
        self.assertTrue(contribution["excessive_tab_switches"])
        self.assertTrue(contribution["fast_submission"])
        self.assertTrue(contribution["low_cadence_variance"])
        # Intervals: 12.5 and 20 in [0, 50), two at 180 in [150, 300), 900 in [600, inf).
        self.assertEqual(
            keystroke_proportion_histogram([12.5, 20.0, 180.0, 180.0, 900.0]),
            [0.4, 0.0, 0.4, 0.0, 0.2],
        )
        release = local_dp_release(self._telemetry(), epsilon=1e6, rng=random.Random(5))
        self.assertAlmostEqual(release["values"]["paste_count"], PASTE_COUNT_CLIP, delta=1e-3)
        self.assertAlmostEqual(release["values"]["tab_switches"], TAB_SWITCH_CLIP, delta=1e-3)
        for noisy, exact in zip(
            release["values"]["keystroke_histogram"],
            [0.4, 0.0, 0.4, 0.0, 0.2],
        ):
            self.assertAlmostEqual(noisy, exact, delta=1e-3)

    def test_histogram_noise_scale_matches_l1_sensitivity(self) -> None:
        release = local_dp_release(self._telemetry(), epsilon=1.0, rng=random.Random(6))
        histogram = release["public_parameters"]["laplace"]["keystroke_histogram"]
        self.assertAlmostEqual(histogram["scale"], 2.0 / histogram["epsilon"])
        paste = release["public_parameters"]["laplace"]["paste_count"]
        self.assertAlmostEqual(paste["scale"], PASTE_COUNT_CLIP / paste["epsilon"])
        tabs = release["public_parameters"]["laplace"]["tab_switches"]
        self.assertAlmostEqual(tabs["scale"], TAB_SWITCH_CLIP / tabs["epsilon"])

    def test_rr_queries_are_the_ones_in_the_release(self) -> None:
        release = local_dp_release(self._telemetry(), rng=random.Random(7))
        for name in LOCAL_RR_QUERIES:
            self.assertIn(release["values"][name], (0, 1))


class CentralReleaseTests(unittest.TestCase):
    def test_noise_scales_match_substitution_sensitivity(self) -> None:
        participants = _load_mock()
        release = central_dashboard_release(participants, epsilon=1.0, rng=random.Random(8))
        stats = release["statistics"]
        paste = stats["paste_detected_count"]
        self.assertEqual(paste["sensitivity"], 1.0)
        self.assertAlmostEqual(paste["scale"], 1.0 / paste["epsilon"])
        status = stats["status_histogram"]
        self.assertEqual(status["sensitivity_l1"], 2.0)
        self.assertAlmostEqual(status["scale"], 2.0 / status["epsilon"])
        self.assertEqual(status["bins"], ["APPROVED", "FLAGGED_FOR_REVIEW", "AUTO_REJECTED"])
        self.assertEqual(len(status["noisy"]), 3)
        for noisy, published in zip(status["noisy"], status["published"]):
            self.assertEqual(published, max(0.0, noisy))
        spent = sum(entry["epsilon"] for entry in release["accountant"]["entries"])
        self.assertAlmostEqual(spent, 1.0)
        self.assertEqual(len(release["accountant"]["entries"]), 6)
        self.assertTrue(release["cohort_size_is_public"])
        self.assertEqual(release["cohort_size"], 4)
        self.assertFalse(release["individual_decisions_included"])

    def test_release_does_not_carry_microdata_or_exact_counts(self) -> None:
        participants = _load_mock()
        report = cohort_privacy_report(participants, epsilon=1.0, rng=random.Random(9))
        blob = json.dumps(report["aggregate_release"])
        self.assertNotIn("Alex Mercer", blob)
        self.assertNotIn("Jane AI-Scammer", blob)
        self.assertNotIn("trap_question", blob)
        self.assertNotIn("expected_status", blob)
        self.assertNotIn("keystroke_intervals", blob)
        exact = exact_cohort_statistics(participants)
        # The exact paste count is a property of this fixture (two of four paste).
        # It must not be stored under a truth field on the release.
        self.assertNotIn("true_count", blob)
        self.assertNotIn("exact", blob)
        self.assertEqual(exact["paste_detected_count"], 2)

    def test_paths_document_which_outputs_are_private(self) -> None:
        self.assertFalse(PRIVACY_PATHS["individual_risk_decision"]["differentially_private"])
        self.assertTrue(PRIVACY_PATHS["local_aggregate_export"]["differentially_private"])
        self.assertTrue(PRIVACY_PATHS["central_dashboard_aggregates"]["differentially_private"])
        report = cohort_privacy_report(_load_mock(), rng=random.Random(10))
        self.assertFalse(report["individual_decisions"]["differentially_private"])
        self.assertTrue(report["aggregate_release"]["differentially_private"])
        self.assertFalse(report["local_export"]["computed_here"])


class DetectionStillWorksTests(unittest.TestCase):
    def test_mock_participants_keep_their_routes(self) -> None:
        expected = {
            "legit_human": "APPROVED",
            "script_bot": "AUTO_REJECTED",
            "llm_scammer": "AUTO_REJECTED",
            "borderline_user": "FLAGGED_FOR_REVIEW",
        }
        participants = _load_mock()
        report = cohort_privacy_report(participants, epsilon=1.0, rng=random.Random(11))
        for participant, decision in zip(participants, report["individual_decisions"]["results"]):
            direct = process_participant_screening(participant)
            self.assertEqual(decision, direct)
            self.assertEqual(decision["status"], expected[participant["participant_id"]])

    def test_local_export_is_not_an_input_to_scoring(self) -> None:
        participant = _load_mock()[1]
        before = process_participant_screening(participant)
        local_dp_release(
            {
                "paste_detected": participant["paste_detected"],
                "tab_switches": participant["tab_switches_during_form"],
                "time_taken_seconds": participant["time_taken_seconds"],
                "typing_cadence_variance_ms": participant["typing_cadence_variance_ms"],
                "keystroke_intervals_ms": [1, 1, 1, 1],
            },
            rng=random.Random(12),
        )
        after = process_participant_screening(participant)
        self.assertEqual(before, after)
        self.assertEqual(after["status"], "AUTO_REJECTED")

    def test_synthetic_roles_stay_inside_their_routing_region(self) -> None:
        population = synthesize_population(40, random.Random(13))
        self.assertEqual(len(population), 40)
        for person in population:
            decision = process_participant_screening(person)
            self.assertEqual(decision["status"], person["expected_status"])
        report = cohort_privacy_report(population, epsilon=0.5, rng=random.Random(14))
        blob = json.dumps(report["aggregate_release"])
        self.assertNotIn("expected_status", blob)
        self.assertNotIn("keystroke_intervals", blob)


class BrowserParityTests(unittest.TestCase):
    def test_client_module_matches_python_and_its_own_checks(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        script = os.path.join(ROOT, "tests", "dp_client.test.js")
        completed = subprocess.run(
            [node, script],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + "\n" + completed.stderr,
        )
        dump = subprocess.run(
            [
                node,
                "-e",
                (
                    "const dp = require('./web/dp.js');"
                    "const allocated = {};"
                    "for (const eps of [0.5, 1, 2, 4]) allocated[String(eps)] = dp.allocateBudget(eps);"
                    "console.log(JSON.stringify({constants: dp.CONSTANTS, allocated}));"
                ),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(dump.returncode, 0, dump.stderr)
        payload = json.loads(dump.stdout)
        self.assertEqual(payload["constants"], client_constants())
        for epsilon_text, js_budget in payload["allocated"].items():
            python_budget = allocate_budget(float(epsilon_text), LOCAL_SHARES)
            self.assertEqual(set(js_budget), set(python_budget))
            for name, value in python_budget.items():
                self.assertAlmostEqual(js_budget[name], value, places=12)


if __name__ == "__main__":
    unittest.main()
