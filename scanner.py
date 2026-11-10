"""Market data loading and Nifty 200 breakout analytics."""

from __future__ import annotations

import csv
from io import StringIO

import numpy as np
import pandas as pd
import requests

CONSTITUENTS_URL = "https://archives.nseindia.com/content/indices/ind_nifty200list.csv"
BENCHMARK_TICKER = "^CNX200"
TRADING_DAYS_PER_YEAR = 252
HISTORY_YEARS = 4
ANALYSIS_YEARS = 3


def load_constituents() -> pd.DataFrame:
    """Load and validate the official Nifty 200 constituent list."""
    response = requests.get(
        CONSTITUENTS_URL,
        headers={
            "User-Agent": "Mozilla/5.0 Nifty200HighScanner/1.0",
            "Accept": "text/csv,*/*",
            "Referer": "https://www.nseindia.com/",
        },
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
    """Download four years of adjusted daily prices, including the benchmark."""
    import yfinance as yf

    start = (pd.Timestamp.today().normalize() - pd.DateOffset(years=HISTORY_YEARS))
    tickers = [f"{symbol}.NS" for symbol in symbols] + [BENCHMARK_TICKER]
    prices = yf.download(
        tickers=tickers,
        start=start.date().isoformat(),
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


def _price_bars(history: pd.DataFrame) -> pd.DataFrame:
    if not {"High", "Close"}.issubset(history.columns):
        return pd.DataFrame(columns=["High", "Close"], dtype=float)
    return (
        history[["High", "Close"]]
        .apply(pd.to_numeric, errors="coerce")
        .dropna()
        .sort_index()
    )


def _date_label(date: object) -> str:
    return pd.Timestamp(date).date().isoformat()


def detect_breakout_runs(
    history: pd.DataFrame,
    symbol: str,
    company: str,
    industry: str,
    analysis_start: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Find 52-week-high sessions and collapse consecutive sessions into runs."""
    bars = _price_bars(history)
    columns = [
        "symbol",
        "company",
        "industry",
        "breakout_date",
        "breakout_high",
        "prior_52w_high",
        "breakout_pct",
        "run_sessions",
    ]
    if len(bars) < TRADING_DAYS_PER_YEAR + 1:
        return pd.DataFrame(columns=columns)

    prior_high = bars["High"].rolling(
        TRADING_DAYS_PER_YEAR, min_periods=TRADING_DAYS_PER_YEAR
    ).max().shift(1)
    breached = (bars["High"] > prior_high).fillna(False)
    run_ids = breached.ne(breached.shift(fill_value=False)).cumsum()
    events: list[dict[str, object]] = []
    for run_id, run in bars.loc[breached].groupby(run_ids[breached]):
        del run_id
        start_date = run.index[0]
        if analysis_start is not None and pd.Timestamp(start_date) < analysis_start:
            continue
        reference_high = float(prior_high.loc[start_date])
        run_high = float(run["High"].max())
        events.append(
            {
                "symbol": symbol,
                "company": company,
                "industry": industry,
                "breakout_date": _date_label(start_date),
                "breakout_high": run_high,
                "prior_52w_high": reference_high,
                "breakout_pct": (run_high / reference_high - 1) * 100,
                "run_sessions": len(run),
            }
        )
    return pd.DataFrame(events, columns=columns)


def calculate_risk_metrics(
    stock_history: pd.DataFrame,
    benchmark_history: pd.DataFrame,
    annual_risk_free_rate_pct: float,
) -> dict[str, float | int]:
    """Calculate annualized Sharpe, Sortino, Treynor, and Jensen's alpha."""
    stock = _price_bars(stock_history)["Close"].pct_change().rename("stock")
    market = _price_bars(benchmark_history)["Close"].pct_change().rename("market")
    latest = stock.index.max()
    start = latest - pd.DateOffset(years=ANALYSIS_YEARS)
    returns = pd.concat([stock, market], axis=1, join="inner").dropna()
    returns = returns.loc[returns.index >= start]
    observations = len(returns)
    missing: dict[str, float | int] = {
        "sharpe_ratio": float("nan"),
        "sortino_ratio": float("nan"),
        "treynor_ratio": float("nan"),
        "jensens_alpha_pct": float("nan"),
        "risk_observations": observations,
    }
    if observations < TRADING_DAYS_PER_YEAR:
        return missing

    risk_free_daily = (1 + annual_risk_free_rate_pct / 100) ** (
        1 / TRADING_DAYS_PER_YEAR
    ) - 1
    stock_returns = returns["stock"]
    market_returns = returns["market"]
    excess = stock_returns - risk_free_daily
    market_excess = market_returns - risk_free_daily
    stock_std = float(excess.std(ddof=1))
    downside_deviation = float(np.sqrt(np.square(np.minimum(excess, 0)).mean()))
    market_variance = float(market_returns.var(ddof=1))
    beta = (
        float(stock_returns.cov(market_returns) / market_variance)
        if market_variance > 0
        else float("nan")
    )
    annual_excess_return = float(excess.mean() * TRADING_DAYS_PER_YEAR)

    return {
        "sharpe_ratio": (
            float(excess.mean() / stock_std * np.sqrt(TRADING_DAYS_PER_YEAR))
            if stock_std > 0
            else float("nan")
        ),
        "sortino_ratio": (
            float(excess.mean() / downside_deviation * np.sqrt(TRADING_DAYS_PER_YEAR))
            if downside_deviation > 0
            else float("nan")
        ),
        "treynor_ratio": (
            float(annual_excess_return / beta * 100)
            if np.isfinite(beta) and beta != 0
            else float("nan")
        ),
        "jensens_alpha_pct": (
            float(
                (
                    excess.mean()
                    - beta * market_excess.mean()
                )
                * TRADING_DAYS_PER_YEAR
                * 100
            )
            if np.isfinite(beta)
            else float("nan")
        ),
        "risk_observations": observations,
    }


def analyze_history(
    history: pd.DataFrame,
) -> dict[str, float | bool | str | None] | None:
    """Summarize current high, trend, and 30-session watchlist indicators."""
    bars = _price_bars(history)
    if len(bars) < TRADING_DAYS_PER_YEAR + 1:
        return None

    previous = bars.iloc[-TRADING_DAYS_PER_YEAR - 1 : -1]
    latest = bars.iloc[-1]
    prior_high = float(previous["High"].max())
    latest_high = float(latest["High"])
    close = float(latest["Close"])
    previous_close = float(bars["Close"].iloc[-2])
    if prior_high <= 0 or previous_close <= 0:
        return None

    window = bars.iloc[-TRADING_DAYS_PER_YEAR:]
    high_52w = float(window["High"].max())
    high_dates = window.index[window["High"] == high_52w]
    prior_high_dates = previous.index[previous["High"] == prior_high]
    sma_50 = float(bars["Close"].tail(50).mean())
    sma_200 = float(bars["Close"].tail(200).mean())
    return_20d = float(close / bars["Close"].iloc[-21] - 1) if len(bars) >= 21 else float("nan")
    return_60d = float(close / bars["Close"].iloc[-61] - 1) if len(bars) >= 61 else float("nan")
    distance_to_high_pct = (close / high_52w - 1) * 100
    watchlist_eligible = (
        close >= high_52w * 0.95
        and return_20d > 0
        and return_60d > 0
        and close > sma_50
        and close > sma_200
    )

    return {
        "price": close,
        "daily_change_pct": (close / previous_close - 1) * 100,
        "latest_high": latest_high,
        "prior_52w_high": prior_high,
        "prior_52w_high_date": _date_label(prior_high_dates[-1]),
        "high_52w": high_52w,
        "high_52w_date": _date_label(high_dates[-1]),
        "breakout_pct": (latest_high / prior_high - 1) * 100,
        "is_breakout": latest_high > prior_high,
        "session_date": _date_label(bars.index[-1]),
        "return_20d_pct": return_20d * 100,
        "return_60d_pct": return_60d * 100,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "distance_to_high_pct": distance_to_high_pct,
        "watchlist_eligible": watchlist_eligible,
    }


def screen_nifty_200(
    annual_risk_free_rate_pct: float = 6.5,
) -> tuple[pd.DataFrame, pd.DataFrame, int, int]:
    """Screen constituents, history, ratios, and technical watchlist."""
    members = load_constituents()
    prices = download_history(members["Symbol"].tolist())
    benchmark = history_for_symbol(prices, BENCHMARK_TICKER)
    if benchmark is None or _price_bars(benchmark).empty:
        raise RuntimeError(
            f"Yahoo Finance returned no {BENCHMARK_TICKER} benchmark history; "
            "risk ratios cannot be calculated."
        )

    results: list[dict[str, object]] = []
    event_frames: list[pd.DataFrame] = []
    not_screened = 0
    benchmark_bars = _price_bars(benchmark)
    analysis_start = benchmark_bars.index[-1] - pd.DateOffset(years=ANALYSIS_YEARS)

    for member in members.to_dict("records"):
        symbol = str(member["Symbol"])
        company = str(member["Company Name"])
        industry = str(member["Industry"])
        history = history_for_symbol(prices, f"{symbol}.NS")
        metrics = analyze_history(history) if history is not None else None
        if metrics is None:
            not_screened += 1
            continue
        risk_metrics = calculate_risk_metrics(
            history, benchmark, annual_risk_free_rate_pct
        )
        results.append(
            {
                "symbol": symbol,
                "company": company,
                "industry": industry,
                **metrics,
                **risk_metrics,
            }
        )

        events = detect_breakout_runs(
            history,
            symbol,
            company,
            industry,
            analysis_start=analysis_start,
        )
        if not events.empty:
            event_frames.append(events)

    if not results:
        raise RuntimeError(
            "No Nifty 200 stocks had enough price history to screen. "
            "Please retry later."
        )

    if event_frames:
        events = pd.concat(event_frames, ignore_index=True)
        events = (
            events.sort_values(["symbol", "breakout_date"])
            .groupby("symbol", group_keys=False)
            .tail(5)
            .sort_values(["breakout_date", "symbol"], ascending=[False, True])
            .reset_index(drop=True)
        )
    else:
        events = pd.DataFrame(
            columns=[
                "symbol",
                "company",
                "industry",
                "breakout_date",
                "breakout_high",
                "prior_52w_high",
                "breakout_pct",
                "run_sessions",
            ]
        )
    return pd.DataFrame(results), events, not_screened, len(members)
