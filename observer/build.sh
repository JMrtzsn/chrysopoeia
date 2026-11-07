#!/bin/sh
# Build only. Publishing is a separate, explicitly approved operation.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$ROOT/observer/.build"
(cd "$ROOT/observer" && uv build)
# Pin the runtime to the verified lockfile instead of resolving at image build.
(cd "$ROOT/observer" && uv export --frozen --no-dev --no-emit-project --no-hashes \
  -o .build/requirements.txt)
docker build --platform linux/amd64 -t chrysopoeia-observer:local "$ROOT/observer"
docker run --rm --platform linux/amd64 --network none chrysopoeia-observer:local \
  python -c "import observer; import observer.app"
docker inspect --format='{{.Id}}' chrysopoeia-observer:local
