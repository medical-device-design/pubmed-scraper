"""Write parsed records as a dataset: one JSONL with everything, plus flat CSV
tables shaped for knowledge-graph loading (one row per node or edge).

    data/processed/<topic>/<run>/
        papers.jsonl     full nested record per paper
        papers.csv       one row per paper
        authors.csv      one row per (paper, author)
        mesh.csv         one row per (paper, MeSH descriptor)
        summary.json     counts, and the manifest of the raw run it came from

CSVs are UTF-8 with a byte-order mark so Excel opens them correctly.
"""

import csv
import json
from pathlib import Path

_J = "; "   # separator for multi-valued cells in papers.csv


def _write_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def author_name(au):
    if au.get("collective_name"):
        return au["collective_name"]
    parts = [au.get("fore_name") or au.get("initials"), au.get("last_name")]
    return " ".join(p for p in parts if p) or None


def export(records, out_dir, topic, manifest, stats):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    with open(out / "papers.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps({"topic": topic, **r}, ensure_ascii=False) + "\n")

    _write_csv(out / "papers.csv", [
        "pmid", "topic", "title", "pub_year", "pub_date", "journal", "doi", "pmcid",
        "publication_types", "major_mesh", "keywords", "has_abstract", "is_retracted",
        "nct_ids", "fda_numbers", "author_count", "first_author",
    ], ({
        "pmid": r["pmid"],
        "topic": topic,
        "title": r["title"],
        "pub_year": r["pub_year"],
        "pub_date": r["pub_date"],
        "journal": r["journal"],
        "doi": r["doi"],
        "pmcid": r["pmcid"],
        "publication_types": _J.join(filter(None, r["publication_types"])),
        "major_mesh": _J.join(m["term"] for m in r["mesh"] if m["major"] and m["term"]),
        "keywords": _J.join(r["keywords"]),
        "has_abstract": bool(r["abstract"]),
        "is_retracted": r["is_retracted"],
        "nct_ids": _J.join(r["nct_ids"]),
        "fda_numbers": _J.join(r["fda_numbers"]),
        "author_count": len(r["authors"]),
        "first_author": author_name(r["authors"][0]) if r["authors"] else None,
    } for r in records))

    _write_csv(out / "authors.csv", [
        "pmid", "position", "name", "last_name", "fore_name", "orcid", "affiliation",
    ], ({
        "pmid": r["pmid"],
        "position": i,
        "name": author_name(au),
        "last_name": au["last_name"],
        "fore_name": au["fore_name"],
        "orcid": au["orcid"],
        "affiliation": _J.join(au["affiliations"]),
    } for r in records for i, au in enumerate(r["authors"], 1)))

    _write_csv(out / "mesh.csv", [
        "pmid", "mesh_ui", "mesh_term", "major_topic", "qualifiers",
    ], ({
        "pmid": r["pmid"],
        "mesh_ui": m["ui"],
        "mesh_term": m["term"],
        "major_topic": m["major"],
        "qualifiers": _J.join(q["term"] for q in m["qualifiers"] if q["term"]),
    } for r in records for m in r["mesh"]))

    summary = {
        **stats,
        "with_abstract": sum(1 for r in records if r["abstract"]),
        "with_doi": sum(1 for r in records if r["doi"]),
        "in_pmc": sum(1 for r in records if r["pmcid"]),
        "with_nct_id": sum(1 for r in records if r["nct_ids"]),
        "with_fda_number": sum(1 for r in records if r["fda_numbers"]),
        "retracted": sum(1 for r in records if r["is_retracted"]),
        "source_manifest": manifest,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
