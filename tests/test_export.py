"""End-to-end test of parse + export on saved batch files: streaming, PMID
de-duplication across batches, and the output tables.
Run from the repo root: python -m unittest discover -s tests"""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from pubmed_scraper.export import export
from pubmed_scraper.parse import iter_run


def article(pmid, title, major_mesh="Hip Prosthesis", abstract=True):
    abstract_xml = "<Abstract><AbstractText>Text.</AbstractText></Abstract>" if abstract else ""
    return f"""
<PubmedArticle><MedlineCitation Status="MEDLINE"><PMID>{pmid}</PMID>
 <Article><Journal><JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue>
  <Title>J</Title></Journal><ArticleTitle>{title}</ArticleTitle>{abstract_xml}
  <AuthorList><Author><LastName>Lee</LastName><ForeName>Kim</ForeName></Author>
   <Author><LastName>Diaz</LastName><Initials>M</Initials></Author></AuthorList>
  <PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
 </Article>
 <MeshHeadingList><MeshHeading><DescriptorName UI="D006622" MajorTopicYN="Y">{major_mesh}</DescriptorName></MeshHeading>
  <MeshHeading><DescriptorName UI="D006801" MajorTopicYN="N">Humans</DescriptorName></MeshHeading></MeshHeadingList>
</MedlineCitation></PubmedArticle>"""


class ExportTest(unittest.TestCase):
    def test_streaming_parse_and_export(self):
        with tempfile.TemporaryDirectory() as d:
            run = Path(d) / "raw"
            run.mkdir()
            (run / "efetch-00001.xml").write_text(
                "<PubmedArticleSet>" + article("1", "First") + article("2", "Second", abstract=False)
                + "<PubmedBookArticle><BookDocument><PMID>9</PMID></BookDocument></PubmedBookArticle>"
                + "</PubmedArticleSet>", encoding="utf-8")
            (run / "efetch-00002.xml").write_text(          # PMID 2 again: must be dropped
                "<PubmedArticleSet>" + article("2", "Second again") + article("3", "Third, with \"quotes\"")
                + "</PubmedArticleSet>", encoding="utf-8")

            stats = {}
            out = Path(d) / "out"
            summary = export(iter_run(run, stats), out, "in_vitro", {"query": "q"}, stats)

            self.assertEqual(summary["records"], 3)
            self.assertEqual(summary["duplicates_skipped"], 1)
            self.assertEqual(summary["book_articles_skipped"], 1)
            self.assertEqual(summary["with_abstract"], 2)
            self.assertEqual(summary["source_manifest"], {"query": "q"})

            lines = (out / "papers.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual([json.loads(l)["pmid"] for l in lines], ["1", "2", "3"])
            self.assertEqual(json.loads(lines[1])["title"], "Second")      # first copy kept

            with open(out / "papers.csv", encoding="utf-8-sig", newline="") as f:
                papers = list(csv.DictReader(f))
            self.assertEqual(papers[2]["title"], 'Third, with "quotes"')
            self.assertEqual(papers[0]["major_mesh"], "Hip Prosthesis")
            self.assertEqual(papers[0]["first_author"], "Kim Lee")

            with open(out / "authors.csv", encoding="utf-8-sig", newline="") as f:
                authors = list(csv.DictReader(f))
            self.assertEqual(len(authors), 6)
            self.assertEqual(authors[1]["name"], "M Diaz")

            with open(out / "mesh.csv", encoding="utf-8-sig", newline="") as f:
                self.assertEqual(len(list(csv.DictReader(f))), 6)


if __name__ == "__main__":
    unittest.main()
