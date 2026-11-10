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

SCAN_CACHE_SCHEMA_VERSION = 4

@st.cache_data(ttl="15m", max_entries=2, show_spinner=False)
def load_scan(schema_version: int):
    return screen_nifty_200()


st.title("Nifty 200 52-week high scanner")
st.caption(
    "Find stocks whose latest available session high has moved above the "
    "previous 252 trading sessions."
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
        options=["Breakout %", "Day change %", "Company name"],
    )
    refresh = st.button("Refresh market data", icon=":material/refresh:")

if refresh:
    load_scan.clear()

try:
    with st.spinner("Loading Nifty 200 constituents and market data..."):
        results, not_screened, universe_size = load_scan(
            schema_version=SCAN_CACHE_SCHEMA_VERSION
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

filtered = results.copy()
if show_breakouts_only:
    filtered = filtered[filtered["is_breakout"]]
if selected_industries:
    filtered = filtered[filtered["industry"].isin(selected_industries)]
if search.strip():
    query = search.strip()
    matches = filtered["symbol"].str.contains(query, case=False, regex=False) | filtered[
        "company"
    ].str.contains(query, case=False, regex=False)
    filtered = filtered[matches]

sort_columns = {
    "Breakout %": ("breakout_pct", False),
    "Day change %": ("daily_change_pct", False),
    "Company name": ("company", True),
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

st.caption(
    "A breakout means the latest session's high strictly exceeded the highest "
    "high in the preceding 252 trading sessions. Market data is for information "
    "only and is not investment advice."
)
