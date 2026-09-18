"""Indian-market stock analysis agent.

Combines technical indicators, fundamental ratios and recent news into a
single composite view, with an optional Claude-written synthesis.

This package produces *analysis*, not investment advice. See README.
"""

from .analyze import analyze_stock

__all__ = ["analyze_stock"]
