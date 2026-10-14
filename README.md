# pubmed-scraper
A data scraper for getting information for Knowledge Graph building

Collects PubMed papers on medical-device research by research type (in vitro
first; in vivo, safety and effectiveness planned) through NCBI's E-utilities,
and turns them into tables ready for loading into the medical-device-kg graph.

## Setup

Needs Python 3.11 or newer. Run these from the repo root.

**1. Create and activate a virtual environment** (once; the `.venv` folder is
git-ignored)

Windows (PowerShell):
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Linux / macOS / the VM:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

Your prompt shows `(.venv)` while it is active. Activate it again in each new
terminal. If PowerShell refuses to run `Activate.ps1`, allow local scripts once
with `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

**2. Install requirements**
```bash
pip install -r requirements.txt
```
(There are none yet; the scraper uses only Python's standard library. This
step keeps setup the same once packages are added.)

**3. Add your NCBI settings.** Copy `.env.example` to `.env` and fill in your
contact email (NCBI asks every client to send one). The API key is optional and
raises the rate limit from 3 to 10 requests per second. `.env` is git-ignored,
so your key stays on your machine. A real environment variable with the same
name (for example on the VM) overrides the value in `.env`.

## Usage

With the environment active, from the repo root:

```bash
python -m pubmed_scraper topics                       # list topics and their queries
python -m pubmed_scraper count in_vitro               # papers matching a topic
python -m pubmed_scraper fetch in_vitro --limit 200   # sample: 200 most recent
python -m pubmed_scraper fetch in_vitro               # everything matching
python -m pubmed_scraper parse in_vitro               # latest fetch -> tables
```

Queries live in `topics.toml`. Each topic's query is combined with the shared
device filter as `(device_filter) AND (topic)`.

NCBI asks that large jobs run on weekends or 9 PM to 5 AM US Eastern.

## Output

```
data/raw/<topic>/<run>/          untouched PubMed XML, PMID list, manifest.json
data/processed/<topic>/<run>/
    papers.jsonl                 everything per paper, nested
    papers.csv                   one row per paper
    authors.csv                  one row per (paper, author)
    mesh.csv                     one row per (paper, MeSH term)
    summary.json                 counts and the source manifest
```

Raw files are kept so data can be re-parsed without contacting NCBI again.
A raw run without `manifest.json` did not finish and is ignored by `parse`.
`data/` is git-ignored.

`papers.jsonl` includes abstracts. Abstracts can be under publisher copyright,
so keep them out of anything published openly (such as the graph on the
Proto-OKN Fabric).

## Tests

```bash
python -m unittest discover -s tests
```
