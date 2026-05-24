"""Semantic analysis engine for evaluating Tier 2 (Semantic Analysis) criteria.

Offline-first approach utilizing natural language processing rules and structures 
to detect LLM-generated compliance, conversational bullet points, and high-probability
transition phrases with zero external dependencies.
"""

import re
from typing import Dict, Any, List, Tuple


def evaluate_trap_question(response: str, category: str = "developer") -> Tuple[int, Dict[str, Any] | None]:
    """Evaluates the trap question response using context-aware negation-proximity matching.

    Determines if the participant fell for the physically impossible premise of the
    trap question (compliance) or successfully refuted it (refutation).

    Args:
        response: The text response to the trap question.
        category: The form category ("developer", "speaker", or "habits").

    Returns:
        A tuple of (points, triggered_rule_dict_or_None).
    """
    clean_res = response.lower().strip()
    word_count = len(clean_res.split())

    # Category-specific advanced negation proximity regex configurations
    refutation_regexes = []
    compliance_regexes = []

    if category == "developer":
        refutation_regexes = [
            # E.g. "css doesn't leak memory" or "no css memory leaks"
            r"\b(no|not|fake|impossible|doesn't|does not|don't|dont|can't|cant|cannot|myth|misunderstanding|issue|bug|logic|declarative)\b.{0,40}\b(leak|leaks|memory|heap|selector)\b",
            r"\b(js/dom issue|rendering engine|browser layout|css itself does not|no such thing)\b"
        ]
        compliance_regexes = [
            r"\b(fix|resolve|prevent|troubleshoot|inspect)\b.{0,40}\b(css memory leak|leak|heap|selector)\b",
            r"\b(heap snapshot|selectors|optimize selectors|unused classes|selector complexity|dynamic class)\b"
        ]
    elif category == "speaker":
        refutation_regexes = [
            # E.g. "no projector on a speaker" or "cannot watch movies on it"
            r"\b(no|not|fake|impossible|doesn't|does not|don't|dont|can't|cant|cannot|myth|misunderstanding|issue|bug|only)\b.{0,40}\b(projector|hologram|holographic|screen|movie|movies)\b",
            r"\b(only plays audio|just a speaker|no screen|not a projector|doesn't project|only plays music)\b"
        ]
        compliance_regexes = [
            r"\b(liked|loved|enjoyed|watched|visual|crystal|clarity|cinematic|immersive|projected)\b.{0,40}\b(projector|hologram|holographic|screen|movie|movies)\b",
            r"\b(watched movies|wall projector|holographic projector|hologram on my wall)\b"
        ]
    elif category == "habits":
        refutation_regexes = [
            # E.g. "phones cannot smell food" or "no smell settings exist"
            r"\b(no|not|fake|impossible|doesn't|does not|don't|dont|can't|cant|cannot|myth|misunderstanding|issue|bug|joke)\b.{0,40}\b(smell|scent|odor|aroma|smell-o-vision)\b",
            r"\b(phones can't smell|cannot smell food|doesn't emit scent|doesn't exist|not a real feature|can't smell photos)\b"
        ]
        compliance_regexes = [
            r"\b(loved|liked|enjoyed|smelled|scent|aroma|olfactory|sensory|delicious|pizza|cookies)\b.{0,40}\b(smell|scent|odor|aroma|smell-o-vision)\b",
            r"\b(smell the photos|aroma settings|scent transmission|smell food)\b"
        ]

    # Evaluate matches using case-insensitive advanced regex proximity checking
    has_refutation = any(re.search(pat, clean_res, re.IGNORECASE) for pat in refutation_regexes)
    has_compliance = any(re.search(pat, clean_res, re.IGNORECASE) for pat in compliance_regexes)

    # Trigger rule if they comply or write a substantial response (>15 words) with zero skepticism
    if has_compliance or (not has_refutation and word_count > 15):
        points = 35
        return points, {
            "rule_name": "The Technical Trap",
            "points": points,
            "details": (
                f"Participant accepted the physically impossible premise of the trap question "
                f"({category} loadout) and structuralized a compliant explanation instead of refuting it."
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
