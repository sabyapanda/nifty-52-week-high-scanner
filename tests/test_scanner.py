import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scanner import (
    analyze_history,
    calculate_risk_metrics,
    detect_breakout_runs,
    load_constituents,
    screen_nifty_200,
)


class AnalyzeHistoryTests(unittest.TestCase):
    def setUp(self):
        self.history = pd.DataFrame(
            {"High": [100.0] * 253, "Close": [95.0] * 253}
        )

    def test_detects_new_high_against_previous_252_sessions(self):
        self.history.index = pd.date_range("2025-11-10", periods=253)
        self.history.loc[self.history.index[-1], ["High", "Close"]] = [101.0, 100.0]

        result = analyze_history(self.history)

        self.assertIsNotNone(result)
        self.assertTrue(result["is_breakout"])
        self.assertAlmostEqual(result["breakout_pct"], 1.0)
        self.assertEqual(result["session_date"], "2026-07-20")
        self.assertEqual(result["high_52w_date"], "2026-07-20")
        self.assertEqual(result["prior_52w_high_date"], "2026-07-19")
        self.assertEqual(result["prior_52w_high"], 100.0)

    def test_returns_latest_date_of_tied_highs_and_prior_high_details(self):
        self.history.index = pd.date_range("2025-11-10", periods=253)
        self.history.loc[self.history.index[25], "High"] = 105.0
        self.history.loc[self.history.index[240], "High"] = 105.0
        self.history.loc[self.history.index[-1], "High"] = 99.0

        result = analyze_history(self.history)

        self.assertFalse(result["is_breakout"])
        self.assertEqual(
            result["high_52w_date"], self.history.index[240].date().isoformat()
        )
        self.assertEqual(
            result["prior_52w_high_date"], self.history.index[240].date().isoformat()
        )
        self.assertEqual(result["high_52w"], 105.0)
        self.assertEqual(result["prior_52w_high"], 105.0)

    def test_does_not_count_equal_or_lower_high_as_breakout(self):
        self.history.loc[252, "High"] = 100.0
        self.assertFalse(analyze_history(self.history)["is_breakout"])

        self.history.loc[252, "High"] = 99.0
        self.assertFalse(analyze_history(self.history)["is_breakout"])

    def test_requires_252_prior_sessions(self):
        self.assertIsNone(analyze_history(self.history.iloc[:252]))

    def test_collapses_consecutive_breakout_days_into_runs(self):
        dates = pd.bdate_range("2023-01-02", periods=260)
        history = pd.DataFrame(
            {"High": [100.0] * len(dates), "Close": [95.0] * len(dates)},
            index=dates,
        )
        history.loc[dates[252:255], "High"] = [101.0, 102.0, 103.0]
        history.loc[dates[255], "High"] = 99.0
        history.loc[dates[256], "High"] = 104.0

        runs = detect_breakout_runs(
            history, "TEST", "Test Limited", "Technology"
        )

        self.assertEqual(len(runs), 2)
        self.assertEqual(runs.iloc[0]["breakout_date"], dates[252].date().isoformat())
        self.assertEqual(runs.iloc[0]["breakout_high"], 103.0)
        self.assertEqual(runs.iloc[0]["run_sessions"], 3)
        self.assertEqual(runs.iloc[1]["breakout_date"], dates[256].date().isoformat())

    def test_calculates_three_year_risk_adjusted_ratios(self):
        dates = pd.bdate_range("2023-01-02", periods=800)
        market_returns = np.resize(
            np.array([-0.012, -0.004, 0.002, 0.006, 0.011]), len(dates)
        )
        risk_free_daily = (1 + 6.5 / 100) ** (1 / 252) - 1
        stock_returns = (
            risk_free_daily + 1.2 * (market_returns - risk_free_daily) + 0.0002
        )
        market_close = 100 * np.cumprod(1 + market_returns)
        stock_close = 100 * np.cumprod(1 + stock_returns)
        market = pd.DataFrame(
            {"High": market_close * 1.01, "Close": market_close}, index=dates
        )
        stock = pd.DataFrame(
            {"High": stock_close * 1.01, "Close": stock_close}, index=dates
        )

        ratios = calculate_risk_metrics(stock, market, 6.5)

        self.assertGreaterEqual(ratios["risk_observations"], 750)
        self.assertLessEqual(ratios["risk_observations"], 800)
        for name in (
            "sharpe_ratio",
            "sortino_ratio",
            "treynor_ratio",
            "jensens_alpha_pct",
        ):
            self.assertTrue(pd.notna(ratios[name]), name)
        self.assertAlmostEqual(ratios["jensens_alpha_pct"], 5.04, places=1)

    def test_risk_metrics_require_at_least_one_year_of_returns(self):
        dates = pd.bdate_range("2025-01-02", periods=200)
        history = pd.DataFrame(
            {"High": np.arange(200) + 101, "Close": np.arange(200) + 100},
            index=dates,
        )

        ratios = calculate_risk_metrics(history, history, 6.5)

        self.assertEqual(ratios["risk_observations"], 199)
        self.assertTrue(pd.isna(ratios["sharpe_ratio"]))

    @patch("scanner.requests.get")
    def test_loads_constituents_after_metadata_rows(self, get):
        response = get.return_value
        response.content = (
            b"Index,Name,Value\n"
            b"Nifty,200,Constituents\n"
            b"Generated,2026-11-10,\n"
            b"Source,Nifty Indices,\n"
            b"Metadata,ignored,\n"
            b"Metadata,ignored,\n"
            b"Metadata,ignored,\n"
            b"Company Name,Industry,Symbol,Series,ISIN Code\n"
            b"Alpha Limited,Technology,ALPHA,EQ,INE000A01000\n"
            b"Beta Limited,Finance,BETA,EQ,INE000B01000\n"
        )

        members = load_constituents()

        self.assertEqual(members["Symbol"].tolist(), ["ALPHA", "BETA"])
        self.assertEqual(members["Company Name"].tolist(), ["Alpha Limited", "Beta Limited"])

    @patch("scanner.download_history")
    @patch("scanner.load_constituents")
    def test_screens_symbols_and_reports_unavailable_history(
        self, load_constituents, download_history
    ):
        members = pd.DataFrame(
            {
                "Symbol": ["AAA", "BBB"],
                "Company Name": ["A Limited", "B Limited"],
                "Industry": ["Technology", "Finance"],
            }
        )
        dates = pd.date_range("2025-11-10", periods=270)
        columns = pd.MultiIndex.from_product(
            [["AAA.NS", "BBB.NS", "^CNX200"], ["High", "Close"]]
        )
        prices = pd.DataFrame(index=dates, columns=columns, dtype=float)
        prices.loc[:, ("AAA.NS", "High")] = 100.0
        prices.loc[:, ("AAA.NS", "Close")] = 95.0
        prices.loc[dates[252::2], ("AAA.NS", "High")] = np.arange(
            101.0, 119.0, 2.0
        )
        prices.loc[dates[252::2], ("AAA.NS", "Close")] = 95.0
        prices.loc[:, ("^CNX200", "High")] = 100.0
        prices.loc[:, ("^CNX200", "Close")] = np.linspace(95.0, 100.0, len(dates))
        prices.loc[dates[:252], ("BBB.NS", "High")] = 100.0
        prices.loc[dates[:252], ("BBB.NS", "Close")] = 95.0
        load_constituents.return_value = members
        download_history.return_value = prices

        results, events, not_screened, universe_size = screen_nifty_200()

        self.assertEqual(universe_size, 2)
        self.assertEqual(not_screened, 1)
        self.assertEqual(results.iloc[0]["company"], "A Limited")
        self.assertFalse(results.iloc[0]["is_breakout"])
        self.assertEqual(results.iloc[0]["session_date"], dates[-1].date().isoformat())
        self.assertEqual(len(events), 5)
        self.assertEqual(
            results.iloc[0]["prior_52w_high_date"], dates[-2].date().isoformat()
        )
        self.assertEqual(results.iloc[0]["prior_52w_high"], 117.0)


if __name__ == "__main__":
    unittest.main()
