#!/bin/sh
# Build only. Publishing is a separate, explicitly approved operation.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
(cd "$ROOT/consumer" && uv build)
mkdir -p "$ROOT/consumer/.build"
cp "$ROOT/contracts/trade_plan_ready.v1.schema.json" "$ROOT/consumer/.build/"
cp "$ROOT/contracts/trade_plan_ready.v2.schema.json" "$ROOT/consumer/.build/"
cp "$ROOT/contracts/consumer_outcome.v1.schema.json" "$ROOT/consumer/.build/"
docker build --platform linux/amd64 -t chrysopoeia-paper-consumer:local "$ROOT/consumer"
docker inspect --format='{{.Id}}' chrysopoeia-paper-consumer:local
