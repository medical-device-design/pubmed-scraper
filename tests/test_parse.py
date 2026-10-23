"""Parser tests on a synthetic PubMed record.
Run from the repo root: python -m unittest discover -s tests"""

import unittest
import xml.etree.ElementTree as ET

from pubmed_scraper.parse import parse_article, partial_date

SAMPLE = """
<PubmedArticle>
 <MedlineCitation Status="MEDLINE" Owner="NLM">
  <PMID Version="1">31234567</PMID>
  <Article PubModel="Print-Electronic">
   <Journal>
    <ISSN IssnType="Electronic">1234-5678</ISSN>
    <JournalIssue><Volume>12</Volume><Issue>3</Issue>
     <PubDate><Year>2024</Year><Month>Mar</Month></PubDate></JournalIssue>
    <Title>Journal of Device Studies</Title>
    <ISOAbbreviation>J Device Stud</ISOAbbreviation>
   </Journal>
   <ArticleTitle>In vitro wear of a <i>titanium</i> hip cup cleared under K033394.</ArticleTitle>
   <Pagination><MedlinePgn>100-110</MedlinePgn></Pagination>
   <ELocationID EIdType="doi" ValidYN="Y">10.1000/jds.2024.001</ELocationID>
   <Abstract>
    <AbstractText Label="METHODS">Simulator testing of the P100047/S002 device (trial nct02345678; not NCT1234567).</AbstractText>
    <AbstractText Label="RESULTS">Wear was low.</AbstractText>
   </Abstract>
   <AuthorList>
    <Author><LastName>Smith</LastName><ForeName>Ana</ForeName><Initials>A</Initials>
     <Identifier Source="ORCID">https://orcid.org/0000-0002-1825-0097</Identifier>
     <AffiliationInfo><Affiliation>Hofstra University, Hempstead, NY.</Affiliation></AffiliationInfo>
    </Author>
    <Author><CollectiveName>HIP Study Group</CollectiveName></Author>
   </AuthorList>
   <Language>eng</Language>
   <GrantList><Grant><GrantID>R01 AR000000</GrantID><Agency>NIAMS NIH HHS</Agency><Country>United States</Country></Grant></GrantList>
   <PublicationTypeList><PublicationType UI="D016428">Journal Article</PublicationType></PublicationTypeList>
   <ArticleDate DateType="Electronic"><Year>2024</Year><Month>01</Month><Day>15</Day></ArticleDate>
   <DataBankList><DataBank><DataBankName>ClinicalTrials.gov</DataBankName>
    <AccessionNumberList><AccessionNumber>NCT01234567</AccessionNumber>
     <AccessionNumber>not-an-nct</AccessionNumber></AccessionNumberList></DataBank></DataBankList>
  </Article>
  <ChemicalList><Chemical><RegistryNumber>D1JT611TNE</RegistryNumber>
   <NameOfSubstance UI="D014025">Titanium</NameOfSubstance></Chemical></ChemicalList>
  <MeshHeadingList>
   <MeshHeading><DescriptorName UI="D006622" MajorTopicYN="Y">Hip Prosthesis</DescriptorName></MeshHeading>
   <MeshHeading><DescriptorName UI="D011475" MajorTopicYN="N">Prosthesis Failure</DescriptorName>
    <QualifierName UI="Q000209" MajorTopicYN="Y">etiology</QualifierName></MeshHeading>
   <MeshHeading><DescriptorName UI="D006801" MajorTopicYN="N">Humans</DescriptorName></MeshHeading>
  </MeshHeadingList>
  <KeywordList Owner="NOTNLM"><Keyword MajorTopicYN="N">wear</Keyword></KeywordList>
 </MedlineCitation>
 <PubmedData>
  <ArticleIdList><ArticleId IdType="pubmed">31234567</ArticleId>
   <ArticleId IdType="doi">10.1000/jds.2024.001</ArticleId>
   <ArticleId IdType="pmc">PMC7654321</ArticleId></ArticleIdList>
 </PubmedData>
</PubmedArticle>
"""


class ParseArticleTest(unittest.TestCase):
    def setUp(self):
        self.r = parse_article(ET.fromstring(SAMPLE))

    def test_identity_and_text(self):
        self.assertEqual(self.r["pmid"], "31234567")
        self.assertEqual(self.r["title"], "In vitro wear of a titanium hip cup cleared under K033394.")
        self.assertEqual(self.r["abstract"],
                         "METHODS: Simulator testing of the P100047/S002 device (trial nct02345678; "
                         "not NCT1234567).\nRESULTS: Wear was low.")
        self.assertEqual(self.r["doi"], "10.1000/jds.2024.001")
        self.assertEqual(self.r["pmcid"], "PMC7654321")

    def test_dates(self):
        self.assertEqual(self.r["pub_date"], "2024-03")
        self.assertEqual(self.r["pub_year"], "2024")
        self.assertEqual(self.r["article_date"], "2024-01-15")

    def test_authors(self):
        first, group = self.r["authors"]
        self.assertEqual(first["orcid"], "0000-0002-1825-0097")
        self.assertEqual(first["affiliations"], ["Hofstra University, Hempstead, NY."])
        self.assertEqual(group["collective_name"], "HIP Study Group")

    def test_mesh_major_includes_major_qualifier(self):
        major = {m["term"] for m in self.r["mesh"] if m["major"]}
        self.assertEqual(major, {"Hip Prosthesis", "Prosthesis Failure"})

    def test_links_to_trials_and_fda(self):
        self.assertEqual(self.r["nct_ids"], ["NCT01234567"])              # NLM's linked-trials list
        self.assertEqual(self.r["nct_ids_in_text"], ["NCT02345678"])      # written in the abstract
        self.assertEqual(self.r["fda_numbers"], ["K033394", "P100047"])

    def test_grants(self):
        self.assertEqual(self.r["grants"], [{"id": "R01 AR000000", "agency": "NIAMS NIH HHS",
                                             "country": "United States"}])

    def test_partial_date_fallback(self):
        el = ET.fromstring("<PubDate><MedlineDate>2019 Jan-Feb</MedlineDate></PubDate>")
        self.assertEqual(partial_date(el), "2019")


if __name__ == "__main__":
    unittest.main()
