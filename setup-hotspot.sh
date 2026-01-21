#!/bin/bash
# setup-hotspot.sh - Install hostapd-based hotspot for Pi 3B

set -e

echo "Installing hostapd and dnsmasq..."
sudo apt-get update
sudo apt-get install -y hostapd dnsmasq

echo "Stopping services..."
sudo systemctl stop hostapd 2>/dev/null || true
sudo systemctl stop dnsmasq 2>/dev/null || true

echo "Copying config files..."
sudo cp /home/pi/beautifi-iot/hostapd.conf /etc/hostapd/hostapd.conf
sudo cp /home/pi/beautifi-iot/dnsmasq-hotspot.conf /etc/dnsmasq.d/hotspot.conf

echo "Configuring hostapd default..."
echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' | sudo tee /etc/default/hostapd

echo "Unmasking hostapd..."
sudo systemctl unmask hostapd

echo "Done. Hotspot configured but not started."
echo "To start manually: sudo systemctl start hostapd dnsmasq"
