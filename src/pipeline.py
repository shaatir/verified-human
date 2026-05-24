"""Core orchestrator and risk score aggregator pipeline for Project Verified-Human.

Combines deterministic behavioral dynamics, OSINT footprints, and semantic evaluation.
"""

from typing import Dict, Any
from src.heuristics import evaluate_tier1_behavioral, evaluate_tier3_footprint
from src.semantic_agent import evaluate_trap_question, evaluate_linguistic_perplexity


def process_participant_screening(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Ingests a participant screening payload, evaluates all tiers, and assigns a routing status.

    Args:
        payload: Dictionary containing behavioral, semantic, and footprint metadata.

    Returns:
        A rich dictionary summary of the risk assessment and routing status.
    """
    participant_id = payload.get("participant_id", "unknown_id")
    name = payload.get("name", "Unknown Name")

    # Evaluate Tier 1 (Behavioral)
    t1_score, t1_rules = evaluate_tier1_behavioral(payload)

    # Evaluate Tier 2 (Semantic)
    t2_rules = []
    t2_score = 0

    trap_res = payload.get("trap_question_response", "")
    t2_trap_score, t2_trap_rule = evaluate_trap_question(trap_res)
    if t2_trap_rule:
        t2_score += t2_trap_score
        t2_rules.append(t2_trap_rule)

    other_responses = payload.get("other_responses", [])
    t2_perp_score, t2_perp_rule = evaluate_linguistic_perplexity(trap_res, other_responses)
    if t2_perp_rule:
        t2_score += t2_perp_score
        t2_rules.append(t2_perp_rule)

    # Evaluate Tier 3 (Footprint Integrity)
    t3_score, t3_rules = evaluate_tier3_footprint(payload)

    # Aggregate scores
    raw_score = t1_score + t2_score + t3_score
    cumulative_score = min(100, raw_score)

    # Routing Logic
    if cumulative_score < 30:
        status = "APPROVED"
    elif cumulative_score < 60:
        status = "FLAGGED_FOR_REVIEW"
    else:
        status = "AUTO_REJECTED"

    return {
        "participant_id": participant_id,
        "name": name,
        "raw_score": raw_score,
        "cumulative_score": cumulative_score,
        "status": status,
        "breakdown": {
            "tier1": {
                "score": t1_score,
                "triggered_rules": t1_rules
            },
            "tier2": {
                "score": t2_score,
                "triggered_rules": t2_rules
            },
            "tier3": {
                "score": t3_score,
                "triggered_rules": t3_rules
            }
        }
    }
