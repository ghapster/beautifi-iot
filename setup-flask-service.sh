#!/bin/bash

echo "Creating systemd service for SalonSafe Flask..."

cat <<EOF | sudo tee /etc/systemd/system/salonsafe-flask.service
[Unit]
Description=SalonSafe Flask App
After=network-online.target hostapd.service
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/salonsafe-iot/app.py
WorkingDirectory=/home/pi/salonsafe-iot
StandardOutput=inherit
StandardError=inherit
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
EOF

echo "Reloading and enabling service..."

sudo systemctl daemon-reload
sudo systemctl enable salonsafe-flask.service
sudo systemctl restart salonsafe-flask.service

echo "✅ Flask service installed and started!"
