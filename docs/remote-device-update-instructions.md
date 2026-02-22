# How to Update Your BeautiFi Device (2 minutes)

> **Send these instructions to whoever has physical access to a device that needs a manual update.**

---

Hi,

The BeautiFi device at your location needs a one-time update that will take about 2 minutes. After this, it will update itself automatically going forward.

**What you'll need:**
- A laptop or computer connected to the same WiFi network as the device
- The device needs to be powered on

## Steps

### 1. Open a terminal

- **Mac:** Open "Terminal" (search for it in Spotlight)
- **Windows:** Open "Command Prompt" or "PowerShell" (search from Start menu)

### 2. Connect to the device

Type this and press Enter:

```
ssh pi@DEVICE_IP_ADDRESS
```

> Replace `DEVICE_IP_ADDRESS` with the device's IP (check the admin dashboard for the current IP).
>
> **Example:** `ssh pi@10.0.0.117`

- If it asks "Are you sure you want to continue connecting?" type `yes` and press Enter
- When it asks for a password, type `raspberry` and press Enter
  - You won't see the characters as you type — that's normal

### 3. Run the update

Copy and paste this entire line, then press Enter:

```
cd ~/beautifi-iot && git pull origin main && sudo systemctl restart beautifi-iot
```

- If it asks for a password again, type `raspberry` and press Enter
- You should see files downloading and then the service restarting

### 4. Verify it worked

Type this and press Enter:

```
sudo journalctl -u beautifi-iot --no-pager -n 5
```

You should see a line that says something like `[OTA] Update manager ready`.

### 5. Done!

Type `exit` and press Enter to disconnect.

The device will now keep itself updated automatically. No need to do this again.

---

**Having trouble?** Let us know — happy to walk you through it over the phone.
