#!/bin/sh
# Explicit, operator-gated entrypoint for running the deployed platform.
# Mutating actions require CHRYSOPOEIA_RUN_PLATFORM=1.
#
#   platform/run.sh drift
#   CHRYSOPOEIA_RUN_PLATFORM=1 platform/run.sh deploy [terraform plan args...]
#   CHRYSOPOEIA_RUN_PLATFORM=1 platform/run.sh job    [gcloud args...]
#
# drift   read-only `terraform plan -detailed-exitcode`; exit 2 means drift
# deploy  offline gates -> saved plan -> conftest policy -> apply that plan only
# job     execute one on-demand Cloud Run job
#
# Values live in the operator-local platform/infra-tf/terraform.tfvars.
set -eu

ACTION=${1:-}
if [ "$#" -gt 0 ]; then shift; fi
REGION=${REGION:-us-central1}
OPERATOR=${OPERATOR:-local}
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
TF_DIR="$REPO_ROOT/platform/infra-tf"

if [ "$ACTION" = "drift" ]; then
  terraform -chdir="$TF_DIR" init -input=false >/dev/null
  exec terraform -chdir="$TF_DIR" plan -input=false -lock=false -detailed-exitcode "$@"
fi

if [ "${CHRYSOPOEIA_RUN_PLATFORM:-}" != "1" ]; then
  echo "platform/run.sh: refusing; set CHRYSOPOEIA_RUN_PLATFORM=1 to run the platform" >&2
  exit 2
fi

case "$ACTION" in
  deploy)
    PLAN=$(mktemp -d)/tfplan
    "$TF_DIR/gates.sh"
    terraform -chdir="$TF_DIR" init -input=false >/dev/null
    terraform -chdir="$TF_DIR" plan -input=false -out="$PLAN" "$@"
    terraform -chdir="$TF_DIR" show -json "$PLAN" > "$PLAN.json"
    conftest test --namespace terraform.plan -p "$TF_DIR/policy" "$PLAN.json"
    exec terraform -chdir="$TF_DIR" apply -input=false "$PLAN"
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
    echo "usage: platform/run.sh {drift|deploy|job|enqueue} [args...]" >&2
    exit 2
    ;;
esac
