#!/bin/bash
# setup-new-device.sh
# One-command setup for new BeautiFi IoT Raspberry Pi devices
#
# Usage (run this on the Pi after SSH):
#   curl -sSL https://raw.githubusercontent.com/ghapster/beautifi-iot/main/setup-new-device.sh | bash
#
# This script will:
#   1. Install system dependencies (git, python, etc.)
#   2. Clone the repo from GitHub
#   3. Install Python packages
#   4. Create the .env file with R2 credentials
#   5. Set up systemd services
#   6. Start the IoT service
#   7. Device auto-generates its unique identity on first run

set -e

echo ""
echo "========================================"
echo "  BeautiFi IoT - New Device Setup"
echo "========================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

INSTALL_DIR="/home/pi/beautifi-iot"
REPO_URL="https://github.com/ghapster/beautifi-iot.git"

# Check if running as pi user
if [ "$USER" != "pi" ]; then
    echo -e "${RED}Please run as 'pi' user${NC}"
    exit 1
fi

# Step 1: System dependencies
echo -e "${GREEN}[1/7] Updating system and installing dependencies...${NC}"
sudo apt-get update
sudo apt-get install -y git python3-pip python3-venv python3-dev

# Step 2: Clone repository
echo ""
echo -e "${GREEN}[2/7] Cloning BeautiFi IoT from GitHub...${NC}"
if [ -d "$INSTALL_DIR" ]; then
    echo "Directory exists, pulling latest..."
    cd "$INSTALL_DIR"
    git pull origin main
else
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# Step 3: Python virtual environment
echo ""
echo -e "${GREEN}[3/7] Creating Python virtual environment...${NC}"
cd "$INSTALL_DIR"
python3 -m venv venv
source venv/bin/activate

# Step 4: Install Python packages
echo ""
echo -e "${GREEN}[4/7] Installing Python packages...${NC}"
pip install --upgrade pip
pip install wheel
pip install -r requirements.txt
pip install RPi.GPIO

# Step 5: Create .env file
echo ""
echo -e "${GREEN}[5/7] Creating .env configuration...${NC}"
cat > "$INSTALL_DIR/.env" << 'ENVFILE'
R2_ENDPOINT_URL=https://56b78a569ec9d97475a8dc70cdb818c9.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=73f638f06feb1f4e6a37341a871b7353
R2_SECRET_ACCESS_KEY=39c91b9d8a9f20fa5d26170aa6de04d28edda79957958c37c74cb264e1905789
R2_BUCKET_NAME=beautifi-evidence
R2_TOKEN_VALUE=Pui1XYh4EgR8F4WrKtMKbSHOccdtynVxYmkFgibO
ENVFILE
echo ".env created"

# Step 6: Create systemd services
echo ""
echo -e "${GREEN}[6/7] Setting up systemd services...${NC}"

# WiFi boot check service
sudo tee /etc/systemd/system/beautifi-wifi.service > /dev/null << EOF
[Unit]
Description=BeautiFi WiFi Boot Check
Before=beautifi-iot.service
After=network.target

[Service]
Type=oneshot
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/wifi_boot.py
WorkingDirectory=$INSTALL_DIR
User=pi
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

# Main IoT service
sudo tee /etc/systemd/system/beautifi-iot.service > /dev/null << EOF
[Unit]
Description=BeautiFi IoT Service
After=network-online.target beautifi-wifi.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/app.py
WorkingDirectory=$INSTALL_DIR
User=pi
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable beautifi-wifi.service
sudo systemctl enable beautifi-iot.service

# Step 7: Start services
echo ""
echo -e "${GREEN}[7/7] Starting BeautiFi IoT service...${NC}"
sudo systemctl start beautifi-iot.service

sleep 5

# Get IP address
IP_ADDR=$(hostname -I | awk '{print $1}')

# Check if running
if sudo systemctl is-active --quiet beautifi-iot.service; then
    STATUS="${GREEN}RUNNING${NC}"
else
    STATUS="${YELLOW}CHECK LOGS${NC}"
fi

echo ""
echo "========================================"
echo -e "${GREEN}        Setup Complete!${NC}"
echo "========================================"
echo ""
echo "  Hostname:    $(hostname)"
echo "  IP Address:  $IP_ADDR"
echo "  Status:      $STATUS"
echo ""
echo "  Dashboard:   http://$IP_ADDR:5000/dashboard"
echo ""
echo "----------------------------------------"
echo "Useful Commands:"
echo "  sudo journalctl -u beautifi-iot -f    # View logs"
echo "  sudo systemctl restart beautifi-iot  # Restart"
echo "  sudo systemctl status beautifi-iot   # Status"
echo ""
echo "----------------------------------------"
echo "Next Steps:"
echo "  1. Open dashboard to verify fans work"
echo "  2. Run calibration (30 min):"
echo "     curl -X POST http://$IP_ADDR:5000/api/registration/calibrate \\"
echo "       -H 'Content-Type: application/json' -d '{\"duration_minutes\":30}'"
echo "  3. Register device with backend"
echo "  4. Approve in admin dashboard"
echo ""
