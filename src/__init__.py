"""Verified-Human package.

Individual screening stays exact. Aggregate analytics live in ``src.analytics``
and ``src.dp`` and are differentially private. Do not feed a DP release back
into ``process_participant_screening``.
"""

from src.pipeline import process_participant_screening

__all__ = ["process_participant_screening"]
