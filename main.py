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
        print(f"    {CLR_DIM}✔ No suspicious behavioral dynamic triggers detected.{CLR_RESET}")
    for rule in t1["triggered_rules"]:
        print(f"    {CLR_RED}⚠ [{rule['rule_name']}] +{rule['points']} pts{CLR_RESET}")
        print(f"      {CLR_DIM}{rule['details']}{CLR_RESET}")

    # Tier 2
    t2 = breakdown["tier2"]
    print(f"\n  {CLR_BOLD}Tier 2: Semantic Analysis{CLR_RESET} (Subtotal: {t2['score']} pts)")
    if not t2["triggered_rules"]:
        print(f"    {CLR_DIM}✔ No semantic/perplexity anomalies triggered.{CLR_RESET}")
    for rule in t2["triggered_rules"]:
        print(f"    {CLR_RED}⚠ [{rule['rule_name']}] +{rule['points']} pts{CLR_RESET}")
        print(f"      {CLR_DIM}{rule['details']}{CLR_RESET}")

    # Tier 3
    t3 = breakdown["tier3"]
    print(f"\n  {CLR_BOLD}Tier 3: Footprint Integrity{CLR_RESET} (Subtotal: {t3['score']} pts)")
    if not t3["triggered_rules"]:
        print(f"    {CLR_DIM}✔ OSINT footprint verification clean.{CLR_RESET}")
    for rule in t3["triggered_rules"]:
        print(f"    {CLR_RED}⚠ [{rule['rule_name']}] +{rule['points']} pts{CLR_RESET}")
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
        print(f"\n{CLR_GREEN}✔ All integration test cases successfully passed.{CLR_RESET}\n")
    else:
        print(f"\n{CLR_RED}❌ Test failure detected! Some outputs deviated from expectation.{CLR_RESET}\n")
        
    return all_passed


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
        help="Execute the automated test suite."
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
        success = run_automated_tests(participants)
        sys.exit(0 if success else 1)

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
    print(f"  {len(participants)+3}. Exit")

    try:
        choice = input(f"\nSelect a menu option (1-{len(participants)+3}): ").strip()
        choice_idx = int(choice) - 1
        
        if choice_idx == len(participants):
            success = run_automated_tests(participants)
            sys.exit(0 if success else 1)
        elif choice_idx == len(participants) + 1:
            for p in participants:
                report = process_participant_screening(p)
                display_risk_report(report, p)
        elif choice_idx == len(participants) + 2:
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
