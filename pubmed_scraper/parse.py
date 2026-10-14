"""Parse saved PubMed XML (from `fetch`) into plain Python records. Offline only.

One record per PubmedArticle. Book chapters (PubmedBookArticle) are skipped
and counted, since they carry a different structure and rarely matter here.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# FDA submission numbers: 510(k) K######, De Novo DEN######, PMA P###### (with
# optional /S### supplement, which is dropped). These are the hooks into the
# FDA records already in the medical-device-kg graph.
_FDA_NUMBER = re.compile(r"(?<![A-Za-z0-9])(DEN\d{6}|K\d{6}|P\d{6})(?![0-9])", re.IGNORECASE)


def text_of(el):
    """All text inside an element (titles and abstracts contain <i>, <sup>,
    etc.), with whitespace collapsed. None if empty or missing."""
    if el is None:
        return None
    s = " ".join("".join(el.itertext()).split())
    return s or None


def _month(value):
    if not value:
        return None
    v = value.strip().lower()
    if v.isdigit() and 1 <= int(v) <= 12:
        return int(v)
    return _MONTHS.get(v[:3])


def partial_date(el):
    """ISO date with only the parts PubMed actually has: '2024', '2024-03' or
    '2024-03-05'. Falls back to the year of a free-text MedlineDate."""
    if el is None:
        return None
    year = (el.findtext("Year") or "").strip()
    if not year:
        md = (el.findtext("MedlineDate") or "").strip()
        return md[:4] if md[:4].isdigit() else None
    month = _month(el.findtext("Month"))
    day = (el.findtext("Day") or "").strip()
    if month and day.isdigit():
        return f"{year}-{month:02d}-{int(day):02d}"
    if month:
        return f"{year}-{month:02d}"
    return year


def fda_numbers(*texts):
    found = set()
    for t in texts:
        if t:
            found.update(m.group(1).upper() for m in _FDA_NUMBER.finditer(t))
    return sorted(found)


def parse_article(art):
    mc = art.find("MedlineCitation")
    a = mc.find("Article")
    pmid = (mc.findtext("PMID") or "").strip()

    sections = []
    for t in a.findall("Abstract/AbstractText"):
        body = text_of(t)
        if body:
            label = t.get("Label")
            sections.append(f"{label}: {body}" if label else body)
    abstract = "\n".join(sections) or None
    title = text_of(a.find("ArticleTitle")) or text_of(a.find("VernacularTitle"))

    ids = {i.get("IdType"): (i.text or "").strip()
           for i in art.findall("PubmedData/ArticleIdList/ArticleId")}
    doi = ids.get("doi") or next(
        ((e.text or "").strip() for e in a.findall("ELocationID")
         if e.get("EIdType") == "doi" and e.get("ValidYN", "Y") == "Y"), None)

    authors = []
    for au in a.findall("AuthorList/Author"):
        orcid = None
        for ident in au.findall("Identifier"):
            if (ident.get("Source") or "").upper() == "ORCID" and ident.text:
                orcid = ident.text.strip().rstrip("/").split("/")[-1]
        authors.append({
            "last_name": au.findtext("LastName"),
            "fore_name": au.findtext("ForeName"),
            "initials": au.findtext("Initials"),
            "collective_name": text_of(au.find("CollectiveName")),
            "orcid": orcid,
            "affiliations": [text_of(x) for x in au.findall("AffiliationInfo/Affiliation")
                             if text_of(x)],
        })

    mesh = []
    for mh in mc.findall("MeshHeadingList/MeshHeading"):
        d = mh.find("DescriptorName")
        if d is None:
            continue
        quals = [{"ui": q.get("UI"), "term": text_of(q), "major": q.get("MajorTopicYN") == "Y"}
                 for q in mh.findall("QualifierName")]
        mesh.append({
            "ui": d.get("UI"),
            "term": text_of(d),
            # major topic either on the descriptor itself or via a qualifier
            "major": d.get("MajorTopicYN") == "Y" or any(q["major"] for q in quals),
            "qualifiers": quals,
        })

    pub_types = [text_of(p) for p in a.findall("PublicationTypeList/PublicationType")]
    retracted = "Retracted Publication" in pub_types or any(
        c.get("RefType") == "RetractionIn"
        for c in mc.findall("CommentsCorrectionsList/CommentsCorrections"))

    databanks = []
    for db in mc.findall("DataBankList/DataBank"):
        databanks.append({
            "name": (db.findtext("DataBankName") or "").strip(),
            "accessions": [(x.text or "").strip()
                           for x in db.findall("AccessionNumberList/AccessionNumber")],
        })
    nct_ids = sorted({acc.upper() for d in databanks if d["name"] == "ClinicalTrials.gov"
                      for acc in d["accessions"] if re.fullmatch(r"NCT\d{8}", acc, re.I)})

    pub_date = partial_date(a.find("Journal/JournalIssue/PubDate"))
    article_date = next((partial_date(d) for d in a.findall("ArticleDate")
                         if d.get("DateType") == "Electronic"), None)

    return {
        "pmid": pmid,
        "title": title,
        "abstract": abstract,
        "journal": a.findtext("Journal/Title"),
        "journal_iso": a.findtext("Journal/ISOAbbreviation"),
        "issn": a.findtext("Journal/ISSN"),
        "volume": a.findtext("Journal/JournalIssue/Volume"),
        "issue": a.findtext("Journal/JournalIssue/Issue"),
        "pages": a.findtext("Pagination/MedlinePgn"),
        "pub_date": pub_date,
        "pub_year": pub_date[:4] if pub_date else (article_date or "")[:4] or None,
        "article_date": article_date,
        "doi": doi,
        "pmcid": ids.get("pmc"),
        "languages": [x.text for x in a.findall("Language") if x.text],
        "publication_types": pub_types,
        "is_retracted": retracted,
        "citation_status": mc.get("Status"),
        "authors": authors,
        "mesh": mesh,
        "chemicals": [{"ui": c.find("NameOfSubstance").get("UI"),
                       "name": text_of(c.find("NameOfSubstance")),
                       "registry_number": c.findtext("RegistryNumber")}
                      for c in mc.findall("ChemicalList/Chemical")
                      if c.find("NameOfSubstance") is not None],
        "keywords": [text_of(k) for k in mc.findall("KeywordList/Keyword") if text_of(k)],
        "grants": [{"id": g.findtext("GrantID"), "agency": g.findtext("Agency"),
                    "country": g.findtext("Country")} for g in a.findall("GrantList/Grant")],
        "databanks": databanks,
        "nct_ids": nct_ids,
        "fda_numbers": fda_numbers(title, abstract),
    }


def iter_run(run_dir, stats):
    """Yield the records of a fetch run one at a time, de-duplicated by PMID.

    Only one batch file is in memory at a time, so a run of any size parses in
    constant memory. `stats` (a dict) is filled in as records are read."""
    stats.setdefault("records", 0)
    stats.setdefault("duplicates_skipped", 0)
    stats.setdefault("book_articles_skipped", 0)
    seen = set()
    for path in sorted(Path(run_dir).glob("efetch-*.xml")):
        root = ET.parse(path).getroot()
        stats["book_articles_skipped"] += sum(1 for _ in root.iter("PubmedBookArticle"))
        for art in root.iter("PubmedArticle"):
            rec = parse_article(art)
            if not rec["pmid"] or rec["pmid"] in seen:
                stats["duplicates_skipped"] += 1
                continue
            seen.add(rec["pmid"])
            rec["source_file"] = path.name
            stats["records"] += 1
            yield rec
        del root
