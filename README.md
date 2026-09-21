# US Equity Screener

A Python script that builds a snapshot of the US equity market: it pulls the current S&P 500 and Russell 2000 constituent lists, downloads price and volume history for every ticker, and reduces each one to a small set of comparable statistics.

## What it computes

For each ticker, over a configurable period (default `1mo`):

| Field | Meaning |
| --- | --- |
| `current_price` | Most recent close |
| `weighted_avg_price` | Volume-weighted average close over the period |
| `avg_daily_volume` | Mean daily volume |
| `total_volume` | Total volume over the period |
| `price_high` / `price_low` | Range over the period |
| `price_change_pct` | Percent change from first to last close |
| `trading_days` | Number of sessions with data |

The volume weighting is the point. A plain average of closing prices treats a thin session and a heavy session as equal, which misstates where the shares actually traded.

## How it works

1. `get_sp500_tickers()` and `get_russell2000_tickers()` scrape the current constituent lists instead of hard-coding them, so the universe stays correct as the indices rebalance.
2. `fetch_stock_data()` downloads price and volume history in batches.
3. `_compute_stats()` reduces one ticker to the table above.
4. `build_market_dict(period)` assembles everything into a single dictionary keyed by ticker.

## Usage

```python
from market import build_market_dict

market = build_market_dict(period="3mo")
market["AAPL"]["weighted_avg_price"]
```

## Requirements

```bash
pip install yfinance pandas requests beautifulsoup4
```

## Notes

Data comes from public sources through `yfinance`, so no API key is needed. Requests are batched and paced to stay inside rate limits. This is a data-collection utility, not investment advice.
