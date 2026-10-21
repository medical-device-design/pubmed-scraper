#!/usr/bin/env bash
#
# run_pipeline.sh -- fetch, annotate and parse one topic, unattended.
#
#   bash scripts/run_pipeline.sh <topic> [auto|full|update] [--background]
#
#   auto (default)  a full fetch if the topic has none yet, otherwise an update
#   full            a fresh full fetch (do this every few months)
#   update          only papers changed since the last run
#
#   --background    start detached from the terminal, so it keeps running after
#                   you log out of the VM; prints where the log is and returns
#
# Every run writes logs/<topic>-<timestamp>.log and logs/<topic>.status (OK,
# PARTIAL or FAILED), so you or a health check can see how the last run went.
# Two runs of the same topic never overlap: a second one exits straight away.
#
# Optional: SCRAPER_OPTS passes extra options to every command, e.g. to keep
# data on a bigger disk:  SCRAPER_OPTS="--data-dir /data/pubmed" bash scripts/...
#
# Weekly with cron (Sunday 2 AM, inside NCBI's off-peak window). `crontab -e`:
#   0 2 * * 0  bash /home/<you>/pubmed-scraper/scripts/run_pipeline.sh in_vitro
#
# Exit codes: 0 OK, 1 failed, 2 bad usage, 3 PubMed data updated but PubTator3
# annotation failed (rerun later; it continues where it stopped), 75 another
# run of this topic is already in progress.

set -euo pipefail

usage() {
    sed -n '3,12p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
}

topic="" mode="auto" background=0
for arg in "$@"; do
    case "$arg" in
        --background) background=1 ;;
        -h|--help) usage ;;
        auto|full|update) mode="$arg" ;;
        -*) echo "unknown option: $arg" >&2; usage ;;
        *) if [[ -z "$topic" ]]; then topic="$arg"; else echo "unexpected argument: $arg" >&2; usage; fi ;;
    esac
done
[[ -n "$topic" ]] || usage

script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
repo="$(cd "$(dirname "$script")/.." && pwd)"
cd "$repo"
mkdir -p logs

stamp="$(date +%Y%m%d-%H%M%S)"
log="${PIPELINE_LOG:-logs/$topic-$stamp.log}"

# --- detach -------------------------------------------------------------------
if (( background )); then
    PIPELINE_LOG="$log" nohup bash "$script" "$topic" "$mode" >/dev/null 2>&1 &
    echo "started in the background (PID $!)"
    echo "  follow it:    tail -f $repo/$log"
    echo "  last result:  cat $repo/logs/$topic.status"
    exit 0
fi

# --- find Python in the virtual environment ----------------------------------
if [[ -x .venv/bin/python ]]; then
    py=.venv/bin/python
elif [[ -x .venv/Scripts/python.exe ]]; then        # Git Bash on Windows
    py=.venv/Scripts/python.exe
else
    echo "no virtual environment at $repo/.venv. Set it up first (see README):" >&2
    echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi
export PYTHONUNBUFFERED=1           # so the log shows progress as it happens
read -r -a opts <<< "${SCRAPER_OPTS:-}"

# --- log everything; also show it when run in a terminal ---------------------
if [[ -t 1 ]]; then
    exec > >(tee -a "$log") 2>&1
else
    exec >>"$log" 2>&1
fi

# --- one run per topic at a time ----------------------------------------------
lock="logs/.$topic.lock"
if command -v flock >/dev/null 2>&1; then
    exec 9>"$lock"
    if ! flock -n 9; then
        echo "$(date '+%F %T') another $topic run is still in progress; not starting a second one"
        exit 75
    fi
else                                                # no flock (e.g. Git Bash): lock directory
    if ! mkdir "$lock.d" 2>/dev/null; then
        other="$(cat "$lock.d/pid" 2>/dev/null || true)"
        if [[ -n "$other" ]] && kill -0 "$other" 2>/dev/null; then
            echo "$(date '+%F %T') another $topic run (PID $other) is still in progress; not starting a second one"
            exit 75
        fi
        rm -rf "$lock.d"; mkdir "$lock.d"            # left behind by a run that was killed
    fi
    echo $$ > "$lock.d/pid"
fi

# --- record the outcome, however the run ends ----------------------------------
started="$(date '+%F %T %Z')"
status="FAILED"
finish() {
    local code=$?
    [[ -d "$lock.d" ]] && rm -rf "$lock.d"
    {
        echo "status=$status"
        echo "topic=$topic"
        echo "mode=$mode"
        echo "started=$started"
        echo "finished=$(date '+%F %T %Z')"
        echo "exit_code=$code"
        echo "log=$log"
    } > "logs/$topic.status"
    echo
    echo "=== $(date '+%F %T') finished: $status (exit $code)"
}
trap finish EXIT

step() {
    echo
    echo "=== $(date '+%F %T') $*"
    "$py" -m pubmed_scraper ${opts[@]+"${opts[@]}"} "$@"     # (empty-array safe on old bash)
}

echo "=== $(date '+%F %T') pubmed-scraper pipeline: topic=$topic mode=$mode host=$(hostname)"
echo "    repo $repo, git $(git rev-parse --short HEAD 2>/dev/null || echo '?')"

case "$mode" in
    auto)   fetch_flag=(--auto) ;;
    full)   fetch_flag=() ;;
    update) fetch_flag=(--update) ;;
esac

step count "$topic"                  # fails fast on a bad topic name or no network
step fetch "$topic" ${fetch_flag[@]+"${fetch_flag[@]}"}

# PubTator3 is a separate service. If it is down, still produce the tables from
# the PubMed data; the next run annotates whatever is missing.
if step annotate "$topic"; then
    annotated=1
else
    annotated=0
    echo "warning: PubTator3 annotation failed; continuing without it for now"
fi

step parse "$topic"
step runs "$topic"

if (( annotated )); then
    status="OK"
else
    status="PARTIAL"
    exit 3
fi
