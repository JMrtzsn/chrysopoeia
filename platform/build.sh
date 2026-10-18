#!/bin/sh
# Build and publish the harness image from the harness wheel, not harness
# source: the harness folder is owned by a separate work unit, and the
# platform's only contract with it is the pinned image digest.
#
#   platform/build.sh <digest-file>          build+push, print digest
#
# Steps:
#   1. uv build in harness/ produces dist/crysopoeia-<ver>-py3-none-any.whl
#   2. stage the wheel into platform/.build/ (docker build context)
#   3. docker build from platform/Dockerfile, tag harness:latest
#   4. local offline gate: docker run <image> validate --json
#   5. docker push; echo the digest for the Pulumi image variable
set -eu

PROJECT=${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}
REGION=${REGION:-us-central1}
IMAGE="$REGION-docker.pkg.dev/$PROJECT/chrysopoeia/harness"
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
HARNESS_DIR="$REPO_ROOT/harness"
PLATFORM_DIR="$REPO_ROOT/platform"

mkdir -p "$HARNESS_DIR/dist" "$PLATFORM_DIR/.build"
(cd "$HARNESS_DIR" && uv build)
cp "$HARNESS_DIR"/dist/*.whl "$PLATFORM_DIR/.build/"
cp "$HARNESS_DIR/chrysopoeia.toml" "$PLATFORM_DIR/.build/chrysopoeia.toml"
cp "$HARNESS_DIR/configs/platform.toml" "$PLATFORM_DIR/.build/platform.toml"
# Pin the runtime to the verified lockfile; installing the wheel alone lets
# transitive dependencies drift and changes agent behavior between rebuilds.
(cd "$HARNESS_DIR" && uv export --frozen --no-dev --no-emit-project --no-hashes \
  -o "$PLATFORM_DIR/.build/requirements.txt")

docker build --platform linux/amd64 \
  -t "$REGION-docker.pkg.dev/$PROJECT/chrysopoeia/harness:latest" "$PLATFORM_DIR"

docker run --rm --platform linux/amd64 \
  "$REGION-docker.pkg.dev/$PROJECT/chrysopoeia/harness:latest" validate --json \
  | tee "$PLATFORM_DIR/.build/validate.json"

docker run --rm --platform linux/amd64 \
  "$REGION-docker.pkg.dev/$PROJECT/chrysopoeia/harness:latest" \
  validate --config /etc/chrysopoeia-platform.toml --json

docker push "$REGION-docker.pkg.dev/$PROJECT/chrysopoeia/harness:latest"

digest=$(docker inspect --format='{{index .RepoDigests 0}}' \
  "$REGION-docker.pkg.dev/$PROJECT/chrysopoeia/harness:latest")
echo "PULUMI image pin: $digest"
