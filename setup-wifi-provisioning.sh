#!/bin/bash
# setup-wifi-provisioning.sh
# Sets up WiFi provisioning with AP mode fallback for BeautiFi IoT

set -e

echo "========================================"
echo "BeautiFi WiFi Provisioning Setup"
echo "========================================"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo)"
    exit 1
fi

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/home/pi/beautifi-iot"

echo ""
echo "1. Installing dependencies..."
apt-get update
apt-get install -y network-manager python3-pip

echo ""
echo "2. Ensuring NetworkManager is enabled..."
systemctl enable NetworkManager
systemctl start NetworkManager

# Disable wpa_supplicant if it conflicts
if systemctl is-active --quiet wpa_supplicant; then
    echo "   Stopping wpa_supplicant (NetworkManager will manage WiFi)..."
    systemctl stop wpa_supplicant
    systemctl disable wpa_supplicant
fi

echo ""
echo "3. Copying files to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR/"
chown -R pi:pi "$INSTALL_DIR"

echo ""
echo "4. Installing systemd services..."

# WiFi boot service
cp "$INSTALL_DIR/beautifi-wifi.service" /etc/systemd/system/
chmod 644 /etc/systemd/system/beautifi-wifi.service

# Main IoT service
cp "$INSTALL_DIR/beautifi-iot.service" /etc/systemd/system/
chmod 644 /etc/systemd/system/beautifi-iot.service

echo ""
echo "5. Enabling services..."
systemctl daemon-reload
systemctl enable beautifi-wifi.service
systemctl enable beautifi-iot.service

echo ""
echo "6. Starting services..."
systemctl start beautifi-wifi.service
systemctl start beautifi-iot.service

echo ""
echo "========================================"
echo "Setup Complete!"
echo "========================================"
echo ""
echo "The device will now:"
echo "  1. Check for WiFi connection on boot"
echo "  2. If no WiFi, start AP mode (BeautiFi-Setup)"
echo "  3. You can connect to the AP and configure WiFi"
echo ""
echo "AP Settings:"
echo "  SSID: BeautiFi-Setup"
echo "  Password: beautifi123"
echo "  Setup URL: http://192.168.4.1:5000"
echo ""
echo "To check status:"
echo "  sudo systemctl status beautifi-wifi"
echo "  sudo systemctl status beautifi-iot"
echo ""
echo "To view logs:"
echo "  sudo journalctl -u beautifi-iot -f"
echo ""
