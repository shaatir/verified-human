#!/usr/bin/env python3
"""CLI Entry point for Project Verified-Human.

Provides a polished, scannable CLI interface and an automated verification test suite
to evaluate screening participants.
"""

import os
import sys
import json
import argparse
from typing import Dict, Any, List

# Add the root directory to path to enable package src lookup
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.pipeline import process_participant_screening

# --- ANSI Colors for Premium CLI Aesthetics ---
CLR_RESET = "\033[0m"
CLR_BOLD = "\033[1m"
CLR_DIM = "\033[2m"

# Harmonic Tailored Colors
CLR_GREEN = "\033[38;2;46;204;113m"      # Emerald Green
CLR_YELLOW = "\033[38;2;241;196;15m"     # Warning Gold
CLR_RED = "\033[38;2;231;76;60m"        # Alizarin Red
CLR_CYAN = "\033[38;2;52;152;219m"       # Sleek Cyan
CLR_MAGENTA = "\033[38;2;155;89;182m"    # Amethyst Purple
CLR_WHITE = "\033[37m"


def get_status_color(status: str) -> str:
    """Returns the ANSI color string corresponding to the routing status."""
    if status == "APPROVED":
        return CLR_GREEN
    elif status == "FLAGGED_FOR_REVIEW":
        return CLR_YELLOW
    return CLR_RED


def render_progress_bar(score: int, width: int = 20) -> str:
    """Creates a beautiful visual progression bar for score density."""
    filled_len = int(round(width * score / 100.0))
    bar = "█" * filled_len + "░" * (width - filled_len)
    
    # Color-code the progress bar
    if score < 30:
        bar_color = CLR_GREEN
    elif score < 60:
        bar_color = CLR_YELLOW
    else:
        bar_color = CLR_RED
        
    return f"{bar_color}[{bar}]{CLR_RESET} {CLR_BOLD}{score}/100{CLR_RESET}"


def print_box_header(title: str, color: str = CLR_CYAN) -> None:
    """Prints a styled subsection header."""
    print(f"\n{color}╓{'─'*50}╖{CLR_RESET}")
    print(f"{color}║ {CLR_BOLD}{title:<48}{CLR_RESET}{color} ║{CLR_RESET}")
    print(f"{color}╙{'─'*50}╜{CLR_RESET}")


def display_risk_report(report: Dict[str, Any], payload: Dict[str, Any]) -> None:
    """Outputs a beautifully formatted terminal report with box layouts and color coding."""
    status = report["status"]
    color = get_status_color(status)
    
    # 1. Main Header Box
    print(f"\n{color}╔{'═' * 70}╗{CLR_RESET}")
    print(f"{color}║{CLR_RESET} {CLR_BOLD}PARTICIPANT RISK & LEGITIMACY REPORT{CLR_RESET:<49} {color}║{CLR_RESET}")
    print(f"{color}╠{'═' * 70}╣{CLR_RESET}")
    print(f"{color}║{CLR_RESET} {CLR_BOLD}Participant ID:{CLR_RESET} {report['participant_id']:<18} {CLR_BOLD}Name:{CLR_RESET} {report['name']:<27} {color}║{CLR_RESET}")
    print(f"{color}║{CLR_RESET} {CLR_BOLD}Assigned Status:{CLR_RESET} {color}{CLR_BOLD}{status:<17}{CLR_RESET} {CLR_BOLD}Risk Score:{CLR_RESET} {render_progress_bar(report['cumulative_score'], 15):<19} {color}║{CLR_RESET}")
    print(f"{color}╚{'═' * 70}╝{CLR_RESET}")

    # 2. General Submission Info
    print_box_header("SUBMISSION METADATA", CLR_CYAN)
    print(f"  {CLR_BOLD}Time Taken:{CLR_RESET} {payload.get('time_taken_seconds')} seconds")
    print(f"  {CLR_BOLD}Keystroke Variance:{CLR_RESET} {payload.get('typing_cadence_variance_ms'):.2f} ms")
    print(f"  {CLR_BOLD}Paste Detected:{CLR_RESET} {CLR_RED if payload.get('paste_detected') else CLR_GREEN}{payload.get('paste_detected')}{CLR_RESET}")
    print(f"  {CLR_BOLD}Tab Switches:{CLR_RESET} {payload.get('tab_switches_during_form')}")
    print(f"  {CLR_BOLD}GitHub Footprint:{CLR_RESET} {payload.get('github_account_age_days')} days old | {payload.get('github_public_repos')} public repos | {payload.get('github_followers')} followers")

    # 3. Rule Breakdown Tiers
    print_box_header("RISK ASSESSMENT DETAILED BREAKDOWN", CLR_MAGENTA)
    
    breakdown = report["breakdown"]
    
    # Tier 1
    t1 = breakdown["tier1"]
    print(f"\n  {CLR_BOLD}Tier 1: Behavioral Dynamics{CLR_RESET} (Subtotal: {t1['score']} pts)")
    if not t1["triggered_rules"]:
        print(f"    {CLR_GREEN}✓ No suspicious behavioral dynamic triggers detected.{CLR_RESET}")
    for rule in t1["triggered_rules"]:
        print(f"    {CLR_RED}✗ [{rule['rule_name']}] +{rule['points']} pts{CLR_RESET}")
        print(f"      {CLR_DIM}{rule['details']}{CLR_RESET}")

    # Tier 2
    t2 = breakdown["tier2"]
    print(f"\n  {CLR_BOLD}Tier 2: Semantic Analysis{CLR_RESET} (Subtotal: {t2['score']} pts)")
    if not t2["triggered_rules"]:
        print(f"    {CLR_GREEN}✓ No semantic/perplexity anomalies triggered.{CLR_RESET}")
    for rule in t2["triggered_rules"]:
        print(f"    {CLR_RED}✗ [{rule['rule_name']}] +{rule['points']} pts{CLR_RESET}")
        print(f"      {CLR_DIM}{rule['details']}{CLR_RESET}")

    # Tier 3
    t3 = breakdown["tier3"]
    print(f"\n  {CLR_BOLD}Tier 3: Footprint Integrity{CLR_RESET} (Subtotal: {t3['score']} pts)")
    if not t3["triggered_rules"]:
        print(f"    {CLR_GREEN}✓ OSINT footprint verification clean.{CLR_RESET}")
    for rule in t3["triggered_rules"]:
        print(f"    {CLR_RED}✗ [{rule['rule_name']}] +{rule['points']} pts{CLR_RESET}")
        print(f"      {CLR_DIM}{rule['details']}{CLR_RESET}")

    # 4. Answers preview
    print_box_header("SEMANTIC ANSWERS PREVIEW", CLR_CYAN)
    trap_ans = payload.get("trap_question_response", "")
    print(f"  {CLR_BOLD}Trap Question Response:{CLR_RESET}")
    # Wrap text cleanly for preview
    lines = [trap_ans[i:i+75] for i in range(0, len(trap_ans), 75)]
    for line in lines[:4]:
        print(f"    {CLR_DIM}{line}{CLR_RESET}")
    if len(lines) > 4:
        print(f"    {CLR_DIM}... (truncated){CLR_RESET}")
    print()


def run_automated_tests(participants: List[Dict[str, Any]]) -> bool:
    """Executes verification tests ensuring participants route correctly."""
    print(f"\n{CLR_BOLD}🚀 RUNNING AUTOMATED COMPLIANCE & INTEGRATION TESTS...{CLR_RESET}")
    
    expected_outcomes = {
        "legit_human": "APPROVED",
        "script_bot": "AUTO_REJECTED",
        "llm_scammer": "AUTO_REJECTED",
        "borderline_user": "FLAGGED_FOR_REVIEW"
    }

    all_passed = True
    print(f"{CLR_DIM}┌{'─'*30}┬{'─'*22}┬{'─'*22}┬{'─'*11}┐{CLR_RESET}")
    print(f"{CLR_DIM}│{CLR_RESET} {CLR_BOLD}{'Participant ID':<28}{CLR_RESET} {CLR_DIM}│{CLR_RESET} {CLR_BOLD}{'Expected Status':<20}{CLR_RESET} {CLR_DIM}│{CLR_RESET} {CLR_BOLD}{'Actual Status':<20}{CLR_RESET} {CLR_DIM}│{CLR_RESET} {CLR_BOLD}{'Result':<9}{CLR_RESET} {CLR_DIM}│{CLR_RESET}")
    print(f"{CLR_DIM}├{'─'*30}┼{'─'*22}┼{'─'*22}┼{'─'*11}┤{CLR_RESET}")

    for participant in participants:
        pid = participant["participant_id"]
        expected = expected_outcomes.get(pid, "UNKNOWN")
        report = process_participant_screening(participant)
        actual = report["status"]
        
        passed = (actual == expected)
        result_str = f"{CLR_GREEN}PASSED{CLR_RESET}" if passed else f"{CLR_RED}FAILED{CLR_RESET}"
        
        if not passed:
            all_passed = False
            
        print(f"{CLR_DIM}│{CLR_RESET} {pid:<28} {CLR_DIM}│{CLR_RESET} {expected:<20} {CLR_DIM}│{CLR_RESET} {actual:<20} {CLR_DIM}│{CLR_RESET} {result_str:<18} {CLR_DIM}│{CLR_RESET}")

    print(f"{CLR_DIM}└{'─'*30}┴{'─'*22}┴{'─'*22}┴{'─'*11}┘{CLR_RESET}")

    if all_passed:
        print(f"\n{CLR_GREEN}✓ All integration test cases successfully passed.{CLR_RESET}\n")
    else:
        print(f"\n{CLR_RED}✗ Test failure detected! Some outputs deviated from expectation.{CLR_RESET}\n")
        
    return all_passed


def run_dp_unit_tests(base_dir: str) -> bool:
    """Runs the differential-privacy unittest suite."""
    import unittest

    suite = unittest.defaultTestLoader.discover(
        os.path.join(base_dir, "tests"),
        pattern="test_*.py",
    )
    print(f"\n{CLR_BOLD}RUNNING DIFFERENTIAL PRIVACY TESTS...{CLR_RESET}")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return result.wasSuccessful()


def display_privacy_analytics(base_dir: str) -> None:
    """Print exact status counts beside one central DP release of 2,000 people.

    The cohort is synthetic and seeded, so a second run replays the stored
    publication instead of drawing new noise. Exact query answers are a
    curator-only comparison. They are not fields on the release object.
    Individual names are not printed.
    """
    import random
    from collections import Counter

    from src.analytics import (
        STATUS_BINS,
        cohort_privacy_report,
        exact_cohort_statistics,
        synthesize_population,
    )
    from src.ledger import DatasetLedger

    cohort_rng = random.Random(20261021)
    population = synthesize_population(2000, cohort_rng)
    ledger_path = os.path.join(base_dir, "data", "ledgers", "synthetic-cohort.json")
    ledger = DatasetLedger(ledger_path)
    report = cohort_privacy_report(population, ledger, rng=random.SystemRandom())
    decisions = report["individual_decisions"]["results"]
    exact = exact_cohort_statistics(population, decisions)
    release = report["aggregate_release"]
    cohort_size = release["cohort_size"]
    counts = Counter(decision["status"] for decision in decisions)

    print(f"\n{CLR_BOLD}PRIVACY REPORT{CLR_RESET}  synthetic cohort n={cohort_size}  seed=20261021")
    print(f"{CLR_YELLOW}Individual decisions are exact and are NOT differentially private.{CLR_RESET}")
    print(f"{CLR_DIM}{report['individual_decisions']['reason']}{CLR_RESET}")
    print(f"{CLR_DIM}Status counts only. Per-person scores stay exact and are not listed.{CLR_RESET}\n")
    for status in STATUS_BINS:
        print(f"  {get_status_color(status)}{status:<22}{CLR_RESET} {counts[status]:>5}")

    replay = "replayed stored publication; no new noise and no new spend" if release.get("replayed") else "new publication stored in the dataset ledger"
    print(f"\n{CLR_CYAN}{CLR_BOLD}Central DP aggregate release{CLR_RESET}  ({replay})")
    print(
        f"  ε={release['epsilon']:.2f}  composition=basic  mechanism=discrete Laplace  "
        f"spent={release['accountant']['spent_epsilon']:.2f}  "
        f"remaining={release['accountant']['remaining_epsilon']:.2f}"
    )
    print(f"  {CLR_DIM}{release['cohort_size_reason']}{CLR_RESET}")
    print(f"  {CLR_DIM}{release['float_laplace']}{CLR_RESET}")
    print(f"  {CLR_DIM}Curator columns are not part of the released object.{CLR_RESET}")

    def print_count(label: str, exact_value: int, stat: Dict[str, Any]) -> None:
        print(
            f"  {label:<24} curator {exact_value:>6}   "
            f"noisy {stat['noisy']:>8}   published {stat['published']:>8}   "
            f"ε={stat['epsilon']:.2f}"
        )

    stats = release["statistics"]
    print_count("Paste detected", exact["paste_detected_count"], stats["paste_detected_count"])
    print_count("Low cadence variance", exact["low_variance_count"], stats["low_variance_count"])
    print_count("Excessive tab switches", exact["excessive_tabs_count"], stats["excessive_tabs_count"])

    def print_histogram(label: str, exact_counts: List[int], stat: Dict[str, Any]) -> None:
        print(
            f"\n  {CLR_BOLD}{label}{CLR_RESET}  L1 sensitivity {stat['sensitivity_l1']}  "
            f"ε={stat['epsilon']:.2f}  noise variance={stat['noise_variance']:.2f}"
        )
        for name, exact_value, noisy, published in zip(
            stat["bins"], exact_counts, stat["noisy"], stat["published"]
        ):
            print(
                f"    {name:<22} curator {exact_value:>6}   "
                f"noisy {noisy:>8}   published {published:>8}"
            )

    print_histogram("Status", exact["status_histogram"], stats["status_histogram"])
    print_histogram("Tab switches", exact["tab_switch_histogram"], stats["tab_switch_histogram"])
    print_histogram("Cadence variance (ms)", exact["cadence_histogram"], stats["cadence_histogram"])

    print(f"\n  {CLR_BOLD}Ledger{CLR_RESET}  {ledger_path}")
    for entry in release["accountant"]["entries"]:
        print(
            f"    {entry['name']:<24} {entry['mechanism']:<18} "
            f"ε={entry['epsilon']:.2f}  Δ={entry['sensitivity']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verified-Human: Advanced Fraud Operations & Semantic Security Pipeline CLI",
        formatter_class=argparse.RawTextHelpFormatter
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--id", type=str,
        help="Specify the participant ID to run the risk evaluation against."
    )
    group.add_argument(
        "--all", action="store_true",
        help="Audit all participants in the mock database."
    )
    group.add_argument(
        "--test", action="store_true",
        help="Execute the routing checks and the differential-privacy tests."
    )
    group.add_argument(
        "--analytics", action="store_true",
        help="Print exact status counts and a central DP release for a seeded cohort of 2,000."
    )

    args = parser.parse_args()

    # Locate database
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, "data", "participants_mock.json")
    
    if not os.path.exists(db_path):
        print(f"{CLR_RED}Error: Mock dataset not found at: {db_path}{CLR_RESET}")
        sys.exit(1)

    with open(db_path, "r", encoding="utf-8") as f:
        participants = json.load(f)

    if args.test:
        routing_ok = run_automated_tests(participants)
        privacy_ok = run_dp_unit_tests(base_dir)
        sys.exit(0 if routing_ok and privacy_ok else 1)

    if args.analytics:
        display_privacy_analytics(base_dir)
        sys.exit(0)

    if args.all:
        print(f"\n{CLR_BOLD}🔍 AUDITING ALL PARTICIPANTS IN MOCK DATABASE...{CLR_RESET}")
        for p in participants:
            report = process_participant_screening(p)
            display_risk_report(report, p)
        sys.exit(0)

    if args.id:
        target = next((p for p in participants if p["participant_id"] == args.id), None)
        if not target:
            print(f"{CLR_RED}Error: Participant ID '{args.id}' not found.{CLR_RESET}")
            print(f"Available IDs: {', '.join([p['participant_id'] for p in participants])}")
            sys.exit(1)
        
        report = process_participant_screening(target)
        display_risk_report(report, target)
        sys.exit(0)

    # Interactive Select Mode if no arguments provided
    print(f"\n{CLR_CYAN}{CLR_BOLD}=== Welcome to Verified-Human: Semantic Security CLI ==={CLR_RESET}")
    print(f"Available participant IDs in database:")
    for idx, p in enumerate(participants, 1):
        print(f"  {idx}. {CLR_BOLD}{p['participant_id']:<20}{CLR_RESET} ({p['name']})")
    
    print(f"  {len(participants)+1}. Run all automated tests")
    print(f"  {len(participants)+2}. Run audit for all participants")
    print(f"  {len(participants)+3}. Run privacy analytics")
    print(f"  {len(participants)+4}. Exit")

    try:
        choice = input(f"\nSelect a menu option (1-{len(participants)+4}): ").strip()
        choice_idx = int(choice) - 1
        
        if choice_idx == len(participants):
            routing_ok = run_automated_tests(participants)
            privacy_ok = run_dp_unit_tests(base_dir)
            sys.exit(0 if routing_ok and privacy_ok else 1)
        elif choice_idx == len(participants) + 1:
            for p in participants:
                report = process_participant_screening(p)
                display_risk_report(report, p)
        elif choice_idx == len(participants) + 2:
            display_privacy_analytics(base_dir)
        elif choice_idx == len(participants) + 3:
            print("Exiting...")
            sys.exit(0)
        elif 0 <= choice_idx < len(participants):
            p = participants[choice_idx]
            report = process_participant_screening(p)
            display_risk_report(report, p)
        else:
            print(f"{CLR_RED}Invalid option selected.{CLR_RESET}")
    except (ValueError, KeyboardInterrupt, EOFError):
        print("\nOperation cancelled.")


if __name__ == "__main__":
    main()
