"""Tests for PubTator3 annotations: parsing the real BioC JSON shape,
downloading with resume, and merging runs. No network.
Run from the repo root: python -m unittest discover -s tests"""

import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from pubmed_scraper import pubtator as P


def ann(ident, etype, text, name=None, valid=True, db="ncbi_mesh"):
    inf = {"identifier": ident, "type": etype, "valid": valid}
    if valid:
        inf.update(database=db, name=name)
    return {"infons": inf, "text": text, "locations": [{"offset": 0, "length": len(text)}]}


def doc(pmid, title_anns=(), abstract_anns=(), relations=()):
    """A document in the shape PubTator3's biocjson export returns."""
    return {"_id": f"{pmid}|None", "id": pmid, "pmid": int(pmid), "pmcid": None,
            "passages": [{"infons": {"type": "title"}, "text": "t", "annotations": list(title_anns),
                          "relations": []},
                         {"infons": {"type": "abstract"}, "text": "a", "annotations": list(abstract_anns),
                          "relations": []}],
            "relations": list(relations)}


TITANIUM = ann("MESH:D014025", "Chemical", "titanium", "Titanium")
HUMAN = ann("9606", "Species", "patients", "9606", db="ncbi_taxonomy")
GELMA = ann("-", "Chemical", "GelMA", valid=False)
REL = {"id": "R1", "infons": {"score": "0.9669", "type": "Association",
       "role1": {"identifier": "MESH:D014025", "type": "Chemical", "name": "Titanium"},
       "role2": {"identifier": "MESH:D010024", "type": "Disease", "name": "Osteoporosis"}}}


class ParseDocTest(unittest.TestCase):
    def test_entities_are_aggregated_per_paper(self):
        pmid, ents, rels = P.parse_doc(doc("42", [TITANIUM], [ann("MESH:D014025", "Chemical", "Ti", "Titanium"),
                                                              TITANIUM, HUMAN, HUMAN, GELMA], [REL]))
        self.assertEqual(pmid, "42")
        by = {(e["entity_type"], e["identifier"]): e for e in ents}
        ti = by[("Chemical", "MESH:D014025")]
        self.assertEqual((ti["name"], ti["mention_count"], ti["in_title"]), ("Titanium", 3, True))
        self.assertEqual(ti["mentions"], ["Ti", "titanium"])
        sp = by[("Species", "9606")]
        self.assertEqual((sp["name"], sp["database"], sp["in_title"]), ("patients", "ncbi_taxonomy", False))
        loose = by[("Chemical", None)]
        self.assertEqual((loose["name"], loose["is_normalized"]), ("GelMA", False))
        self.assertEqual(len(ents), 3)
        self.assertEqual(rels, [{"pmid": "42", "relation_type": "Association", "score": 0.9669,
                                 "entity1_type": "Chemical", "entity1_id": "MESH:D014025",
                                 "entity1_name": "Titanium", "entity2_type": "Disease",
                                 "entity2_id": "MESH:D010024", "entity2_name": "Osteoporosis"}])

    def test_paper_with_no_annotations(self):
        self.assertEqual(P.parse_doc(doc("7")), ("7", [], []))


class FakePubTator:
    """Knows the PMIDs in `known`; counts requests."""

    def __init__(self, known):
        self.known = set(known)
        self.requests = 0

    def export(self, pmids):
        self.requests += 1
        docs = [doc(p, [TITANIUM]) for p in pmids if p in self.known]
        return "https://example/pubtator", json.dumps({"PubTator3": docs}).encode()


class AnnotateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name) / "20260101-000000"
        self.run.mkdir()
        self.pmids = [str(i) for i in range(1, 251)]                      # 3 batches of <=100
        (self.run / "pmids.txt").write_text("\n".join(self.pmids) + "\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_download_counts_missing_and_resumes(self):
        # an interrupted earlier attempt left batch 1 complete and batch 2 cut off
        out = self.run / "pubtator"
        out.mkdir()
        (out / "batch-00001.json").write_text(json.dumps({"PubTator3": [doc(p) for p in self.pmids[:100]]}))
        (out / "batch-00002.json").write_text('{"PubTator3": [{"id"')

        client = FakePubTator(self.pmids[:240])                          # newest 10 not indexed yet
        P.annotate(self.run, client=client, log=lambda *_: None)
        self.assertEqual(client.requests, 2)                              # batch 1 reused
        m = json.loads((out / "manifest.json").read_text())
        self.assertEqual(m["papers_returned"], 240)
        self.assertEqual(m["pmids_not_in_pubtator"], self.pmids[240:])
        self.assertEqual([f["reused"] for f in m["files"]], [True, False, False])

        P.annotate(self.run, client=client, log=lambda *_: None)          # finished: skipped
        self.assertEqual(client.requests, 2)
        P.annotate(self.run, client=client, force=True, log=lambda *_: None)
        self.assertEqual(client.requests, 5)

    def test_batch_pubtator_knows_nothing_about(self):
        def http_400(url):
            raise urllib.error.HTTPError(url, 400, "Bad Request", {},
                                         io.BytesIO(b'{"detail":"Could not retrieve publications"}'))
        client = P.PubTator()
        with mock.patch.object(client.http, "open", side_effect=http_400):
            _, body = client.export(["99999999999"])
        self.assertEqual(json.loads(body), {"PubTator3": []})

    def test_other_errors_are_not_hidden(self):
        def http_400(url):
            raise urllib.error.HTTPError(url, 400, "Bad Request", {}, io.BytesIO(b'["too long"]'))
        client = P.PubTator()
        with mock.patch.object(client.http, "open", side_effect=http_400), \
                self.assertRaises(urllib.error.HTTPError):
            client.export(["1"])
        with self.assertRaises(ValueError):
            client.export(self.pmids[:101])


class IterAnnotationsTest(unittest.TestCase):
    def test_newest_run_wins_and_unannotated_runs_are_listed(self):
        with tempfile.TemporaryDirectory() as d:
            full, upd1, upd2 = (Path(d) / n for n in ("20260101-000000", "20260201-000000", "20260301-000000"))
            # PMID 5 was missing in the full run and is annotated by the update; 6 stays missing
            for run, docs, missing in ((full, [doc("1"), doc("2")], ["5", "6"]),
                                       (upd1, [doc("1", [TITANIUM]), doc("5")], ["6"])):
                (run / "pubtator").mkdir(parents=True)
                (run / "pubtator" / "batch-00001.json").write_text(json.dumps({"PubTator3": docs}))
                (run / "pubtator" / "manifest.json").write_text(json.dumps({"pmids_not_in_pubtator": missing}))
            upd2.mkdir()
            stats = {}
            got = {pmid: ents for pmid, ents, _ in P.iter_annotations([full, upd1, upd2], stats)}
        self.assertEqual(sorted(got), ["1", "2", "5"])
        self.assertEqual(len(got["1"]), 1)                                # update's annotation, not the full run's
        self.assertEqual(stats["papers_annotated"], 3)
        self.assertEqual(stats["pmids_not_in_pubtator"], 1)               # only 6, counted once
        self.assertEqual(stats["runs_not_annotated"], [upd2.name])


if __name__ == "__main__":
    unittest.main()
