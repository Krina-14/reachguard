#!/usr/bin/env bash
# no_demo_data.sh — CI guard: ensures no mock/dummy/placeholder data in source.
# Exits 0 if backend/app and frontend/src are clean (or absent).
# Exits 1 if any forbidden patterns are found.

set -euo pipefail

PATTERN="mock|dummy|lorem|fake|demo_data|sample_data|hardcoded"
EXIT_CODE=0

for dir in backend/app frontend/src; do
  if [ -d "$dir" ]; then
    if matches=$(grep -rniE "$PATTERN" "$dir"); then
      echo "❌ Forbidden patterns found in $dir:"
      echo "$matches"
      EXIT_CODE=1
    fi
  fi
done

if [ "$EXIT_CODE" -eq 0 ]; then
  echo "✅ No demo/mock data found."
fi

exit "$EXIT_CODE"
