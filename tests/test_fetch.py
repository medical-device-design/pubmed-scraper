"""Tests for the date-window splitting that gets past ESearch's 10,000-ID cap.
No network: a fake client stands in for NCBI.
Run from the repo root: python -m unittest discover -s tests"""

import unittest

from pubmed_scraper import fetch as F


class FakeClient:
    """Pretends PubMed holds `per_year[y]` papers in year y, spread evenly
    over 12 months, with PMIDs that encode their year and month."""

    def __init__(self, per_year):
        self.per_year = per_year

    def _months(self, lo, hi):
        y0, m0 = int(lo[:4]), int(lo[5:7])
        y1, m1 = int(hi[:4]), int(hi[5:7])
        for y in range(y0, y1 + 1):
            for m in range(m0 if y == y0 else 1, (m1 if y == y1 else 12) + 1):
                yield y, m

    def _ids(self, lo, hi):
        for y, m in self._months(lo, hi):
            n = self.per_year.get(y, 0) // 12
            for i in range(n):
                yield f"{y}{m:02d}{i:05d}"

    def esearch_count(self, term, mindate=None, maxdate=None):
        return sum(1 for _ in self._ids(mindate, maxdate))

    def esearch_ids(self, term, retmax, sort=None, mindate=None, maxdate=None):
        ids = list(self._ids(mindate, maxdate))
        assert len(ids) <= retmax, "a window exceeded the ESearch cap"
        return ids


class DateWindowTest(unittest.TestCase):
    def test_every_window_fits_under_the_cap_and_nothing_is_lost(self):
        # 2019: 6,000 papers, 2020: 13,200 (needs a month split), 2021: 4,800
        client = FakeClient({2019: 6000, 2020: 13200, 2021: 4800})
        wins = list(F.date_windows(client, "q", 2018, 2022, log=lambda *_: None))
        for lo, hi in wins:
            self.assertLessEqual(client.esearch_count("q", lo, hi), F.ESEARCH_CAP)
        self.assertIn(("2020/02/01", "2020/02/29"), wins)           # leap year handled
        self.assertIn(("2020/12/01", "2020/12/31"), wins)

        pmids = []
        for lo, hi in wins:
            pmids += client.esearch_ids("q", F.ESEARCH_CAP, mindate=lo, maxdate=hi)
        self.assertEqual(len(pmids), 6000 + 13200 + 4800)
        self.assertEqual(len(set(pmids)), len(pmids))               # no overlap between windows

    def test_month_over_the_cap_is_an_error_not_a_silent_truncation(self):
        client = FakeClient({2020: 12 * 10_500})
        with self.assertRaises(RuntimeError):
            list(F.date_windows(client, "q", 2020, 2020, log=lambda *_: None))

    def test_empty_query_yields_no_windows(self):
        self.assertEqual(list(F.date_windows(FakeClient({}), "q", 2000, 2025)), [])


if __name__ == "__main__":
    unittest.main()
