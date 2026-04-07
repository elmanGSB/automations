#!/usr/bin/env bash
set -euo pipefail

VM="paperclip-vm"
ZONE="us-central1-f"
REMOTE_DIR="~/interview-router"

echo "==> Syncing code to VM..."
gcloud compute scp --recurse \
  --zone="$ZONE" \
  ~/interview-router/ \
  "${VM}:${REMOTE_DIR}" \
  --exclude=".git" \
  --exclude="__pycache__" \
  --exclude="*.pyc" \
  --exclude=".pytest_cache" \
  --exclude=".env" \
  --exclude="state.json"

echo "==> Installing dependencies on VM..."
gcloud compute ssh "$VM" --zone="$ZONE" -- \
  "cd ~/interview-router && pip install -r requirements.txt -q"

echo "==> Restarting service..."
gcloud compute ssh "$VM" --zone="$ZONE" -- \
  "sudo systemctl restart interview-router 2>/dev/null || echo 'Service not installed yet — run: sudo systemctl enable --now interview-router'"

echo "==> Done. Check status with:"
echo "    gcloud compute ssh $VM --zone=$ZONE -- 'sudo systemctl status interview-router'"
