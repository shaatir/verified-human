"""Semantic analysis engine for evaluating Tier 2 (Semantic Analysis) criteria.

Offline-first approach utilizing natural language processing rules and structures 
to detect LLM-generated compliance, conversational bullet points, and high-probability
transition phrases with zero external dependencies.
"""

import re
from typing import Dict, Any, List, Tuple


def evaluate_trap_question(response: str) -> Tuple[int, Dict[str, Any] | None]:
    """Evaluates the trap question response to see if the participant fell for it.

    The question asks how to fix "CSS memory leaks". Since CSS stylesheet files
    do not allocate/leak heap memory (which is a JavaScript runtime/DOM concern),
    legitimate humans will flag the premise as false. Scammers or naive LLMs will
    comply and construct a fake technical explanation.

    Args:
        response: The text response to the trap question.

    Returns:
        A tuple of (points, triggered_rule_dict_or_None).
    """
    clean_res = response.lower().strip()

    # 1. Look for Refutation Indicators (indicates they recognized it is false/incorrect)
    refutation_patterns = [
        r"false premise",
        r"incorrect premise",
        r"doesn't have memory leaks",
        r"does not have memory leaks",
        r"don't think",
        r"dont think",
        r"don't believe",
        r"dont believe",
        r"can't leak",
        r"cant leak",
        r"cannot leak",
        r"no memory leak",
        r"no leak",
        r"not leak",
        r"no such thing",
        r"not possible",
        r"is a myth",
        r"misunderstanding",
        r"js/dom issue",
        r"javascript memory leaks",
        r"rendering engine bug",
        r"css is not",
        r"css doesn't",
        r"css itself doesn't",
        r"css does not"
    ]

    has_refutation = any(re.search(pat, clean_res) for pat in refutation_patterns)

    # 2. Look for Compliance Indicators (explaining how to fix the fake problem)
    compliance_patterns = [
        r"to fix css memory leaks",
        r"resolve css memory leaks",
        r"prevent css memory leaks",
        r"optimize.*selectors",
        r"inspect heap snapshots",
        r"styles.*hogging memory",
        r"clean up dynamic class",
        r"unused classes",
        r"selector complexity",
        r"dynamic class injection",
        r"degrade.*performance"
    ]

    has_compliance = any(re.search(pat, clean_res) for pat in compliance_patterns)

    # If they proceed with a structured/confident explanation without any refutation skepticism
    # Or if they specifically try to troubleshoot CSS heap memory leaks
    if has_compliance or (not has_refutation and len(clean_res.split()) > 15):
        points = 35
        return points, {
            "rule_name": "The Technical Trap",
            "points": points,
            "details": (
                "Participant accepted the premise of a fake technical problem ('CSS memory leaks') "
                "and structuralized a compliance-heavy explanation instead of refuting it."
            )
        }

    return 0, None


def evaluate_linguistic_perplexity(response: str, all_responses: List[str]) -> Tuple[int, Dict[str, Any] | None]:
    """Detects high-probability LLM transitions and excessive formatting optimization.

    Args:
        response: The trap question response.
        all_responses: A list of other responses to check context.

    Returns:
        A tuple of (points, triggered_rule_dict_or_None).
    """
    points = 15
    triggered_reasons = []

    # 1. Transitional Marker Analysis
    llm_transitional_markers = [
        r"\bfirst and foremost\b",
        r"\bin conclusion\b",
        r"\bit is crucial to note\b",
        r"\bit is important to note\b",
        r"\bfurthermore\b",
        r"\bmoreover\b",
        r"\bin summary\b",
        r"\bto summarize\b",
        r"\badditionally\b",
        r"\bconsequently\b"
    ]

    combined_text = (response + " " + " ".join(all_responses)).lower()

    matched_markers = []
    for pattern in llm_transitional_markers:
        matches = re.findall(pattern, combined_text)
        if matches:
            matched_markers.extend(matches)

    if len(matched_markers) >= 2:
        triggered_reasons.append(
            f"Found multiple high-probability LLM transitional markers: {list(set(matched_markers))}."
        )

    # 2. Markdown Bullet/Header Density Analysis (excessive structural optimization for short answers)
    bullet_patterns = [
        r"^\s*[-*+]\s+",   # Bullet lists
        r"^\s*\d+\.\s+",   # Numbered lists
        r"^\s*#+\s+"       # Headers
    ]

    lines = response.split("\n") + [line for res in all_responses for line in res.split("\n")]
    bullet_count = 0
    for line in lines:
        if any(re.match(pat, line) for pat in bullet_patterns):
            bullet_count += 1

    if bullet_count >= 3:
        triggered_reasons.append(
            f"Detected excessive structural optimization ({bullet_count} list/header items) "
            "for simple conversational answers."
        )

    if triggered_reasons:
        return points, {
            "rule_name": "Linguistic Perplexity Check",
            "points": points,
            "details": " ".join(triggered_reasons)
        }

    return 0, None
