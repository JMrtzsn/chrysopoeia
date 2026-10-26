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
  enqueue)
    # run.sh enqueue <count> <spacing-minutes> <journal-prefix>
    # Enqueue individually scheduled tasks that each execute one bounded
    # session with its own journal. Pause/purge the queue to stop a campaign.
    PROJECT=${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}
    COUNT=${1:?count required}
    SPACING=${2:?spacing minutes required}
    PREFIX=${3:?journal prefix required}
    QUEUE="chrysopoeia-trigger-$OPERATOR"
    TRIGGER_SA=$(gcloud iam service-accounts list --project="$PROJECT" \
      --filter="email ~ ^chrysopoeia-trigger-$OPERATOR@" --format='value(email)' --limit=1)
    if [ -z "$TRIGGER_SA" ]; then
      echo "platform/run.sh: no trigger identity; deploy the stack first" >&2
      exit 1
    fi
    URL="https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/chrysopoeia-cycle-$OPERATOR:run"
    i=0
    while [ "$i" -lt "$COUNT" ]; do
      i=$((i + 1))
      JOURNAL=$(printf '%s-%03d' "$PREFIX" "$i")
      BODY=$(printf '{"overrides":{"containerOverrides":[{"args":["run","--journal","/mnt/journal/%s"]}]}}' "$JOURNAL")
      SCHED=$(date -u -v+"$(( (i - 1) * SPACING ))"M '+%Y-%m-%dT%H:%M:%SZ')
      gcloud tasks create-http-task --project="$PROJECT" --location="$REGION" --queue="$QUEUE" \
        --url="$URL" --method=POST --header='Content-Type: application/json' \
        --body-content="$BODY" --oauth-service-account-email="$TRIGGER_SA" \
        --schedule-time="$SCHED" > /dev/null
      echo "enqueued $JOURNAL at $SCHED"
    done
    ;;
  *)
    echo "usage: platform/run.sh {deploy|job|enqueue} [args...]" >&2
    exit 2
    ;;
esac
