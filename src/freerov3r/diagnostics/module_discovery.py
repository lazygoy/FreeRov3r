"""Compatibility imports for passive CAN network discovery.

New code should import from ``freerov3r.can_research``.
"""
from ..can_research.discovery import compare_module_discovery, discover_modules

__all__ = ["compare_module_discovery", "discover_modules"]
