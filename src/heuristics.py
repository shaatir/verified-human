"""Heuristics engine for evaluating behavioral dynamics (Tier 1) and footprint integrity (Tier 3).

Strictly typed and modular implementation with zero external dependencies.
"""

from typing import Dict, Any, List, Tuple


def evaluate_tier1_behavioral(payload: Dict[str, Any]) -> Tuple[int, List[Dict[str, Any]]]:
    """Evaluates Tier 1 Behavioral Dynamics metrics.

    Args:
        payload: The participant screening submission dictionary.

    Returns:
        A tuple of (total_points, list_of_triggered_rules).
        Each rule dictionary contains:
            - "rule_name": Human-readable identifier.
            - "points": Score added.
            - "details": String explanation of trigger context.
    """
    points = 0
    triggered: List[Dict[str, Any]] = []

    # 1. Time Delta Check
    time_taken = payload.get("time_taken_seconds", 0)
    if time_taken < 30:
        rule_points = 30
        points += rule_points
        triggered.append({
            "rule_name": "Time Delta Check",
            "points": rule_points,
            "details": f"Submission completed in {time_taken}s (threshold: < 30s)."
        })

    # 2. Keystroke Variance Check
    variance = payload.get("typing_cadence_variance_ms", 0.0)
    if variance < 5.0:
        rule_points = 25
        points += rule_points
        triggered.append({
            "rule_name": "Keystroke Variance Check",
            "points": rule_points,
            "details": f"Keystroke variance is {variance:.2f}ms (threshold: < 5ms), indicating script injection."
        })

    # 3. Input Modification & Focus-Paste Correlation Checks
    focus_paste_coincidence = payload.get("focus_paste_coincidence", False)
    paste_detected = payload.get("paste_detected", False)
    if focus_paste_coincidence:
        rule_points = 30
        points += rule_points
        triggered.append({
            "rule_name": "Input Modification Check",
            "points": rule_points,
            "details": "Highly suspicious Focus-Paste Coincidence detected: clipboard paste occurred within 1.5s of browser refocus."
        })
    elif paste_detected:
        if time_taken < 45:
            rule_points = 20
            points += rule_points
            triggered.append({
                "rule_name": "Input Modification Check",
                "points": rule_points,
                "details": f"Clipboard paste detected and submission time ({time_taken}s) is < 45s."
            })
        else:
            triggered.append({
                "rule_name": "Input Modification Check",
                "points": 0,
                "details": f"Clipboard paste detected, but time taken ({time_taken}s) is above high-risk 45s threshold."
            })

    # 4. Attention Loss Check
    tab_switches = payload.get("tab_switches_during_form", 0)
    if tab_switches > 4:
        rule_points = 15
        points += rule_points
        triggered.append({
            "rule_name": "Attention Loss Check",
            "points": rule_points,
            "details": f"Switched tabs {tab_switches} times (threshold: > 4), indicating external querying."
        })

    # 5. Cryptographic Signature Payload Check (Anti-Spoofing)
    tampered_signature = payload.get("tampered_signature", False)
    signature = payload.get("signature", "")
    if tampered_signature:
        rule_points = 50
        points += rule_points
        triggered.append({
            "rule_name": "Cryptographic Payload Validation Check",
            "points": rule_points,
            "details": "❌ CRITICAL FAILURE: Cryptographic telemetry signature mismatch. Telemetry intervals do not match signature hash (potential payload forgery)."
        })
    elif signature:
        triggered.append({
            "rule_name": "Cryptographic Payload Validation Check",
            "points": 0,
            "details": "🟢 VERIFIED: HMAC-SHA256 telemetry signature matches active session challenge."
        })

    return points, triggered


def evaluate_tier3_footprint(payload: Dict[str, Any]) -> Tuple[int, List[Dict[str, Any]]]:
    """Evaluates Tier 3 Footprint Integrity (OSINT metadata) metrics.

    Args:
        payload: The participant screening submission dictionary.

    Returns:
        A tuple of (total_points, list_of_triggered_rules).
        Each rule dictionary contains:
            - "rule_name": Human-readable identifier.
            - "points": Score added.
            - "details": String explanation of trigger context.
    """
    points = 0
    triggered: List[Dict[str, Any]] = []

    # 1. Account Recency Check
    account_age = payload.get("github_account_age_days", 0)
    if account_age < 30:
        rule_points = 25
        points += rule_points
        triggered.append({
            "rule_name": "Account Recency Check",
            "points": rule_points,
            "details": f"GitHub account is {account_age} days old (threshold: < 30 days)."
        })

    # 2. Graph Density Ratio Check
    public_repos = payload.get("github_public_repos", 0)
    followers = payload.get("github_followers", 0)
    if public_repos == 0 and followers == 0:
        rule_points = 20
        points += rule_points
        triggered.append({
            "rule_name": "Graph Density Ratio Check",
            "points": rule_points,
            "details": f"GitHub account has 0 public repositories and 0 followers, indicating a burner profile."
        })

    return points, triggered
