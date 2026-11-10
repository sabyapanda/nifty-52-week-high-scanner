import unittest
from unittest.mock import patch

import pandas as pd

from scanner import analyze_history, load_constituents, screen_nifty_200


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
        self.assertIsNone(result["previous_high_date"])

    def test_returns_most_recent_date_of_52_week_high(self):
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
            result["previous_high_date"], self.history.index[25].date().isoformat()
        )

    def test_previous_high_date_is_missing_when_high_occurred_once(self):
        self.history.index = pd.date_range("2025-11-10", periods=253)
        self.history.loc[self.history.index[-1], "High"] = 101.0

        result = analyze_history(self.history)

        self.assertIsNone(result["previous_high_date"])

    def test_does_not_count_equal_or_lower_high_as_breakout(self):
        self.history.loc[252, "High"] = 100.0
        self.assertFalse(analyze_history(self.history)["is_breakout"])

        self.history.loc[252, "High"] = 99.0
        self.assertFalse(analyze_history(self.history)["is_breakout"])

    def test_requires_252_prior_sessions(self):
        self.assertIsNone(analyze_history(self.history.iloc[:252]))

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
        dates = pd.date_range("2025-11-10", periods=253)
        columns = pd.MultiIndex.from_product(
            [["AAA.NS", "BBB.NS"], ["High", "Close"]]
        )
        prices = pd.DataFrame(index=dates, columns=columns, dtype=float)
        prices.loc[:, ("AAA.NS", "High")] = 100.0
        prices.loc[:, ("AAA.NS", "Close")] = 95.0
        prices.loc[dates[-1], ("AAA.NS", "High")] = 101.0
        prices.loc[dates[:-1], ("BBB.NS", "High")] = 100.0
        prices.loc[dates[:-1], ("BBB.NS", "Close")] = 95.0
        load_constituents.return_value = members
        download_history.return_value = prices

        results, not_screened, universe_size = screen_nifty_200()

        self.assertEqual(universe_size, 2)
        self.assertEqual(not_screened, 1)
        self.assertEqual(results.iloc[0]["company"], "A Limited")
        self.assertTrue(results.iloc[0]["is_breakout"])
        self.assertEqual(results.iloc[0]["session_date"], dates[-1].date().isoformat())


if __name__ == "__main__":
    unittest.main()
