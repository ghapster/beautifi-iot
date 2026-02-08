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
echo -e "${GREEN}[1/8] Updating system and installing dependencies...${NC}"
sudo apt-get update
sudo apt-get install -y git python3-pip python3-venv python3-dev libffi-dev build-essential hostapd dnsmasq avahi-daemon

# Step 2: Clone repository
echo ""
echo -e "${GREEN}[2/8] Cloning BeautiFi IoT from GitHub...${NC}"
if [ -d "$INSTALL_DIR" ]; then
    echo "Directory exists, pulling latest..."
    cd "$INSTALL_DIR"
    git pull origin main
else
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# Step 3: Configure hostapd and dnsmasq for AP mode
echo ""
echo -e "${GREEN}[3/8] Configuring WiFi AP mode (hostapd/dnsmasq)...${NC}"

# Copy hostapd config
sudo cp "$INSTALL_DIR/hostapd.conf" /etc/hostapd/hostapd.conf
sudo chmod 644 /etc/hostapd/hostapd.conf

# Tell hostapd to use our config file
sudo sed -i 's|^#DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd 2>/dev/null || \
    echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' | sudo tee /etc/default/hostapd > /dev/null

# Configure dnsmasq for AP mode (only used when in AP mode)
sudo cp "$INSTALL_DIR/dnsmasq-hotspot.conf" /etc/dnsmasq.d/beautifi-hotspot.conf
sudo chmod 644 /etc/dnsmasq.d/beautifi-hotspot.conf

# Disable hostapd and dnsmasq from auto-starting (we start them manually in AP mode)
sudo systemctl disable hostapd 2>/dev/null || true
sudo systemctl disable dnsmasq 2>/dev/null || true
sudo systemctl stop hostapd 2>/dev/null || true
sudo systemctl stop dnsmasq 2>/dev/null || true

# Unmask hostapd (it's often masked by default on Raspberry Pi OS)
sudo systemctl unmask hostapd 2>/dev/null || true

echo "hostapd and dnsmasq configured for AP mode"

# Configure NetworkManager to ignore uap0 (AP virtual interface managed by hostapd)
sudo mkdir -p /etc/NetworkManager/conf.d/
cat << EOF | sudo tee /etc/NetworkManager/conf.d/unmanaged-uap0.conf > /dev/null
[keyfile]
unmanaged-devices=interface-name:uap0
EOF
sudo systemctl restart NetworkManager 2>/dev/null || true
echo "NetworkManager configured to ignore uap0 (AP+STA concurrent mode)"

# Enable mDNS (avahi) for easy access via hostname.local
sudo systemctl enable avahi-daemon 2>/dev/null || true
sudo systemctl start avahi-daemon 2>/dev/null || true

# Disable IPv6 in avahi to prevent .local resolving to unusable link-local IPv6 addresses
sudo sed -i 's/use-ipv6=yes/use-ipv6=no/' /etc/avahi/avahi-daemon.conf
# Also stop publishing AAAA records over IPv4 mDNS (browsers prefer IPv6 and fail on fe80::)
sudo sed -i 's/#publish-aaaa-on-ipv4=yes/publish-aaaa-on-ipv4=no/' /etc/avahi/avahi-daemon.conf
echo "Disabled IPv6 in avahi (prevents .local resolution failures)"

# Install avahi service file for device discovery
if [ -f "$INSTALL_DIR/avahi/beautifi.service" ]; then
    sudo cp "$INSTALL_DIR/avahi/beautifi.service" /etc/avahi/services/
    sudo systemctl restart avahi-daemon
    echo "BeautiFi mDNS service installed for network discovery"
fi
echo "mDNS enabled - device accessible via $(hostname).local"

# Step 4: Python virtual environment
echo ""
echo -e "${GREEN}[4/8] Creating Python virtual environment...${NC}"
cd "$INSTALL_DIR"
python3 -m venv venv
source venv/bin/activate

# Step 5: Install Python packages
echo ""
echo -e "${GREEN}[5/8] Installing Python packages...${NC}"
pip install --upgrade pip
pip install wheel
pip install -r requirements.txt
pip install RPi.GPIO

# Step 6: Create .env file
echo ""
echo -e "${GREEN}[6/8] Creating .env configuration...${NC}"
cat > "$INSTALL_DIR/.env" << 'ENVFILE'
R2_ENDPOINT_URL=https://56b78a569ec9d97475a8dc70cdb818c9.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=73f638f06feb1f4e6a37341a871b7353
R2_SECRET_ACCESS_KEY=39c91b9d8a9f20fa5d26170aa6de04d28edda79957958c37c74cb264e1905789
R2_BUCKET_NAME=beautifi-evidence
R2_TOKEN_VALUE=Pui1XYh4EgR8F4WrKtMKbSHOccdtynVxYmkFgibO
ENVFILE
echo ".env created"

# Step 7: Create systemd services
echo ""
echo -e "${GREEN}[7/8] Setting up systemd services...${NC}"

# WiFi boot check service (runs as root to configure networking)
sudo tee /etc/systemd/system/beautifi-wifi.service > /dev/null << EOF
[Unit]
Description=BeautiFi WiFi Boot Check
Before=beautifi-iot.service
After=network.target

[Service]
Type=oneshot
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/wifi_boot.py
WorkingDirectory=$INSTALL_DIR
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

# Step 8: Start services
echo ""
echo -e "${GREEN}[8/8] Starting BeautiFi IoT service...${NC}"
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
echo "  Dashboard:   http://$(hostname).local:5000/dashboard"
echo "               http://$IP_ADDR:5000/dashboard"
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
