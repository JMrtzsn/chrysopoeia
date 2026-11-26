#!/bin/sh
# Fixture tests for the plan policy: every deny_*.json
# fixture must produce at least one denial, every allow_*.json must pass clean.
# Usage: policy/test.sh  (run from the infra-tf root)
set -eu
cd "$(dirname "$0")/.."

fail=0
for fixture in policy/fixtures/*.json; do
  name="$(basename "$fixture")"
  case "$name" in
    deny_*)
      if conftest test "$fixture" --policy policy --namespace terraform.plan >/dev/null 2>&1; then
        echo "FAIL expected denial: $name"
        fail=1
      else
        echo "ok   denial: $name"
      fi
      ;;
    allow_*)
      if conftest test "$fixture" --policy policy --namespace terraform.plan >/dev/null 2>&1; then
        echo "ok   clean:  $name"
      else
        echo "FAIL unexpected denial: $name"
        conftest test "$fixture" --policy policy --namespace terraform.plan 2>&1 | sed 's/^/     /'
        fail=1
      fi
      ;;
  esac
done
exit "$fail"
