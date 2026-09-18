"""TradingView "Advanced Real-Time Chart" widget embed.

This is TradingView's free, public embed (loaded from ``s3.tradingview.com``,
no API key) — a live, interactive chart with the full indicator toolbox
(RSI, MACD, Bollinger Bands, moving averages, and everything else in
TradingView's own studies picker). We just preselect a useful default set;
the user can add/remove indicators from the widget's own toolbar.
"""

from __future__ import annotations

import json

_INDEX_SYMBOLS_IN = {
    "^NSEI": "NSE:NIFTY",
    "^BSESN": "BSE:SENSEX",
    "^NSEBANK": "NSE:CNXBANK",
}

_DEFAULT_STUDIES = [
    "RSI@tv-basicstudies",
    "MACD@tv-basicstudies",
    "BB@tv-basicstudies",
    "MASimple@tv-basicstudies",
    "Volume@tv-basicstudies",
]


def tv_symbol(ticker: str, market: str) -> str:
    """Map our internal (Yahoo-style) ticker to a TradingView symbol."""
    if market == "US":
        return ticker[1:] if ticker.startswith("^") else ticker
    if ticker in _INDEX_SYMBOLS_IN:
        return _INDEX_SYMBOLS_IN[ticker]
    if ticker.startswith("^"):
        return ticker[1:]
    if ticker.endswith(".BO"):
        return f"BSE:{ticker[:-3]}"
    base = ticker[:-3] if ticker.endswith(".NS") else ticker
    return f"NSE:{base}"


def widget_html(
    symbol: str,
    theme: str = "dark",
    height: int = 620,
    interval: str = "D",
    studies: list[str] | None = None,
) -> str:
    """Return a self-contained HTML snippet for ``st.components.v1.html``."""
    container = "tv_" + "".join(c if c.isalnum() else "_" for c in symbol)
    config = {
        "autosize": True,
        "symbol": symbol,
        "interval": interval,
        "timezone": "Etc/UTC",
        "theme": theme,
        "style": "1",
        "locale": "en",
        "toolbar_bg": "#131722" if theme == "dark" else "#f1f3f6",
        "enable_publishing": False,
        "hide_side_toolbar": False,
        "allow_symbol_change": True,
        "studies": studies if studies is not None else _DEFAULT_STUDIES,
        "support_host": "https://www.tradingview.com",
        "container_id": container,
    }
    bg = "#131722" if theme == "dark" else "#ffffff"
    return f"""
    <div class="tradingview-widget-container" style="height:{height}px;width:100%;background:{bg};">
      <div id="{container}" style="height:100%;width:100%;"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
        new TradingView.widget({json.dumps(config)});
      </script>
    </div>
    """
