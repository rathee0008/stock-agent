# Stock Analysis Agent

A Streamlit dashboard that analyses **India (NSE/BSE) and US** stocks by
blending **technical indicators**, **fundamental ratios** and **recent news
tone** into a single composite view, with an optional **Claude-written
briefing**, a live **TradingView** chart, and an **FII/DII** (India) /
**institutional ownership** (US) tab.

> ⚠️ **This is not investment advice.** It is automated, rule-based analysis on
> delayed public data, built for research and learning. It does not know your
> financial situation. The "projection" it shows is a volatility band derived
> from historical variance — *not* a forecast of where the price will go.
> Markets are uncertain and you can lose money. Do your own due diligence and
> consult a SEBI-registered adviser before trading.

## What it does

| Layer | Inputs | Output |
|---|---|---|
| Technical | 2y daily OHLCV | SMA/EMA, RSI, MACD, Bollinger, ATR, momentum, volume, support/resistance → score −100…+100 |
| Fundamental | Yahoo `info` | P/E, forward P/E, P/B, PEG, ROE, margins, debt/equity, current ratio, revenue & earnings growth, yield → score |
| News | Yahoo news feed | keyword-lexicon tone per headline → score |
| Composite | weighted blend (default 45 / 40 / 15) | Buy/Hold/Sell *bias*, confidence, 1w/1m/3m statistical range |
| Briefing | all of the above | Claude synthesis (Snapshot, technicals, fundamentals, news, bull/bear triggers, risks) or a rule-based template |
| Live chart | intraday bars (1m–60m) | auto-refreshing candlesticks with session VWAP, prev-close / last-price lines and coloured volume; market-state badge (NSE or US session clock) |
| TradingView | live embedded widget | interactive chart with RSI, MACD, Bollinger Bands, SMA and volume preloaded — full indicator toolbox via the widget's own UI |
| FII/DII (India) | BSE quarterly shareholding-pattern filings | Promoter / DII / FII / government / public % by quarter, stacked chart + QoQ deltas |
| Ownership (US) | Yahoo institutional/insider holders | % held by institutions & insiders, top institutional holders table |

The **🔴 Live** tab re-fetches on its own timer (`st.fragment(run_every=…)`), so
it updates without recomputing the analysis. Interval, session window (1d/5d),
refresh cadence and an on/off switch are in the sidebar. Data is still Yahoo's
~15 min delayed feed — not a real-time trading feed.

Pick the market (🇮🇳 India / 🇺🇸 United States) at the top of the sidebar —
it changes the ticker format, currency, session-hours clock, and which
ownership tab (FII/DII vs. institutional holders) is shown.

## Setup

```bash
cd ~/stock-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# optional — turns on the Claude briefing
cp .env.example .env && $EDITOR .env      # add ANTHROPIC_API_KEY
```

## Run

Dashboard:

```bash
streamlit run app.py
```

One-off from the terminal:

```bash
python cli.py RELIANCE
python cli.py TATASTEEL --no-llm
python cli.py INFY --json > infy.json
```

## Ticker format

**India:** plain NSE symbol — `RELIANCE`, `TATASTEEL`, `INFY`, `HDFCBANK`. The
agent appends `.NS`. Use `SYMBOL.BO` for BSE, `^NSEI` / `^BSESN` for indices.
Symbols do change (demergers, renames) — if one 404s, check NSE for the current
ticker.

**US:** plain ticker — `AAPL`, `MSFT`, `TSLA`, `BRK-B`. Use `^GSPC` for the
S&P 500, `^IXIC` for the Nasdaq Composite, `^DJI` for the Dow.

## TradingView chart

The **📺 TradingView** tab embeds TradingView's free, public "Advanced
Real-Time Chart" widget (loaded from `s3.tradingview.com`, no API key) with
RSI, MACD, Bollinger Bands, a moving average and volume preselected — add or
remove studies from the widget's own toolbar.

For **US** tickers this just works. For **India**, TradingView's free
embeddable widget doesn't carry NSE/BSE data unless you're signed in to
TradingView in the same browser (Indian-exchange real-time data is gated
behind a TradingView account) — the tab shows a warning and an "Open on
TradingView.com ↗" button as a reliable fallback.

## FII/DII (India) and institutional ownership (US)

**India** — the **🏦 FII/DII** tab shows the last 8 quarters of shareholding
pattern (Promoter / DII / FII / government / public %), pulled from BSE's
public shareholding-pattern API (`agent/ownership.py`) — the same JSON BSE's
own website renders from, unauthenticated. (NSE's equivalent API sits behind
Akamai bot-detection and refuses plain requests; every NSE-listed company is
also BSE-listed, so BSE covers NSE names too.) FII/DII here means:
- **FII/FPI** = BSE's "Institutions (Foreign)" total (FPI Category I & II, FDI)
- **DII** = BSE's "Institutions (Domestic)" total (mutual funds, insurers,
  banks, AIFs, pension funds)

**US** — there is no FII/DII split for US equities, so the tab is labelled
**🏦 Ownership** and shows Yahoo Finance's institutional/insider ownership
(via `yfinance`) instead: % held by institutions and insiders, plus the
largest individual institutional holders.

## Notes & limitations

- **Data source:** Yahoo Finance via `yfinance` for prices/fundamentals/news;
  BSE's public API for India shareholding pattern; TradingView's free widget
  for the live chart. Intraday is ~15 min delayed; fundamental fields are
  sometimes missing or stale for Indian names — the agent degrades gracefully
  and re-weights around missing components.
- The scoring thresholds are heuristic and deliberately conservative. Tune the
  weights in the sidebar; edit `agent/technical.py` / `agent/fundamental.py` to
  change the rules.
- The **Backtest** page tests the technical score only (Yahoo has no point-in-time
  fundamentals/news). It is survivorship-biased and cost-modelled with a flat
  per-side estimate. Treat the composite as a structured checklist, not a track record.
- News sentiment is a simple word-list heuristic, not an NLP model.
- FII/DII scrip-code lookup covers ~20 large caps directly and falls back to
  BSE's symbol search for everything else — if a name doesn't resolve, BSE may
  list it under a different short name.

## What's new (reliability, signal quality, alerts, risk)

**Data reliability** — `agent/cache.py`, `agent/fallback.py`, `agent/log.py`, `agent/config.py`
- Market-hours-aware caching: every cached page takes a `cache.bucket(market)` argument that rolls
  every 2 min while the session is open and every 3 h when it is shut.
- If Yahoo fails, price history falls back to Alpha Vantage (set `ALPHAVANTAGE_API_KEY`) then Stooq
  (US only), then the last good copy on disk (flagged *stale*).
- Every analysis shows a freshness strip (data age + source for price, fundamentals and news) and
  the sidebar has a **System status** panel listing recent failures.
- Settings are read from `st.secrets` first, then environment / `.env`.

**Composite call** — `agent/signal.py`, `agent/backtest.py`
- "What moved the call": the top signals ranked by weighted contribution.
- Confidence drops (and is capped) when technical, fundamental and news disagree.
- Backtest: trading costs, Sharpe, drawdown, index benchmark, first-half/second-half split, a
  **calibration** table (how often each score band was actually higher N days later; quoted on the
  Analyze page) and a **signal lab** (rank-IC per signal group) that can save tuned technical weights.

**Movers & Big Money** — `agent/flows.py`, `agent/why.py`
- Delivery % (NSE bhavcopy), bulk/block deals, FII/DII cash flows, and a "why it moved" column
  (volume, gap, 52-week position, sector move, deal, newest headline, optional Claude sentence).
  NSE blocks some hosts; every source degrades gracefully.

**Daily Brief, Ask, Alerts** — `agent/briefing.py`, `agent/chat.py`, `agent/alerts.py`
- Pre/post-market brief covering your watchlist and holdings; a chat page that answers from the
  app's own numbers; alert rules (price, % move, RSI, volume spike, score, composite flip) delivered
  to Telegram/email by a GitHub Actions schedule (`.github/workflows/alerts.yml`). See the Alerts page
  for the one-time setup and the list of secrets.

**Portfolio** — `agent/portfolio.py`
- Dated BUY/SELL lines, FIFO lots, realised P&L, India STCG/LTCG estimate (editable rates), 45-day
  "turns long-term" nudge, correlation, beta, historical VaR/expected shortfall, risk contributions
  and ATR position sizing. Not tax advice.

**Also**: sector drill-down + 3-month view, Compare page, Screener with saved filters (URL / JSON),
mobile layout, and `.github/workflows/keepalive.yml` (a headless browser visit; a plain HTTP ping
does not wake a sleeping Streamlit Cloud app — set the repo variable `STREAMLIT_APP_URL`).

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q                          # 30+ unit tests, no network needed
python tests/smoke_pages.py        # runs every page headless on synthetic data
```

## Project layout

```
agent/
  data.py         yfinance wrapper, ticker normalisation (India + US), fetch_live() for the live tab
  technical.py    indicators + technical score
  fundamental.py  ratio checks + fundamental score
  news.py         headline lexicon sentiment
  signal.py       weighted blend + volatility-band projection
  llm.py          Claude synthesis with template fallback
  tradingview.py  TradingView widget symbol mapping + embed HTML
  ownership.py    BSE FII/DII shareholding pattern + US institutional ownership
  analyze.py      orchestrator (+ per-signal freshness)
  cache.py        market-hours-aware cache buckets, disk stale-while-error
  fallback.py     Alpha Vantage / Stooq price fallbacks
  backtest.py     backtest engine, calibration, signal lab
  flows.py        NSE delivery %, bulk/block deals, FII/DII
  why.py          'why is it moving' tags + Claude summary
  briefing.py     daily brief
  chat.py         Ask-the-agent
  alerts.py       alert rules, Telegram/email delivery
  portfolio.py    FIFO, tax, VaR/beta, position sizing
app.py            Streamlit dashboard
cli.py            terminal runner
pages/            Top 20, Movers, Watchlist, Sector Heatmap, Portfolio, Backtest,
                  Daily Brief, Ask, Alerts, Compare, Screener
scripts/          run_alerts.py, keepalive.py
tests/            unit tests + headless page smoke test
alerts.json       alert rules (edit on the Alerts page, commit to save)
```
