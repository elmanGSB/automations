#!/usr/bin/env bash
# Run this ONCE directly on the Paperclip VM after deploy.sh
set -euo pipefail

USERNAME=$(whoami)
INSTALL_DIR="/home/${USERNAME}/interview-router"

echo "==> Installing system dependencies..."
sudo apt-get update -q
sudo apt-get install -y chromium-browser xvfb

echo "==> Installing notebooklm-mcp-cli..."
pip install notebooklm-mcp-cli

echo "==> Setting up Xvfb systemd service..."
sudo tee /etc/systemd/system/xvfb.service > /dev/null << 'EOF'
[Unit]
Description=Xvfb virtual display
After=network.target

[Service]
ExecStart=/usr/bin/Xvfb :99 -screen 0 1280x1024x24
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable xvfb
sudo systemctl start xvfb
echo "Xvfb status: $(sudo systemctl is-active xvfb)"

echo "==> Configuring nlm to use chromium..."
nlm config set auth.browser chromium

echo "==> Installing interview-router systemd service..."
sed "s/REPLACE_WITH_USERNAME/${USERNAME}/g" \
  "${INSTALL_DIR}/interview-router.service" \
  > /tmp/interview-router.service
sudo cp /tmp/interview-router.service /etc/systemd/system/interview-router.service
sudo systemctl daemon-reload
sudo systemctl enable interview-router

echo ""
echo "==> Setup complete. Next steps:"
echo ""
echo "  1. Log in to NotebookLM (opens browser in virtual display):"
echo "     DISPLAY=:99 nlm login"
echo ""
echo "  2. Verify auth:"
echo "     nlm login --check"
echo ""
echo "  3. Start the service:"
echo "     sudo systemctl start interview-router"
echo "     sudo systemctl status interview-router"
echo ""
echo "  4. Check logs:"
echo "     journalctl -u interview-router -f"
