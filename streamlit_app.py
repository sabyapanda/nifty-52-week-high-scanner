"""Streamlit dashboard for screening Nifty 200 52-week-high breakouts."""

import altair as alt
import pandas as pd
import requests
import streamlit as st

from scanner import screen_nifty_200


st.set_page_config(
    page_title="Nifty 200 52-week high scanner",
    page_icon=":material/query_stats:",
    layout="wide",
)

SCAN_CACHE_SCHEMA_VERSION = 5

@st.cache_data(ttl="15m", max_entries=2, show_spinner=False)
def load_scan(schema_version: int, annual_risk_free_rate_pct: float):
    return screen_nifty_200(annual_risk_free_rate_pct)


st.title("Nifty 200 52-week high scanner")
st.caption(
    "Find stocks whose latest available session high has moved above the "
    "previous 252 trading sessions. Historical and risk metrics use up to "
    "three years of daily data."
)

with st.sidebar:
    st.header("Screen")
    search = st.text_input(
        "Search stocks",
        placeholder="Company or symbol",
    )
    show_breakouts_only = st.toggle("Show fresh breakouts only", value=True)
    sort_by = st.selectbox(
        "Sort results by",
        options=["Breakout %", "Day change %", "Company name", "Distance to high"],
    )
    annual_risk_free_rate_pct = st.number_input(
        "Annual risk-free rate (%)",
        min_value=0.0,
        max_value=20.0,
        value=6.5,
        step=0.25,
        help="Used to calculate Sharpe, Sortino, Treynor, and Jensen's alpha.",
    )
    st.caption("Risk benchmark: Nifty 200 (^CNX200)")
    refresh = st.button("Refresh market data", icon=":material/refresh:")

if refresh:
    load_scan.clear()

try:
    with st.spinner("Loading Nifty 200 constituents and market data..."):
        results, breakout_events, not_screened, universe_size = load_scan(
            schema_version=SCAN_CACHE_SCHEMA_VERSION,
            annual_risk_free_rate_pct=annual_risk_free_rate_pct,
        )
except (requests.RequestException, RuntimeError, ValueError, pd.errors.ParserError) as exc:
    st.error(
        "The scan could not be completed. Check your internet connection and "
        f"try again. Details: {exc}",
        icon=":material/error:",
    )
    st.stop()

industries = sorted(results["industry"].dropna().unique().tolist())
with st.sidebar:
    selected_industries = st.multiselect(
        "Industry",
        options=industries,
        key="industry_filter",
    )

breakouts = results[results["is_breakout"]]
near_high = results[
    (~results["is_breakout"])
    & (results["price"] >= results["high_52w"] * 0.98)
]

with st.container(horizontal=True):
    st.metric("Stocks screened", f"{len(results)} / {universe_size}", border=True)
    st.metric("Fresh 52-week highs", len(breakouts), border=True)
    st.metric("Within 2% of high", len(near_high), border=True)
    st.metric("Not screened", not_screened, border=True)

latest_session = results["session_date"].max()
st.caption(
    f"Latest price session: {latest_session} · Data via Yahoo Finance · "
    "Quotes may be delayed; intraday breakouts are provisional until market close."
)
if not_screened:
    st.warning(
        f"{not_screened} of {universe_size} constituents could not be screened "
        "because price history was unavailable or shorter than 252 sessions."
    )

universe_filtered = results.copy()
if selected_industries:
    universe_filtered = universe_filtered[
        universe_filtered["industry"].isin(selected_industries)
    ]
if search.strip():
    query = search.strip()
    matches = universe_filtered["symbol"].str.contains(
        query, case=False, regex=False
    ) | universe_filtered["company"].str.contains(query, case=False, regex=False)
    universe_filtered = universe_filtered[matches]

filtered = universe_filtered.copy()
if show_breakouts_only:
    filtered = filtered[filtered["is_breakout"]]

sort_columns = {
    "Breakout %": ("breakout_pct", False),
    "Day change %": ("daily_change_pct", False),
    "Company name": ("company", True),
    "Distance to high": ("distance_to_high_pct", True),
}
sort_column, ascending = sort_columns[sort_by]
filtered = filtered.sort_values(sort_column, ascending=ascending)

st.subheader("Most recent 52-week high by stock")
if filtered.empty:
    st.info("No stocks match these filters.")
else:
    high_dates = filtered[
        [
            "symbol",
            "company",
            "high_52w_date",
            "prior_52w_high_date",
            "high_52w",
            "prior_52w_high",
            "is_breakout",
        ]
    ].copy()
    latest_points = high_dates[
        ["symbol", "company", "high_52w_date", "high_52w", "is_breakout"]
    ].rename(columns={"high_52w_date": "date", "high_52w": "high_value"})
    latest_points["date_type"] = "Most recent 52-week high"
    prior_points = high_dates[
        ["symbol", "company", "prior_52w_high_date", "prior_52w_high", "is_breakout"]
    ].rename(
        columns={
            "prior_52w_high_date": "date",
            "prior_52w_high": "high_value",
        }
    )
    prior_points["date_type"] = "Previous 52-week high"
    chart_dates = pd.concat([latest_points, prior_points], ignore_index=True)
    chart_dates["date"] = pd.to_datetime(chart_dates["date"], errors="coerce")
    chart_dates = chart_dates.dropna(subset=["date"])
    high_date_chart = (
        alt.Chart(chart_dates)
        .mark_circle(size=85)
        .encode(
            x=alt.X(
                "date:T",
                title="Date",
                axis=alt.Axis(format="%b %d, %Y"),
            ),
            y=alt.Y(
                "symbol:N",
                title="Stock",
                sort=alt.SortField(field="date", order="descending"),
            ),
            color=alt.Color(
                "date_type:N",
                title="High",
                scale=alt.Scale(
                    domain=[
                        "Most recent 52-week high",
                        "Previous 52-week high",
                    ],
                    range=["#60A5FA", "#FBBF24"],
                ),
            ),
            tooltip=[
                alt.Tooltip("company:N", title="Company"),
                alt.Tooltip("symbol:N", title="Symbol"),
                alt.Tooltip(
                    "date_type:N",
                    title="High date",
                ),
                alt.Tooltip(
                    "date:T",
                    title="Date",
                    format="%b %d, %Y",
                ),
                alt.Tooltip("high_value:Q", title="High value (₹)", format=",.2f"),
                alt.Tooltip("is_breakout:N", title="Fresh breakout"),
            ],
        )
        .properties(height=max(240, min(18 * len(high_dates), 1500)))
    )
    st.altair_chart(
        high_date_chart,
        alt=(
            "Dates and values of the most recent and previous 52-week highs "
            "for each filtered stock"
        ),
    )
    st.subheader("52-week high dates and values")
    date_value_table = high_dates[
        [
            "symbol",
            "company",
            "high_52w_date",
            "high_52w",
            "prior_52w_high_date",
            "prior_52w_high",
        ]
    ].copy()
    date_value_table["high_52w_date"] = pd.to_datetime(
        date_value_table["high_52w_date"]
    ).dt.strftime("%b %d, %Y")
    date_value_table["prior_52w_high_date"] = pd.to_datetime(
        date_value_table["prior_52w_high_date"]
    ).dt.strftime("%b %d, %Y")
    date_value_table = date_value_table.rename(
        columns={
            "symbol": "Symbol",
            "company": "Company",
            "high_52w_date": "Most recent high date",
            "high_52w": "Most recent 52-week high (₹)",
            "prior_52w_high_date": "Previous high date",
            "prior_52w_high": "Previous 52-week high (₹)",
        }
    )
    st.dataframe(
        date_value_table,
        hide_index=True,
        column_config={
            "Most recent 52-week high (₹)": st.column_config.NumberColumn(
                format="₹%.2f"
            ),
            "Previous 52-week high (₹)": st.column_config.NumberColumn(
                format="₹%.2f"
            ),
        },
        alt="Most recent and previous 52-week-high dates and values by stock",
    )

left, right = st.columns([3, 2])
with left:
    st.subheader("Stocks at fresh 52-week highs" if show_breakouts_only else "Screen results")
    if filtered.empty:
        st.info("No stocks match these filters.")
    else:
        display = filtered.assign(
            symbol=filtered["symbol"].map(
                lambda symbol: f"https://finance.yahoo.com/quote/{symbol}.NS/"
            )
        )
        st.dataframe(
            display[
                [
                    "symbol",
                    "company",
                    "industry",
                    "price",
                    "daily_change_pct",
                    "latest_high",
                    "prior_52w_high",
                    "prior_52w_high_date",
                    "high_52w_date",
                    "breakout_pct",
                ]
            ],
            hide_index=True,
            column_config={
                "symbol": st.column_config.LinkColumn(
                    "Symbol", display_text="finance.yahoo.com/quote/(.*?)/"
                ),
                "company": st.column_config.TextColumn("Company"),
                "industry": st.column_config.TextColumn("Industry"),
                "price": st.column_config.NumberColumn("Last close (₹)", format="₹%.2f"),
                "daily_change_pct": st.column_config.NumberColumn(
                    "Day change", format="%+.2f%%"
                ),
                "latest_high": st.column_config.NumberColumn(
                    "Session high (₹)", format="₹%.2f"
                ),
                "prior_52w_high": st.column_config.NumberColumn(
                    "Prior 52-week high (₹)", format="₹%.2f"
                ),
                "prior_52w_high_date": st.column_config.TextColumn(
                    "Prior 52-week high date"
                ),
                "high_52w_date": st.column_config.TextColumn(
                    "Most recent 52-week high date"
                ),
                "breakout_pct": st.column_config.NumberColumn(
                    "Above prior high", format="%+.2f%%"
                ),
            },
            alt="Nifty 200 stock prices and fresh 52-week-high breakouts",
        )
        st.download_button(
            "Download filtered results",
            data=filtered.to_csv(index=False).encode("utf-8"),
            file_name="nifty200_52_week_highs.csv",
            mime="text/csv",
            icon=":material/download:",
        )

with right:
    st.subheader("Breakouts by industry")
    chart_breakouts = filtered[filtered["is_breakout"]]
    if chart_breakouts.empty:
        st.info("No fresh breakouts in the latest available session.")
    else:
        industry_counts = (
            chart_breakouts.groupby("industry", as_index=False)
            .size()
            .rename(columns={"size": "Stocks"})
            .sort_values("Stocks", ascending=False)
            .set_index("industry")
        )
        st.bar_chart(
            industry_counts,
            x_label="Industry",
            y_label="Stocks",
            alt="Number of fresh 52-week-high breakouts by industry",
        )

st.subheader("Last five 52-week-high breakout runs")
st.caption(
    "A breakout run starts when a session's high exceeds the previous 252 "
    "sessions' highs. Consecutive qualifying sessions count as one run. "
    "History covers the latest three calendar years."
)
history_events = breakout_events[
    breakout_events["symbol"].isin(universe_filtered["symbol"])
].copy()
if history_events.empty:
    st.info("No 52-week-high breakout runs match these filters in the last three years.")
else:
    history_events["breakout_date"] = pd.to_datetime(
        history_events["breakout_date"]
    ).dt.strftime("%b %d, %Y")
    st.dataframe(
        history_events.rename(
            columns={
                "symbol": "Symbol",
                "company": "Company",
                "industry": "Industry",
                "breakout_date": "Breakout date",
                "breakout_high": "Run high (₹)",
                "prior_52w_high": "Previous 52-week high (₹)",
                "breakout_pct": "Above prior high (%)",
                "run_sessions": "Sessions in run",
            }
        ),
        hide_index=True,
        column_config={
            "Run high (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "Previous 52-week high (₹)": st.column_config.NumberColumn(
                format="₹%.2f"
            ),
            "Above prior high (%)": st.column_config.NumberColumn(format="%+.2f%%"),
            "Sessions in run": st.column_config.NumberColumn(format="%d"),
        },
        alt="Last five three-year 52-week-high breakout runs for each stock",
        height=420,
    )
    st.download_button(
        "Download breakout history",
        data=history_events.to_csv(index=False).encode("utf-8"),
        file_name="nifty200_three_year_breakout_history.csv",
        mime="text/csv",
        icon=":material/download:",
    )

st.subheader("Three-year risk-adjusted performance")
st.caption(
    "Annualized daily-return ratios versus Nifty 200, using the risk-free rate "
    f"of {annual_risk_free_rate_pct:.2f}% entered in the sidebar. At least 252 "
    "aligned daily returns are required; unavailable ratios are shown blank."
)
if universe_filtered.empty:
    st.info("No stocks match these filters.")
else:
    risk_table = universe_filtered[
        [
            "symbol",
            "company",
            "sharpe_ratio",
            "sortino_ratio",
            "treynor_ratio",
            "jensens_alpha_pct",
            "risk_observations",
        ]
    ].rename(
        columns={
            "symbol": "Symbol",
            "company": "Company",
            "sharpe_ratio": "Sharpe ratio",
            "sortino_ratio": "Sortino ratio",
            "treynor_ratio": "Treynor ratio (%)",
            "jensens_alpha_pct": "Jensen's alpha (%)",
            "risk_observations": "Daily observations",
        }
    )
    st.dataframe(
        risk_table,
        hide_index=True,
        column_config={
            "Sharpe ratio": st.column_config.NumberColumn(format="%.2f"),
            "Sortino ratio": st.column_config.NumberColumn(format="%.2f"),
            "Treynor ratio (%)": st.column_config.NumberColumn(format="%+.2f"),
            "Jensen's alpha (%)": st.column_config.NumberColumn(format="%+.2f%%"),
            "Daily observations": st.column_config.NumberColumn(format="%d"),
        },
        alt="Three-year annualized risk-adjusted stock performance ratios",
        height=420,
    )

st.subheader("30-session technical watchlist")
st.warning(
    "This is a rule-based research watchlist, not a forecast or personalized "
    "investment recommendation. Passing these conditions does not mean a stock "
    "will break its high in the next 30 sessions."
)
st.caption(
    "Candidates must be within 5% of their 52-week high, have positive 20- and "
    "60-session returns, and close above both their 50- and 200-session averages. "
    "Candidates are ranked by distance to their 52-week high."
)
watchlist = universe_filtered[universe_filtered["watchlist_eligible"]].sort_values(
    ["distance_to_high_pct", "return_60d_pct"],
    ascending=[True, False],
)
if watchlist.empty:
    st.info("No stocks currently meet all technical watchlist conditions.")
else:
    watchlist_table = watchlist[
        [
            "symbol",
            "company",
            "price",
            "high_52w",
            "distance_to_high_pct",
            "return_20d_pct",
            "return_60d_pct",
            "sma_50",
            "sma_200",
        ]
    ].rename(
        columns={
            "symbol": "Symbol",
            "company": "Company",
            "price": "Last close (₹)",
            "high_52w": "52-week high (₹)",
            "distance_to_high_pct": "Distance to high (%)",
            "return_20d_pct": "20-session return (%)",
            "return_60d_pct": "60-session return (%)",
            "sma_50": "50-session average (₹)",
            "sma_200": "200-session average (₹)",
        }
    )
    st.dataframe(
        watchlist_table,
        hide_index=True,
        column_config={
            "Last close (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "52-week high (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "Distance to high (%)": st.column_config.NumberColumn(format="%.2f%%"),
            "20-session return (%)": st.column_config.NumberColumn(format="%+.2f%%"),
            "60-session return (%)": st.column_config.NumberColumn(format="%+.2f%%"),
            "50-session average (₹)": st.column_config.NumberColumn(format="₹%.2f"),
            "200-session average (₹)": st.column_config.NumberColumn(
                format="₹%.2f"
            ),
        },
        alt="Stocks matching the 30-session technical watchlist screen",
    )

st.caption(
    "A breakout means the latest session's high strictly exceeded the highest "
    "high in the preceding 252 trading sessions. Market data is for information "
    "only and is not investment advice."
)
