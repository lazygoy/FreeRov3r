"""Compatibility import for passive CAN timing analysis.

New code should import from ``freerov3r.can_research``.
"""
from ..can_research.timing import analyze_message_periodicity

__all__ = ["analyze_message_periodicity"]
