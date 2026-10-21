"""Tests for fetching: the date-window splitting that gets past ESearch's
10,000-ID cap, and full / sample / update runs. No network: a fake client
stands in for NCBI.
Run from the repo root: python -m unittest discover -s tests"""

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from pubmed_scraper import fetch as F
from pubmed_scraper.config import Topic
from pubmed_scraper.runs import chain, read_manifest

QUIET = lambda *_: None  # noqa: E731


def _d(s):
    return date(int(s[:4]), int(s[5:7]), int(s[8:10]))


class FakeClient:
    """A tiny PubMed: records are (pmid, publication date, modification date)."""

    email = "test@example.edu"

    def __init__(self, records):
        self.records = records
        self.efetched = []

    def _match(self, mindate, maxdate, datetype):
        if not mindate:
            return [r[0] for r in self.records]
        lo, hi = _d(mindate), _d(maxdate)
        col = {"pdat": 1, "mdat": 2}[datetype]
        return [r[0] for r in self.records if lo <= r[col] <= hi]

    def esearch_count(self, term, mindate=None, maxdate=None, datetype="pdat"):
        return len(self._match(mindate, maxdate, datetype))

    def esearch_ids(self, term, retmax, sort=None, mindate=None, maxdate=None, datetype="pdat"):
        ids = self._match(mindate, maxdate, datetype)
        if mindate:
            assert len(ids) <= retmax, "a window exceeded the ESearch cap"
        return ids[:retmax]

    def efetch_xml(self, pmids):
        self.efetched += pmids
        body = "".join(f"<PubmedArticle><MedlineCitation><PMID>{p}</PMID></MedlineCitation></PubmedArticle>"
                       for p in pmids)
        return "https://example/efetch", f"<PubmedArticleSet>{body}</PubmedArticleSet>".encode()


def spread(n, start, days, first_pmid=1, mdat=None):
    """n records with publication dates spread over `days` days from start."""
    return [(str(first_pmid + i), start + timedelta(days=i % days), mdat or start + timedelta(days=i % days))
            for i in range(n)]


class DateWindowTest(unittest.TestCase):
    def test_every_window_fits_under_the_cap_and_nothing_is_lost(self):
        client = FakeClient(spread(95, date(2019, 1, 1), 900))
        with mock.patch.object(F, "ESEARCH_CAP", 10):
            wins = list(F.date_windows(client, "q", date(1800, 1, 1), date(2030, 12, 31)))
            self.assertGreater(len(wins), 9)
            for lo, hi in wins:
                self.assertLessEqual(client.esearch_count("q", lo, hi), 10)
            for (_, hi), (lo, _) in zip(wins, wins[1:]):             # contiguous, no overlap
                self.assertLess(_d(hi), _d(lo))
            pmids = F.collect_pmids(client, "q", date(1800, 1, 1), date(2030, 12, 31), log=QUIET)
        self.assertEqual(sorted(pmids, key=int), [str(i) for i in range(1, 96)])

    def test_single_day_over_the_cap_is_an_error_not_a_silent_truncation(self):
        client = FakeClient(spread(11, date(2020, 5, 5), 1))
        with mock.patch.object(F, "ESEARCH_CAP", 10), self.assertRaises(RuntimeError):
            list(F.date_windows(client, "q", date(2000, 1, 1), date(2025, 1, 1)))

    def test_empty_query_yields_no_windows(self):
        self.assertEqual(list(F.date_windows(FakeClient([]), "q", date(2000, 1, 1), date(2025, 1, 1))), [])


class FetchModesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.topic = Topic("t", "T", "x", "(dev) AND (x)")

    def tearDown(self):
        self.tmp.cleanup()

    def run_fetch(self, client, **kw):
        with mock.patch.object(F, "ESEARCH_CAP", 10):
            return F.fetch(self.topic, data_dir=self.data, client=client, batch_size=7, log=QUIET, **kw)

    def test_full_then_update(self):
        old = spread(25, date(2015, 1, 1), 300, mdat=date(2020, 1, 1))
        client = FakeClient(old)
        full = self.run_fetch(client)
        m = read_manifest(full)
        self.assertEqual((m["mode"], m["pmids_requested"], m["records_returned"]), ("full", 25, 25))
        self.assertEqual(len(m["files"]), 4)                                  # 25 in batches of 7

        # Next run: 3 brand-new papers, and paper 5 re-indexed (modified) recently.
        recent = date.today()
        client = FakeClient(old[:4] + [(old[4][0], old[4][1], recent)] + old[5:]
                            + spread(3, recent, 1, first_pmid=100))
        later = datetime.now(timezone.utc) + timedelta(seconds=2)            # a later start time
        with mock.patch("pubmed_scraper.fetch.datetime") as dt:
            dt.now.return_value = later
            update = self.run_fetch(client, update=True)
        u = read_manifest(update)
        self.assertEqual(u["mode"], "update")
        self.assertEqual(u["datetype"], "mdat")
        self.assertEqual(u["base_run"], full.name)
        self.assertEqual(u["since"], (date.fromisoformat(m["started_at"][:10]) - timedelta(days=1)).isoformat())
        self.assertEqual(sorted(client.efetched, key=int), ["5", "100", "101", "102"])
        self.assertEqual(chain(update), [full, update])

    def test_update_needs_a_full_run(self):
        self.run_fetch(FakeClient(spread(5, date(2020, 1, 1), 5)), limit=3)     # a sample is not a base
        with self.assertRaises(SystemExit):
            self.run_fetch(FakeClient([]), update=True)

    def test_update_refuses_when_the_query_changed(self):
        self.run_fetch(FakeClient(spread(5, date(2020, 1, 1), 5)))
        self.topic = Topic("t", "T", "y", "(dev) AND (y)")
        with self.assertRaises(SystemExit):
            self.run_fetch(FakeClient([]), update=True)

    def test_auto_chooses_full_then_update_then_full_after_a_query_change(self):
        client = FakeClient(spread(5, date(2020, 1, 1), 5))
        first = read_manifest(self.run_fetch(client, auto=True))
        self.assertEqual(first["mode"], "full")                               # nothing to build on yet

        later = datetime.now(timezone.utc) + timedelta(seconds=2)
        with mock.patch("pubmed_scraper.fetch.datetime") as dt:
            dt.now.return_value = later
            second = read_manifest(self.run_fetch(client, auto=True))
        self.assertEqual(second["mode"], "update")

        self.topic = Topic("t", "T", "y", "(dev) AND (y)")
        with mock.patch("pubmed_scraper.fetch.datetime") as dt:
            dt.now.return_value = later + timedelta(seconds=2)
            third = read_manifest(self.run_fetch(client, auto=True))
        self.assertEqual(third["mode"], "full")                               # query changed

        with self.assertRaises(SystemExit):
            self.run_fetch(client, auto=True, update=True)

    def test_sample(self):
        run = self.run_fetch(FakeClient(spread(8, date(2020, 1, 1), 8)), limit=3)
        m = read_manifest(run)
        self.assertEqual((m["mode"], m["sample_limit"]), ("sample", 3))
        self.assertEqual(json.loads((run / "manifest.json").read_text())["pmids_requested"], 3)


if __name__ == "__main__":
    unittest.main()
