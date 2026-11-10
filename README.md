# Nifty 200 52-week high scanner

A Streamlit dashboard that screens current Nifty 200 constituents for stocks
whose latest available session high exceeded the highest high in the previous
252 trading sessions. It also charts and tabulates each screened stock's most
recent and previous 52-week-high dates and values.

## Run locally

```bash
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

The app loads the constituent list from NSE archives and adjusted daily price
history from Yahoo Finance. Data is cached for 15 minutes; use **Refresh market
data** to request a new scan. Quotes may be delayed, and an intraday breakout
is provisional until the session closes. Stocks without at least 252 prior
trading sessions of history are excluded and counted as not screened.

## Breakout history and performance measures

The breakout history uses up to four years of downloaded daily data to find
breakout runs in the latest three calendar years. A run begins when a session's
high exceeds the highest high in the previous 252 trading sessions.
Consecutive qualifying sessions count as one run, represented by its first
date, highest run high, and number of sessions. The table shows each stock's
five most recent runs (or fewer if it had fewer than five).

Sharpe, Sortino, Treynor, and Jensen's alpha use aligned daily adjusted-close
returns for each stock and Yahoo Finance's Nifty 200 benchmark (`^CNX200`).
The annual risk-free rate defaults to 6.5% and can be changed in the sidebar.
Ratios use up to the latest three calendar years and are left blank if fewer
than 252 aligned daily returns are available. Sharpe and Sortino are
annualized; Treynor and Jensen's alpha are shown as percentages. Missing
benchmark history prevents the scan from completing, since the requested
benchmark-relative ratios cannot then be calculated.

The 30-session technical watchlist is a screen, not a price forecast. It
includes stocks within 5% of their 52-week high with positive 20- and
60-session returns and a latest close above both the 50- and 200-session
moving averages. Candidates are ranked by proximity to the 52-week high;
passing these conditions does not mean a stock will break out within 30
sessions.

This tool is for informational purposes only and is not investment advice.
