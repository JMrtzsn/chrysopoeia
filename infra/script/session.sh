#!/bin/sh
# One ephemeral operator session on a spot e2-small VM.
#
#   session.sh init  <session-id>   boot VM, install the runtime, push source
#   session.sh push  <session-id>   (re)ship the current source bundle
#   session.sh ssh   <session-id>   open an interactive shell on the VM
#   session.sh delete <session-id>  destroy the VM (this is the exit path:
#                                   idle cost after teardown is exactly zero)
#
# Journal durability: the versioned GCS bucket is mounted at /mnt/journal with
# gcsfuse, so both the VM and your laptop commands can read/write the same
# authoritative journal file. No ingress is opened; egress defaults only.
# The VM runs as the least-privileged runner SA; no credentials are copied.
set -eu

PROJECT=${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}
REGION=${REGION:-us-central1}
ZONE="$REGION-a"
SA=${RUNNER_SA:-}
BUCKET=${JOURNAL_BUCKET:?set JOURNAL_BUCKET from pulumi export journal_bucket}
REPO_DIR=$(cd "$(dirname "$0")/../.." && pwd)

case "${1:?usage: session.sh <init|push|ssh|delete> <session-id>}" in
init)
  [ -n "$SA" ] || { echo "set RUNNER_SA from pulumi export runner_email" >&2; exit 1; }
  session_id=${2:?needs a session id}
  vm=chrysopoeia-sess-${session_id}
  gcloud compute instances create "$vm" \
    --project "$PROJECT" --zone "$ZONE" \
    --machine-type e2-small --provisioning-model SPOT \
    --image-family debian-12 --image-project debian-cloud \
    --boot-disk-size 10GB \
    --service-account "$SA" --scopes cloud-platform \
    --metadata startup-script='#!/bin/sh
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git python-is-python3 python3-pip lsb-release
curl -LsSf https://astral.sh/uv/install.sh | sh
curl -s https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.gpg
DEB=$(lsb_release -s -c)
echo "deb [signed-by=/usr/share/keyrings/cloud.gpg] https://packages.cloud.google.com/apt cloud-sdk-$DEB main" > /etc/apt/sources.list.d/cloud-gcsfuse.list
apt-get update -qq && apt-get install -y -qq gcsfuse
mkdir -p /opt/chrysopoeia /mnt/journal
:'
  echo
  echo "VM is provisioning. Next: infra/script/session.sh push $session_id"
  ;;
push)
  vm=chrysopoeia-sess-${2:?needs a session id}
  bundle=$(mktemp /tmp/chrysopoeia-src-XXXX.tar.gz)
  tar -czf "$bundle" \
    -C "$REPO_DIR" \
    pyproject.toml uv.lock chrysopoeia.toml chrysopoeia tests
  gcloud compute scp --project "$PROJECT" --zone "$ZONE" \
    "$bundle" "$vm":/tmp/source.tar.gz --quiet
  gcloud compute ssh --project "$PROJECT" --zone "$ZONE" "$vm" --tty \
    --command="/bin/sh -s $BUCKET" <<'INNER' || true
set -eu
sudo mkdir -p /opt/chrysopoeia /mnt/journal
sudo tar -xzf /tmp/source.tar.gz -C /opt/chrysopoeia
rm -f /tmp/source.tar.gz
sudo chown -R "$(whoami)" /opt/chrysopoeia /mnt/journal
if ! mountpoint -q /mnt/journal; then
  gcsfuse -o rw "$1" /mnt/journal
fi
cd /opt/chrysopoeia
~/.local/bin/uv sync --frozen >/dev/null
~/.local/bin/uv run --no-sync chrysopoeia validate --json >/dev/null
echo "session ready: cd /opt/chrysopoeia && uv run chrysopoeia --help"
INNER
  ;;
ssh)
  gcloud compute ssh --project "$PROJECT" --zone "$ZONE" \
    "chrysopoeia-sess-${2:?needs a session id}" --tty
  ;;
delete)
  gcloud compute instances delete "chrysopoeia-sess-${2:?needs a session id}" \
    --project "$PROJECT" --zone "$ZONE" --quiet
  ;;
esac
