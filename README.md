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

This tool is for informational purposes only and is not investment advice.
