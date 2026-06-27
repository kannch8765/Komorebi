#!/usr/bin/env bash
# check_api_usage.sh
#
# Print a short summary of Google Places API usage from
# data/places_api_usage.json. Warns if today's call count exceeds
# the per-day soft budget (default: 50).
#
# Usage:
#   ./scripts/check_api_usage.sh                  # default budget 50
#   ./scripts/check_api_usage.sh --budget 100     # custom soft budget
#   ./scripts/check_api_usage.sh --path data/x.json
#
# Exit code: 0 always. This is a status script, not a gate.
#
# The data file is gitignored — it's local observability, not part
# of the project deliverable. We tolerate a missing file (first run)
# and a corrupt file (no crash, just defaults).

set -uo pipefail

# ─── Args ─────────────────────────────────────────────────────────────────

USAGE_PATH="data/places_api_usage.json"
BUDGET=50
SHOW_HELP=false

while [ $# -gt 0 ]; do
    case "$1" in
        --budget)
            BUDGET="$2"
            shift 2
            ;;
        --path)
            USAGE_PATH="$2"
            shift 2
            ;;
        -h|--help)
            SHOW_HELP=true
            shift
            ;;
        *)
            echo "Unknown arg: $1" >&2
            SHOW_HELP=true
            shift
            ;;
    esac
done

if [ "$SHOW_HELP" = "true" ]; then
    cat <<EOF
Usage: $0 [--budget N] [--path FILE]

Options:
  --budget N    Soft daily limit for the warning (default: 50)
  --path FILE   Path to the usage JSON (default: data/places_api_usage.json)
  -h, --help    Show this help

Exit code is always 0.
EOF
    exit 0
fi

# ─── Locate repo root for relative paths ──────────────────────────────────

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
if [ "${USAGE_PATH:0:1}" = "/" ]; then
    ABS_PATH="$USAGE_PATH"
else
    ABS_PATH="$REPO_ROOT/$USAGE_PATH"
fi

# ─── Read the file (tolerate missing/corrupt) ─────────────────────────────

if [ ! -f "$ABS_PATH" ]; then
    echo "Places API usage: no data yet (file not found: $USAGE_PATH)"
    exit 0
fi

if ! command -v jq >/dev/null 2>&1; then
    # No jq → fall back to python, which we know is available (uv env).
    # Use heredoc to avoid quoting nightmares with the JSON content.
    ABS_PATH="$ABS_PATH" BUDGET="$BUDGET" python3 - <<'PYEOF' 2>/dev/null \
        || echo "check_api_usage: python read failed; install jq for better output"
import json
import os
import sys
from datetime import datetime, timezone

path = os.environ["ABS_PATH"]
budget = int(os.environ.get("BUDGET", "50"))

try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
except (OSError, ValueError) as exc:
    print(f"check_api_usage: could not read {path}: {exc}")
    sys.exit(0)

total = int(data.get("total_calls", 0))
last = data.get("last_call")
daily = data.get("daily", {}) or {}
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
today_count = int(daily.get(today, 0))

print("Places API usage:")
print(f"  Today:  {today_count} call(s)")
print(f"  Total:  {total} call(s)")
if last:
    print(f"  Last:   {last}")
if daily and len(daily) > 1:
    # Show recent days (newest first), excluding today which we already printed.
    recent = sorted(
        ((d, c) for d, c in daily.items() if d != today),
        key=lambda kv: kv[0],
        reverse=True,
    )[:3]
    if recent:
        print("  Recent days:")
        for d, c in recent:
            print(f"    {d}: {c} call(s)")

if today_count > budget:
    print()
    print(f"WARNING: today's usage ({today_count}) exceeds soft budget ({budget}).")
    print("  Google Places API free tier: 10,000 calls/month across all Pro+Essentials fields.")
    print("  See https://developers.google.com/maps/billing-and-pricing/billing")
elif today_count > (budget / 2):
    # Quiet info — only print the warning line, no banner.
    print(f"  (soft budget: {budget}, today is over halfway)")
PYEOF
    exit 0
fi

# ─── jq path ──────────────────────────────────────────────────────────────

TOTAL="$(jq -r '.total_calls // 0' "$ABS_PATH" 2>/dev/null || echo 0)"
LAST="$(jq -r '.last_call // "n/a"' "$ABS_PATH" 2>/dev/null || echo "n/a")"
TODAY="$(date -u +%Y-%m-%d)"
TODAY_COUNT="$(jq -r --arg t "$TODAY" '.daily[$t] // 0' "$ABS_PATH" 2>/dev/null || echo 0)"

echo "Places API usage:"
echo "  Today:  $TODAY_COUNT call(s)"
echo "  Total:  $TOTAL call(s)"
if [ "$LAST" != "n/a" ] && [ "$LAST" != "null" ]; then
    echo "  Last:   $LAST"
fi

# Show the most recent 3 days (other than today), newest first.
RECENT="$(jq -r --arg t "$TODAY" \
    '(.daily | to_entries | map(select(.key != $t)) | sort_by(.key) | reverse | .[0:3] | .[] | "    " + .key + ": " + (.value|tostring) + " call(s)")' \
    "$ABS_PATH" 2>/dev/null || true)"
if [ -n "$RECENT" ]; then
    echo "  Recent days:"
    printf '%s\n' $RECENT
fi

if [ "$TODAY_COUNT" -gt "$BUDGET" ]; then
    echo ""
    echo "WARNING: today's usage ($TODAY_COUNT) exceeds soft budget ($BUDGET)."
    echo "  Google Places API free tier: 10,000 calls/month across all Pro+Essentials fields."
    echo "  See https://developers.google.com/maps/billing-and-pricing/billing"
fi

exit 0
