#!/bin/sh
# Offline gates for the infra-tf root (roadmap item 12a): no cloud access.
# fmt (style) -> validate (schema) -> tflint (correctness) -> trivy (security).
set -eu
cd "$(dirname "$0")"

TFLINT="$(command -v tflint || echo "$HOME/bin/tflint")"

terraform fmt -check -diff
terraform init -backend=false >/dev/null
terraform validate
python3 tests/test_protections.py
policy/test.sh
"$TFLINT" --init >/dev/null
"$TFLINT" --format compact
trivy config --exit-code 1 --severity HIGH,CRITICAL .
echo "all gates passed"
