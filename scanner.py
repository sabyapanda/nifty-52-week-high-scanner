"""Data loading and 52-week-high calculations for the Nifty 200 scanner."""

from __future__ import annotations

import csv
from io import StringIO

import pandas as pd
import requests

CONSTITUENTS_URL = (
    "https://www.niftyindices.com/Index_Constituent/ind_nifty200list.csv"
)


def load_constituents() -> pd.DataFrame:
    """Load and validate the official Nifty 200 constituent list."""
    response = requests.get(
        CONSTITUENTS_URL,
        headers={"User-Agent": "Mozilla/5.0 Nifty200HighScanner/1.0"},
        timeout=20,
    )
    response.raise_for_status()
    content = response.content.decode("utf-8-sig")
    required = {"Symbol", "Company Name", "Industry"}
    header_row = next(
        (
            index
            for index, row in enumerate(csv.reader(StringIO(content)))
            if required.issubset({field.strip() for field in row})
        ),
        None,
    )
    if header_row is None:
        raise ValueError(
            "The Nifty Indices constituent file does not contain the expected "
            "CSV header."
        )
    members = pd.read_csv(
        StringIO(content),
        skiprows=header_row,
        usecols=lambda column: column.strip() in required,
    )
    members.columns = members.columns.str.strip()
    missing = required.difference(members.columns)
    if missing:
        raise ValueError(
            "The Nifty Indices constituent file is missing required columns: "
            + ", ".join(sorted(missing))
        )
    members = members[["Symbol", "Company Name", "Industry"]].copy()
    members["Symbol"] = members["Symbol"].astype("string").str.strip().str.upper()
    members["Company Name"] = (
        members["Company Name"].fillna(members["Symbol"]).astype("string").str.strip()
    )
    members["Industry"] = (
        members["Industry"].fillna("Unknown").astype("string").str.strip()
    )
    members = members.dropna(subset=["Symbol"]).drop_duplicates("Symbol")
    if members.empty:
        raise ValueError("The Nifty Indices constituent file contains no stocks.")
    return members.reset_index(drop=True)


def download_history(symbols: list[str]) -> pd.DataFrame:
    """Download two years of adjusted daily prices for Yahoo Finance symbols."""
    import yfinance as yf

    tickers = [f"{symbol}.NS" for symbol in symbols]
    prices = yf.download(
        tickers=tickers,
        period="2y",
        interval="1d",
        auto_adjust=True,
        group_by="ticker",
        progress=False,
        threads=True,
        timeout=30,
        multi_level_index=True,
    )
    if prices.empty:
        raise RuntimeError(
            "Yahoo Finance returned no price history. Please retry in a few minutes."
        )
    return prices


def history_for_symbol(prices: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    """Get one ticker's OHLC columns from yfinance's multi-ticker result."""
    if not isinstance(prices.columns, pd.MultiIndex):
        return prices if ticker in prices.columns else None
    for level in range(prices.columns.nlevels):
        if ticker in prices.columns.get_level_values(level):
            return prices.xs(ticker, axis=1, level=level, drop_level=True)
    return None


def analyze_history(history: pd.DataFrame) -> dict[str, float | bool | str] | None:
    """Measure a new high against the preceding 252 daily trading sessions."""
    if not {"High", "Close"}.issubset(history.columns):
        return None
    bars = history[["High", "Close"]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(bars) < 253:
        return None

    previous = bars.iloc[-253:-1]
    latest = bars.iloc[-1]
    prior_high = float(previous["High"].max())
    latest_high = float(latest["High"])
    close = float(latest["Close"])
    previous_close = float(bars["Close"].iloc[-2])
    if prior_high <= 0 or previous_close <= 0:
        return None

    high_52w = max(prior_high, latest_high)
    return {
        "price": close,
        "daily_change_pct": (close / previous_close - 1) * 100,
        "latest_high": latest_high,
        "prior_52w_high": prior_high,
        "high_52w": high_52w,
        "breakout_pct": (latest_high / prior_high - 1) * 100,
        "is_breakout": latest_high > prior_high,
        "session_date": pd.Timestamp(bars.index[-1]).date().isoformat(),
    }


def screen_nifty_200() -> tuple[pd.DataFrame, int, int]:
    """Screen the current Nifty 200 constituents and return results and coverage."""
    members = load_constituents()
    prices = download_history(members["Symbol"].tolist())
    results: list[dict[str, object]] = []
    not_screened = 0

    for member in members.to_dict("records"):
        ticker = f"{member['Symbol']}.NS"
        history = history_for_symbol(prices, ticker)
        metrics = analyze_history(history) if history is not None else None
        if metrics is None:
            not_screened += 1
            continue
        results.append(
            {
                "symbol": member["Symbol"],
                "company": member["Company Name"],
                "industry": member["Industry"],
                **metrics,
            }
        )

    if not results:
        raise RuntimeError(
            "No Nifty 200 stocks had enough price history to screen. "
            "Please retry later."
        )
    return pd.DataFrame(results), not_screened, len(members)
