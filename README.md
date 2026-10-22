# pubmed-scraper
A data scraper for getting information for Knowledge Graph building

Collects PubMed papers on medical-device research by research type (in vitro
first; in vivo, safety and effectiveness planned) through NCBI's E-utilities,
and turns them into tables ready for loading into the medical-device-kg graph.

## Setup

Needs Python 3.10 or newer (Ubuntu 22.04's built-in Python 3.10 works). Run
these from the repo root.

On Ubuntu, step 1 needs the venv package, or it fails with "ensurepip is not
available": `sudo apt install -y python3-venv`. Without sudo,
`python3 -m venv --without-pip .venv` also works for now, since there are no
packages to install yet.

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
python -m pubmed_scraper fetch in_vitro --update      # only what changed since the last run
python -m pubmed_scraper fetch in_vitro --auto        # full if none exists yet, else update
python -m pubmed_scraper annotate in_vitro            # PubTator3 entities for fetched papers
python -m pubmed_scraper parse in_vitro               # saved data -> tables
python -m pubmed_scraper runs in_vitro                # list the runs saved so far
```

Queries live in `topics.toml`. Each topic's query is combined with the shared
device filter as `(device_filter) AND (topic)`.

NCBI asks that large jobs run on weekends or 9 PM to 5 AM US Eastern.

### The usual cycle

1. **Once:** a full fetch, then annotate, then parse.
2. **Regularly (for example weekly):** `fetch --update`, then `annotate`, then
   `parse`. An update downloads only papers whose PubMed record changed since
   the last run, and `parse` merges them with the full run, newest copy winning.
3. **Now and then (for example quarterly):** a new full fetch, to drop papers
   that no longer match or were deleted from PubMed (updates can't see those).

Updates search by the date a record last *changed*, not the date it was added.
Our query filters on MeSH indexing, which NLM adds weeks after a paper first
appears, so most papers only start matching when they are indexed. In one
month of in vitro data, 81 papers were new but 1,651 records changed.

`fetch --update` refuses to run if there is no full fetch yet, or if the
topic's query in `topics.toml` changed since then (do a full fetch instead).

### PubTator3 annotations

`annotate` downloads NCBI's PubTator3 text-mining results for every fetched
paper: genes, diseases, chemicals, species, variants and cell lines, each
linked to a standard ID (NCBI Gene, MeSH, NCBI Taxonomy), plus relations
between them. No key is needed. It takes about 8 seconds per 100 papers, so a
full in vitro run (~69,000 papers) takes around 1.5 hours. If it stops partway,
run it again and it continues where it left off. The newest papers may not be
in PubTator3 yet; they are counted in the output and get picked up by a later
update once they change.

## Running on the VM

`scripts/run_pipeline.sh` runs fetch, annotate and parse for one topic in a
row, unattended. Do the Setup steps above on the VM first (create `.venv`,
add `.env`).

**Start a run in the background** (keeps going after you log out):
```bash
bash scripts/run_pipeline.sh in_vitro --background
```
It prints where the log is and returns. The first run does a full fetch
(about 10 minutes, then about 1.5 hours of PubTator3 annotation). Later runs
fetch only what changed.

**Check on it:**
```bash
tail -f logs/in_vitro-*.log             # live progress (Ctrl+C stops watching, not the run)
cat logs/in_vitro.status                # result of the last run: OK, PARTIAL or FAILED
python -m pubmed_scraper runs in_vitro  # what has been collected
```

`PARTIAL` means the PubMed data was updated but PubTator3 failed (for example
if the service was down). Run the script again later; annotation continues
where it stopped.

**Choose the kind of run** with a second argument: `auto` (default: full
the first time, update after), `full`, or `update`. Do a `full` run every few
months to drop papers that no longer match:
```bash
bash scripts/run_pipeline.sh in_vitro full --background
```

**Run it on a schedule with cron.** Run `crontab -e` and add a line like this
(every Sunday at 2 AM, inside NCBI's off-peak window), with your repo's path:
```
0 2 * * 0  bash /home/<you>/pubmed-scraper/scripts/run_pipeline.sh in_vitro
```

Two runs of the same topic never overlap: if one is still going, a new one
exits straight away (exit code 75). To keep data on a bigger disk, set
`SCRAPER_OPTS="--data-dir /path/to/disk"` before the command.

The full in vitro data takes about 2 GB of disk (raw XML, PubTator3 output and
tables). Each new full run adds another copy; delete old run folders under
`data/raw/` by hand once a newer full run has finished.

## Output

```
data/raw/<topic>/<run>/          untouched PubMed XML, PMID list, manifest.json
    pubtator/                    raw PubTator3 JSON and its manifest (after annotate)
data/processed/<topic>/<run>/
    papers.jsonl                 everything per paper, nested
    papers.csv                   one row per paper
    authors.csv                  one row per (paper, author)
    mesh.csv                     one row per (paper, MeSH term)
    grants.csv                   one row per (paper, grant)
    entities.csv                 one row per (paper, PubTator3 entity)
    relations.csv                one row per (paper, PubTator3 relation)
    summary.json                 counts and the manifests of the runs used
```

Raw files are kept so data can be re-parsed without contacting NCBI again.
A raw run without `manifest.json` did not finish and is ignored by `parse`.
`data/` is git-ignored.

Two kinds of trial ID are kept apart in `papers.csv`: `nct_ids` are the
ClinicalTrials.gov links NLM recorded on the paper, and `nct_ids_in_text` are
NCT numbers found in the title or abstract. `fda_numbers` are 510(k), De Novo
and PMA numbers found in the title or abstract.

In `entities.csv`, `is_normalized=False` rows are mentions PubTator3 could not
link to an ID. They are kept because many are device materials (PDMS, GelMA,
cobalt-chromium).

`papers.jsonl` and the raw files include abstracts. Abstracts can be under
publisher copyright, so keep them out of anything published openly (such as
the graph on the Proto-OKN Fabric). The other tables hold only identifiers,
terms and counts.

## Tests

```bash
python -m unittest discover -s tests
```
