#!/bin/sh
# Explicit, operator-gated entrypoint for running the deployed platform.
# Nothing here runs on its own: every action requires CHRYSOPOEIA_RUN_PLATFORM=1,
# and the Pulumi program refuses to apply without it as well.
#
#   CHRYSOPOEIA_RUN_PLATFORM=1 platform/run.sh deploy [pulumi args...]
#   CHRYSOPOEIA_RUN_PLATFORM=1 platform/run.sh job    [gcloud args...]
#
# deploy  apply the Pulumi stack (create/update/delete cloud resources)
# job     execute one on-demand Cloud Run job
#
# Preview is always allowed and does not need this entrypoint:
#   PULUMI_CONFIG_PASSPHRASE='' pulumi -C platform/infra preview --stack local-dev
set -eu

ACTION=${1:-}
if [ "$#" -gt 0 ]; then shift; fi
STACK=${STACK:-local-dev}
REGION=${REGION:-us-central1}
OPERATOR=${OPERATOR:-local}

if [ "${CHRYSOPOEIA_RUN_PLATFORM:-}" != "1" ]; then
  echo "platform/run.sh: refusing; set CHRYSOPOEIA_RUN_PLATFORM=1 to run the platform" >&2
  exit 2
fi

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)

case "$ACTION" in
  deploy)
    if [ -z "${PULUMI_CONFIG_PASSPHRASE+x}" ]; then
      echo "platform/run.sh: set PULUMI_CONFIG_PASSPHRASE (empty string for local-dev)" >&2
      exit 2
    fi
    exec pulumi -C "$REPO_ROOT/platform/infra" up --stack "$STACK" --yes "$@"
    ;;
  job)
    PROJECT=${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}
    exec gcloud beta run jobs execute "chrysopoeia-cycle-$OPERATOR" \
      --region "$REGION" --project "$PROJECT" "$@"
    ;;
  *)
    echo "usage: platform/run.sh {deploy|job} [args...]" >&2
    exit 2
    ;;
esac
