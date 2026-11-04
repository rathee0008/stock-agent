"""Indian-market stock analysis agent.

Combines technical indicators, fundamental ratios and recent news into a
single composite view, with an optional Claude-written synthesis.

This package produces *analysis*, not investment advice. See README.
"""

from . import net as _net

_net.install()  # cap yfinance threads before any module calls yf.download

from .analyze import analyze_stock  # noqa: E402

__all__ = ["analyze_stock"]
