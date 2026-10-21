"""End-to-end test of parse + export on saved batch files: streaming, PMID
de-duplication, merging a full run with an update, and the output tables.
Run from the repo root: python -m unittest discover -s tests"""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from pubmed_scraper.export import export
from pubmed_scraper.parse import iter_run, iter_runs


def article(pmid, title, major_mesh="Hip Prosthesis", abstract=True, grant=False):
    abstract_xml = "<Abstract><AbstractText>Text.</AbstractText></Abstract>" if abstract else ""
    grant_xml = ("<GrantList><Grant><GrantID>R01 AR000001</GrantID><Agency>NIAMS NIH HHS</Agency>"
                 "<Country>United States</Country></Grant><Grant><Agency>Hofstra</Agency></Grant></GrantList>"
                 if grant else "")
    return f"""
<PubmedArticle><MedlineCitation Status="MEDLINE"><PMID>{pmid}</PMID>
 <Article><Journal><JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue>
  <Title>J</Title></Journal><ArticleTitle>{title}</ArticleTitle>{abstract_xml}
  <AuthorList><Author><LastName>Lee</LastName><ForeName>Kim</ForeName></Author>
   <Author><LastName>Diaz</LastName><Initials>M</Initials></Author></AuthorList>
  {grant_xml}
  <PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
 </Article>
 <MeshHeadingList><MeshHeading><DescriptorName UI="D006622" MajorTopicYN="Y">{major_mesh}</DescriptorName></MeshHeading>
  <MeshHeading><DescriptorName UI="D006801" MajorTopicYN="N">Humans</DescriptorName></MeshHeading></MeshHeadingList>
</MedlineCitation></PubmedArticle>"""


def write_batch(run, n, *articles):
    run.mkdir(parents=True, exist_ok=True)
    (run / f"efetch-{n:05d}.xml").write_text(
        "<PubmedArticleSet>" + "".join(articles) + "</PubmedArticleSet>", encoding="utf-8")


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class ExportTest(unittest.TestCase):
    def test_streaming_parse_and_export(self):
        with tempfile.TemporaryDirectory() as d:
            run = Path(d) / "raw"
            write_batch(run, 1, article("1", "First", grant=True), article("2", "Second", abstract=False),
                        "<PubmedBookArticle><BookDocument><PMID>9</PMID></BookDocument></PubmedBookArticle>")
            write_batch(run, 2, article("2", "Second again"), article("3", 'Third, with "quotes"'))

            stats = {}
            out = Path(d) / "out"
            summary = export(iter_run(run, stats), out, "in_vitro", [{"run": "raw", "query": "q"}], stats)

            self.assertEqual(summary["records"], 3)
            self.assertEqual(summary["duplicates_skipped"], 1)
            self.assertEqual(summary["book_articles_skipped"], 1)
            self.assertEqual(summary["with_abstract"], 2)
            self.assertEqual(summary["with_grant"], 1)
            self.assertEqual(summary["runs"], ["raw"])
            self.assertNotIn("pubtator", summary)
            self.assertFalse((out / "entities.csv").exists())

            lines = (out / "papers.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual([json.loads(l)["pmid"] for l in lines], ["1", "2", "3"])
            self.assertEqual(json.loads(lines[1])["title"], "Second")      # first copy kept

            papers = read_csv(out / "papers.csv")
            self.assertEqual(papers[2]["title"], 'Third, with "quotes"')
            self.assertEqual(papers[0]["major_mesh"], "Hip Prosthesis")
            self.assertEqual(papers[0]["first_author"], "Kim Lee")
            self.assertEqual(papers[0]["grant_count"], "2")

            authors = read_csv(out / "authors.csv")
            self.assertEqual(len(authors), 6)
            self.assertEqual(authors[1]["name"], "M Diaz")

            self.assertEqual(len(read_csv(out / "mesh.csv")), 6)

            grants = read_csv(out / "grants.csv")
            self.assertEqual([(g["pmid"], g["grant_id"], g["agency"]) for g in grants],
                             [("1", "R01 AR000001", "NIAMS NIH HHS"), ("1", "", "Hofstra")])

    def test_update_run_overrides_the_full_run(self):
        with tempfile.TemporaryDirectory() as d:
            full = Path(d) / "20260101-000000"
            update = Path(d) / "20260201-000000"
            write_batch(full, 1, article("1", "Old title"), article("2", "Unchanged"))
            write_batch(update, 1, article("1", "Corrected title", major_mesh="Knee Prosthesis"),
                        article("3", "New paper"))

            stats = {}
            recs = list(iter_runs([full, update], stats))       # order given doesn't matter
            by_pmid = {r["pmid"]: r for r in recs}
            self.assertEqual(sorted(by_pmid), ["1", "2", "3"])
            self.assertEqual(by_pmid["1"]["title"], "Corrected title")
            self.assertEqual(by_pmid["1"]["source_run"], update.name)
            self.assertEqual(by_pmid["2"]["source_run"], full.name)
            self.assertEqual(stats["duplicates_skipped"], 1)

    def test_annotation_tables(self):
        entity = {"pmid": "1", "entity_type": "Chemical", "identifier": "MESH:D014025",
                  "database": "ncbi_mesh", "name": "Titanium", "mention_count": 3, "in_title": True,
                  "is_normalized": True, "mentions": ["Ti", "titanium"]}
        loose = {**entity, "identifier": None, "database": None, "name": "GelMA", "mention_count": 1,
                 "in_title": False, "is_normalized": False, "mentions": ["GelMA"]}
        relation = {"pmid": "1", "relation_type": "Association", "score": 0.97,
                    "entity1_type": "Chemical", "entity1_id": "MESH:D014025", "entity1_name": "Titanium",
                    "entity2_type": "Disease", "entity2_id": "MESH:D010024", "entity2_name": "Osteoporosis"}
        with tempfile.TemporaryDirectory() as d:
            run = Path(d) / "raw"
            write_batch(run, 1, article("1", "Ti implants"))
            out = Path(d) / "out"
            ann_stats = {"papers_annotated": 1}
            stats = {}
            s = export(iter_run(run, stats), out, "in_vitro", [{"run": "raw"}], stats,
                       annotations=iter([("1", [entity, loose], [relation])]), ann_stats=ann_stats)
            self.assertEqual(s["pubtator"], {"papers_annotated": 1, "entity_rows": 2,
                                             "normalized_entity_rows": 1, "relation_rows": 1})
            ents = read_csv(out / "entities.csv")
            self.assertEqual(ents[0]["mentions"], "Ti; titanium")
            self.assertEqual(ents[1]["is_normalized"], "False")
            self.assertEqual(read_csv(out / "relations.csv")[0]["entity2_name"], "Osteoporosis")

            # re-parsing without annotations removes the now-stale tables
            stats = {}
            export(iter_run(run, stats), out, "in_vitro", [{"run": "raw"}], stats)
            self.assertFalse((out / "entities.csv").exists())


if __name__ == "__main__":
    unittest.main()
