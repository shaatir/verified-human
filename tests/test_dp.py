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
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.analytics import (  # noqa: E402
    CADENCE_BIN_LABELS,
    PRIVACY_PATHS,
    TAB_SWITCH_BIN_LABELS,
    central_dashboard_release,
    cohort_privacy_report,
    exact_cohort_statistics,
    synthesize_population,
)
from src.dp import (  # noqa: E402
    CENTRAL_SHARES,
    DAILY_EXPORT_CAP,
    KEYSTROKE_BIN_LABELS,
    LIFETIME_EPSILON_CAP,
    LOCAL_EPSILON_DEFAULT,
    LOCAL_RR_QUERIES,
    LOCAL_SHARES,
    PASTE_COUNT_CLIP,
    TAB_SWITCH_CLIP,
    ExportCapExceeded,
    PrivacyBudgetExceeded,
    advanced_composition,
    allocate_budget,
    audit_epsilon_from_outputs,
    basic_composition,
    client_constants,
    cms_debias_frequencies,
    cms_encode,
    debias_rr_mean,
    discrete_laplace_mechanism,
    discrete_laplace_variance,
    hcms_debias_frequencies,
    hcms_encode,
    local_contribution,
    local_dp_mechanism,
    oue_debias_mean,
    oue_encode,
    oue_probabilities,
    randomized_response,
    rdp_to_approximate,
    rr_probabilities,
    sample_discrete_laplace,
    shuffle_central_epsilon,
    zcdp_to_approximate,
)
from src.ledger import DatasetLedger, DeviceLedger  # noqa: E402
from src.pipeline import process_participant_screening  # noqa: E402


def _load_mock() -> list[dict]:
    with open(os.path.join(ROOT, "data", "participants_mock.json"), encoding="utf-8") as handle:
        return json.load(handle)


class _CountingRng(random.Random):
    def __init__(self, seed: int) -> None:
        super().__init__(seed)
        self.calls = 0

    def random(self) -> float:
        self.calls += 1
        return super().random()


class DiscreteLaplaceTests(unittest.TestCase):
    def test_variance_matches_the_geometric_formula(self) -> None:
        epsilon, sensitivity = 1.0, 1
        expected = discrete_laplace_variance(epsilon, sensitivity)
        rng = random.Random(20261021)
        draws = [sample_discrete_laplace(epsilon, sensitivity, rng) for _ in range(20000)]
        mean = sum(draws) / len(draws)
        variance = sum((draw - mean) ** 2 for draw in draws) / len(draws)
        self.assertAlmostEqual(mean, 0.0, delta=0.08)
        self.assertAlmostEqual(variance, expected, delta=0.35)
        self.assertTrue(all(isinstance(draw, int) for draw in draws))

    def test_mechanism_is_unbiased_for_an_integer_query(self) -> None:
        rng = random.Random(7)
        draws = [discrete_laplace_mechanism(11, 1, 1.0, rng) for _ in range(20000)]
        self.assertAlmostEqual(sum(draws) / len(draws), 11.0, delta=0.08)

    def test_large_epsilon_adds_no_noise(self) -> None:
        rng = random.Random(1)
        self.assertEqual(discrete_laplace_mechanism(PASTE_COUNT_CLIP, PASTE_COUNT_CLIP, 1e6, rng), PASTE_COUNT_CLIP)

    def test_rejects_a_float_query(self) -> None:
        with self.assertRaises(ValueError):
            discrete_laplace_mechanism(1.5, 1, 1.0, random.Random(0))  # type: ignore[arg-type]


class RandomizedResponseTests(unittest.TestCase):
    def test_likelihood_ratio_is_e_to_the_epsilon(self) -> None:
        for epsilon in (0.2, 1.0, 4.0):
            p_truth, p_flip = rr_probabilities(epsilon)
            self.assertAlmostEqual(p_truth + p_flip, 1.0)
            self.assertAlmostEqual(p_truth / p_flip, math.exp(epsilon), places=9)

    def test_debias_recovers_the_rate(self) -> None:
        rate = 0.35
        epsilon = 4.0
        rng = random.Random(99)
        reports = [randomized_response(rng.random() < rate, epsilon, rng) for _ in range(8000)]
        self.assertAlmostEqual(debias_rr_mean(reports, epsilon), rate, delta=0.06)


class OueTests(unittest.TestCase):
    def test_privacy_ratio_equals_epsilon(self) -> None:
        epsilon = 1.0
        p_keep, q_flip = oue_probabilities(epsilon)
        ratio = math.log((p_keep * (1.0 - q_flip)) / ((1.0 - p_keep) * q_flip))
        self.assertAlmostEqual(ratio, epsilon, places=9)

    def test_debias_recovers_a_point_mass(self) -> None:
        epsilon = 2.0
        rng = random.Random(11)
        reports = [oue_encode(0, len(KEYSTROKE_BIN_LABELS), epsilon, rng) for _ in range(8000)]
        estimate = oue_debias_mean(reports, epsilon)
        self.assertAlmostEqual(estimate[0], 1.0, delta=0.08)
        for other in estimate[1:]:
            self.assertAlmostEqual(other, 0.0, delta=0.08)


class AuditTests(unittest.TestCase):
    def test_randomized_response_audit_is_near_epsilon(self) -> None:
        epsilon = 1.0
        rng = random.Random(3)
        outputs_a = [randomized_response(False, epsilon, rng) for _ in range(20000)]
        outputs_b = [randomized_response(True, epsilon, rng) for _ in range(20000)]
        estimated = audit_epsilon_from_outputs(outputs_a, outputs_b, min_count=20)
        self.assertAlmostEqual(estimated, epsilon, delta=0.25)

    def test_discrete_laplace_audit_is_near_epsilon(self) -> None:
        epsilon = 1.0
        rng = random.Random(4)
        outputs_a = [discrete_laplace_mechanism(0, 1, epsilon, rng) for _ in range(30000)]
        outputs_b = [discrete_laplace_mechanism(1, 1, epsilon, rng) for _ in range(30000)]
        estimated = audit_epsilon_from_outputs(outputs_a, outputs_b, min_count=20)
        self.assertGreater(estimated, 0.7)
        self.assertLess(estimated, 1.35)

    def test_oue_audit_is_near_epsilon(self) -> None:
        epsilon = 1.0
        rng = random.Random(5)
        outputs_a = [tuple(oue_encode(0, 2, epsilon, rng)) for _ in range(20000)]
        outputs_b = [tuple(oue_encode(1, 2, epsilon, rng)) for _ in range(20000)]
        estimated = audit_epsilon_from_outputs(outputs_a, outputs_b, min_count=20)
        self.assertAlmostEqual(estimated, epsilon, delta=0.3)


class CompositionTests(unittest.TestCase):
    def test_advanced_is_looser_than_basic_at_epsilon_one(self) -> None:
        self.assertEqual(basic_composition(1, 1.0), 1.0)
        self.assertGreater(advanced_composition(1, 1.0, 1e-6), basic_composition(1, 1.0))

    def test_zcdp_beats_basic_when_the_per_release_epsilon_is_small(self) -> None:
        releases, epsilon, delta = 100, 0.1, 1e-6
        self.assertLess(
            zcdp_to_approximate(releases, epsilon, delta),
            basic_composition(releases, epsilon),
        )
        self.assertLess(
            rdp_to_approximate(releases, epsilon, delta),
            basic_composition(releases, epsilon),
        )


class ShuffleTests(unittest.TestCase):
    def test_solver_returns_a_central_epsilon_or_none(self) -> None:
        amplified = shuffle_central_epsilon(1.0, 2000, 1e-6)
        if amplified is not None:
            self.assertGreater(amplified, 0.0)
            self.assertLessEqual(amplified, 1.0)
        self.assertIsNone(shuffle_central_epsilon(1.0, 2, 1e-6))


class SketchTests(unittest.TestCase):
    def test_sketches_recover_a_point_mass_at_high_epsilon(self) -> None:
        epsilon = 6.0
        domain = 4
        rng = random.Random(13)
        count = 4000
        cms = [cms_encode(0, domain, epsilon, rng) for _ in range(count)]
        hcms = [hcms_encode(0, domain, epsilon, rng) for _ in range(count)]
        cms_estimate = cms_debias_frequencies(cms, domain, epsilon)
        hcms_estimate = hcms_debias_frequencies(hcms, domain, epsilon)
        self.assertAlmostEqual(cms_estimate[0], 1.0, delta=0.15)
        self.assertAlmostEqual(hcms_estimate[0], 1.0, delta=0.15)
        self.assertLess(sum(abs(value) for value in cms_estimate[1:]), 0.4)
        self.assertLess(sum(abs(value) for value in hcms_estimate[1:]), 0.4)


class DeviceLedgerTests(unittest.TestCase):
    def test_replay_is_identical_and_spends_nothing(self) -> None:
        ledger = DeviceLedger()
        rng = _CountingRng(21)
        telemetry = {"paste_detected": True, "tab_switches": 9, "time_taken_seconds": 10.0}
        first = ledger.export(telemetry, "2026-10-21", rng)
        calls = rng.calls
        second = ledger.export({"paste_detected": False, "tab_switches": 0}, "2026-10-21", rng)
        self.assertEqual(rng.calls, calls)
        self.assertEqual(first["values"], second["values"])
        self.assertEqual(second["privacy_spend_this_call"], 0.0)
        self.assertEqual(second["transmission"], 2)
        self.assertAlmostEqual(ledger.lifetime_spent(), LOCAL_EPSILON_DEFAULT)

    def test_daily_cap_does_not_redraw_or_increment(self) -> None:
        ledger = DeviceLedger()
        rng = random.Random(1)
        ledger.export({"paste_detected": False}, "2026-10-21", rng)
        ledger.export({"paste_detected": True}, "2026-10-21", rng)
        with self.assertRaises(ExportCapExceeded):
            ledger.export({"paste_detected": True}, "2026-10-21", rng)
        self.assertEqual(ledger.transmissions("2026-10-21"), DAILY_EXPORT_CAP)

    def test_lifetime_cap_refuses_the_next_day(self) -> None:
        ledger = DeviceLedger()
        rng = random.Random(2)
        for day in range(int(LIFETIME_EPSILON_CAP)):
            ledger.export({"paste_detected": False}, f"2026-01-{day + 1:02d}", rng)
        before = ledger.lifetime_spent()
        with self.assertRaises(PrivacyBudgetExceeded):
            ledger.export({"paste_detected": True}, "2026-02-01", rng)
        self.assertAlmostEqual(ledger.lifetime_spent(), before)
        self.assertEqual(ledger.transmissions("2026-02-01"), 0)

    def test_file_ledger_replays_across_instances(self) -> None:
        directory = tempfile.mkdtemp()
        try:
            path = os.path.join(directory, "device.json")
            first = DeviceLedger(path).export({"paste_detected": True, "tab_switches": 3}, "2026-10-21", random.Random(8))
            second = DeviceLedger(path).export({"paste_detected": False}, "2026-10-21", random.Random(9))
            self.assertEqual(first["values"], second["values"])
            self.assertEqual(second["privacy_spend_this_call"], 0.0)
        finally:
            shutil.rmtree(directory)


class DatasetLedgerTests(unittest.TestCase):
    def _people(self) -> list[dict]:
        return synthesize_population(20, random.Random(5))

    def test_release_requires_a_ledger(self) -> None:
        with self.assertRaises(TypeError):
            central_dashboard_release(self._people())  # type: ignore[call-arg]

    def test_over_budget_batch_leaves_the_file_unchanged(self) -> None:
        directory = tempfile.mkdtemp()
        try:
            path = os.path.join(directory, "dataset.json")
            ledger = DatasetLedger(path, total_epsilon=1.0)
            people = self._people()
            first = central_dashboard_release(
                people, ledger, epsilon=0.6, rng=random.Random(1), publication_name="first"
            )
            with open(path, "rb") as handle:
                before = handle.read()
            with self.assertRaises(PrivacyBudgetExceeded):
                central_dashboard_release(
                    people, ledger, epsilon=0.6, rng=random.Random(2), publication_name="second"
                )
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(), before)
            self.assertAlmostEqual(ledger.spent(), 0.6)
            self.assertFalse(first["replayed"])
            self.assertIsNone(ledger.get_publication("second"))
        finally:
            shutil.rmtree(directory)

    def test_second_call_replays_the_stored_publication(self) -> None:
        directory = tempfile.mkdtemp()
        try:
            path = os.path.join(directory, "dataset.json")
            ledger = DatasetLedger(path)
            people = self._people()
            first = central_dashboard_release(people, ledger, rng=random.Random(3))
            second = central_dashboard_release(people, ledger, rng=random.Random(4))
            self.assertFalse(first["replayed"])
            self.assertTrue(second["replayed"])
            self.assertEqual(first["statistics"], second["statistics"])
            self.assertAlmostEqual(ledger.spent(), 1.0)
            self.assertAlmostEqual(ledger.remaining(), 0.0)
        finally:
            shutil.rmtree(directory)


class MissingFieldTests(unittest.TestCase):
    def test_missing_time_and_variance_are_unknown_not_suspicious(self) -> None:
        person = {
            "participant_id": "missing_fields",
            "name": "Missing",
            "paste_detected": False,
            "focus_paste_coincidence": False,
            "tab_switches_during_form": 1,
            "trap_question_response": "CSS does not leak memory. JavaScript does.",
            "other_responses": ["I write CSS."],
            "github_account_age_days": 800,
            "github_public_repos": 6,
            "github_followers": 4,
        }
        decision = process_participant_screening(person)
        triggered = [
            rule["rule_name"]
            for rule in decision["breakdown"]["tier1"]["triggered_rules"]
            if rule["points"] > 0
        ]
        self.assertIn("Time Delta Check", triggered)
        self.assertIn("Keystroke Variance Check", triggered)
        stats = exact_cohort_statistics([person], [decision])
        self.assertEqual(stats["low_variance_count"], 0)
        self.assertEqual(stats["cadence_histogram"][CADENCE_BIN_LABELS.index("unknown")], 1)
        view = local_contribution(person, random.Random(0))
        self.assertFalse(view["fast_submission"])
        self.assertFalse(view["low_cadence_variance"])

    def test_missing_tabs_are_not_excessive(self) -> None:
        person = {
            "participant_id": "missing_tabs",
            "name": "No Tabs",
            "time_taken_seconds": 120.0,
            "typing_cadence_variance_ms": 40.0,
            "paste_detected": False,
            "trap_question_response": "CSS does not leak memory. JavaScript does.",
            "other_responses": ["I write CSS."],
            "github_account_age_days": 800,
            "github_public_repos": 6,
            "github_followers": 4,
        }
        decision = process_participant_screening(person)
        stats = exact_cohort_statistics([person], [decision])
        self.assertEqual(stats["excessive_tabs_count"], 0)
        self.assertEqual(stats["tab_switch_histogram"][TAB_SWITCH_BIN_LABELS.index("unknown")], 1)
        view = local_contribution(person, random.Random(0))
        self.assertFalse(view["excessive_tab_switches"])
        self.assertEqual(view["tab_switches"], 0)


class ReleaseShapeTests(unittest.TestCase):
    def test_local_release_omits_raw_keystrokes_and_uses_oue(self) -> None:
        intervals = [12.5, 20.0, 180.0, 900.0]
        release = local_dp_mechanism(
            {
                "paste_detected": True,
                "paste_count": 9999,
                "tab_switches": 9999,
                "time_taken_seconds": 12.0,
                "typing_cadence_variance_ms": 1.25,
                "keystroke_intervals_ms": intervals,
            },
            epsilon=1.0,
            rng=random.Random(4),
        )
        blob = json.dumps(release)
        self.assertNotIn("keystroke_intervals", blob)
        self.assertNotIn(json.dumps(intervals), blob)
        self.assertEqual(len(release["values"]["keystroke_histogram"]), len(KEYSTROKE_BIN_LABELS))
        self.assertEqual(release["public_parameters"]["keystroke_histogram"]["mechanism"], "oue")
        self.assertFalse(release["memoized"])
        spent = sum(entry["epsilon"] for entry in release["accountant"]["entries"])
        self.assertAlmostEqual(spent, 1.0)
        quiet = local_dp_mechanism(
            {"paste_count": 9999, "tab_switches": 9999, "paste_detected": True},
            epsilon=1e6,
            rng=random.Random(5),
        )
        self.assertEqual(quiet["values"]["paste_count"], PASTE_COUNT_CLIP)
        self.assertEqual(quiet["values"]["tab_switches"], TAB_SWITCH_CLIP)

    def test_budget_shares_sum_to_the_total(self) -> None:
        for shares in (LOCAL_SHARES, CENTRAL_SHARES):
            allocated = allocate_budget(1.0, shares)
            self.assertAlmostEqual(sum(allocated.values()), 1.0)
        self.assertEqual(LOCAL_EPSILON_DEFAULT, 1.0)

    def test_mock_routing_is_unchanged(self) -> None:
        expected = {
            "legit_human": "APPROVED",
            "script_bot": "AUTO_REJECTED",
            "llm_scammer": "AUTO_REJECTED",
            "borderline_user": "FLAGGED_FOR_REVIEW",
        }
        for person in _load_mock():
            decision = process_participant_screening(person)
            self.assertEqual(decision["status"], expected[person["participant_id"]])
        self.assertFalse(PRIVACY_PATHS["individual_risk_decision"]["differentially_private"])

    def test_aggregate_release_does_not_include_decisions(self) -> None:
        directory = tempfile.mkdtemp()
        try:
            people = _load_mock()
            ledger = DatasetLedger(os.path.join(directory, "mock.json"))
            report = cohort_privacy_report(people, ledger, rng=random.Random(6))
            blob = json.dumps(report["aggregate_release"])
            self.assertNotIn("legit_human", blob)
            self.assertNotIn("cumulative_score", blob)
            self.assertTrue(report["aggregate_release"]["differentially_private"])
            self.assertFalse(report["individual_decisions"]["differentially_private"])
        finally:
            shutil.rmtree(directory)


class SyntheticRoleTests(unittest.TestCase):
    def test_roles_route_to_the_labeled_status(self) -> None:
        population = synthesize_population(40, random.Random(20261021))
        for person in population:
            decision = process_participant_screening(person)
            self.assertEqual(decision["status"], person["expected_status"])


class ClientParityTests(unittest.TestCase):
    def test_browser_constants_match_python(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        script = r"""
        const dp = require("./web/dp.js");
        process.stdout.write(JSON.stringify({
            constants: dp.CONSTANTS,
            budget: dp.allocateBudget(1),
            bins: dp.BIN_LABELS
        }));
        """
        result = subprocess.run(
            [node, "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["constants"], client_constants())
        self.assertEqual(payload["budget"], allocate_budget(1.0, LOCAL_SHARES))
        self.assertEqual(payload["bins"], list(KEYSTROKE_BIN_LABELS))
        suite = subprocess.run(
            [node, os.path.join(ROOT, "tests", "dp_client.test.js")],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(suite.returncode, 0, suite.stdout + suite.stderr)
        for name in LOCAL_RR_QUERIES:
            self.assertIn(name, payload["budget"])


if __name__ == "__main__":
    unittest.main()
