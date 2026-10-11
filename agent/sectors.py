"""Static sector map for the screener universes (used by the heatmap; no Yahoo info calls)."""

_IN = {
    "Financials": "HDFCBANK ICICIBANK SBIN KOTAKBANK AXISBANK BAJFINANCE BAJAJFINSV INDUSINDBK SBILIFE HDFCLIFE SHRIRAMFIN CHOLAFIN",
    "IT": "TCS INFY WIPRO HCLTECH TECHM PERSISTENT",
    "Energy": "RELIANCE ONGC BPCL COALINDIA NTPC POWERGRID",
    "Consumer": "HINDUNILVR ITC NESTLEIND BRITANNIA TATACONSUM TITAN ASIANPAINT TRENT PIDILITIND",
    "Auto": "MARUTI M&M EICHERMOT HEROMOTOCO BAJAJ-AUTO TVSMOTOR",
    "Metals & Materials": "TATASTEEL JSWSTEEL HINDALCO VEDL ULTRACEMCO GRASIM",
    "Pharma & Health": "SUNPHARMA CIPLA DRREDDY DIVISLAB APOLLOHOSP",
    "Industrials & Infra": "LT ADANIENT ADANIPORTS ABB SIEMENS POLYCAB BEL HAL DLF",
    "Telecom & Services": "BHARTIARTL IRCTC INDIGO ETERNAL",
}
_US = {
    "Technology": "AAPL MSFT NVDA AVGO ORCL ADBE CRM CSCO ACN IBM QCOM TXN INTU AMD AMAT MU PANW LRCX ANET NOW PLTR SHOP",
    "Communication": "GOOGL META NFLX DIS T VZ",
    "Consumer": "AMZN TSLA COST HD WMT MCD PG KO PEP LOW BKNG UBER",
    "Financials": "BRK-B JPM V MA BAC WFC GS BLK SPGI",
    "Health": "LLY UNH JNJ ABBV MRK TMO ABT AMGN ISRG PFE",
    "Energy & Utilities": "XOM CVX COP NEE LIN",
    "Industrials": "GE CAT UNP DE",
}


def sector_map(market: str) -> dict[str, str]:
    """Return {Yahoo symbol: sector} for 'IN' (.NS suffix) or 'US'."""
    src = _IN if market == "IN" else _US
    suffix = ".NS" if market == "IN" else ""
    return {f"{s}{suffix}": sec for sec, names in src.items() for s in names.split()}
