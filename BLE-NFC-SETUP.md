# BLE NFC Reader — Pi Zero 2 W Setup

## Architecture

```
[NFC Card] → [PN532 via I2C] → [Pi Zero 2 W — BLE GATT Server] → [Browser Web Bluetooth] → [Next.js App]
```

The Pi Zero 2 W runs a Python BLE GATT server (`py/ble_nfc_server.py`) that:
1. Connects to a PN532 NFC module over I2C
2. Advertises as a BLE peripheral named "HospitalOS-NFC"
3. Exposes 3 GATT characteristics (NFC Data, Command, Status)
4. The browser connects via Web Bluetooth and sends READ/WRITE/FORMAT commands

## Pi Zero 2 W Setup (DietPi)

### 1. Flash & Boot

Flash **DietPi** (ARMv6/ARMv7 RPi image) to SD card. Complete first-boot setup (WiFi, locale, etc).

### 2. Enable I2C

```bash
dietpi-config
# → Advanced Options → I2C State → On
sudo reboot
```

### 3. Wire PN532

Set PN532 DIP switches to **I2C mode** (usually `1 0` — check silkscreen).

```
PN532       →  Pi Zero 2 W
──────────────────────────
SDA         →  GPIO 2 (pin 3)
SCL         →  GPIO 3 (pin 5)
VCC         →  3.3V   (pin 1)
GND         →  GND    (pin 6)
```

Verify:
```bash
sudo apt install -y i2c-tools
sudo i2cdetect -y 1
# Should show address 0x24
```

### 4. Install Dependencies

```bash
# System packages (dbus + GObject for BlueZ D-Bus API)
sudo apt install -y python3 python3-pip python3-venv python3-dbus python3-gi \
    libgirepository1.0-dev gcc python3-dev bluez bluez-tools i2c-tools

# Create venv WITH system site packages (required for dbus/gi)
python3 -m venv --system-site-packages /root/ble-nfc-env
source /root/ble-nfc-env/bin/activate

# PN532 driver
pip install adafruit-circuitpython-pn532
```

**Important:** The `--system-site-packages` flag is required. `python3-dbus` and `python3-gi` are system packages that cannot be pip-installed — the venv must be able to see them.

### 5. Copy Server Script

From your dev machine:
```bash
scp py/ble_nfc_server.py root@<PI_IP>:/root/hospital-project1/py/
```

### 6. Test

```bash
source /root/ble-nfc-env/bin/activate
python3 /root/hospital-project1/py/ble_nfc_server.py
```

Expected output:
```
PN532 found: firmware 1.6
Using adapter: /org/bluez/hci0
Advertising as 'HospitalOS-NFC' via BLE...
Hardware: True, Simulate: False
Service UUID: 12345678-1234-5678-1234-56789abcdef0
[BLE] GATT application registered
[BLE] Advertisement registered
```

Both `GATT application registered` AND `Advertisement registered` must appear.

### 7. Install as systemd Service

```bash
sudo tee /etc/systemd/system/ble-nfc.service > /dev/null << 'EOF'
[Unit]
Description=HospitalOS BLE NFC Server
After=bluetooth.target
Wants=bluetooth.target

[Service]
Type=simple
User=root
Environment=PATH=/root/ble-nfc-env/bin:/usr/local/bin:/usr/bin
ExecStart=/root/ble-nfc-env/bin/python3 /root/hospital-project1/py/ble_nfc_server.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ble-nfc
sudo systemctl start ble-nfc
```

Check logs:
```bash
sudo systemctl status ble-nfc
sudo journalctl -u ble-nfc -f
```

## How It Works (Technical)

### Why we use raw BlueZ D-Bus (not bluezero)

The first attempt used the `bluezero` Python library. It registered the device as **classic Bluetooth** (BR/EDR), not BLE (Low Energy). The device showed up in macOS Bluetooth Settings but was invisible to Web Bluetooth, which only scans for BLE advertisements.

The fix was to use the **BlueZ D-Bus API directly** (`dbus-python` + `python3-gi`), which gives full control over:
- `org.bluez.LEAdvertisingManager1` — registers a proper BLE advertisement
- `org.bluez.GattManager1` — registers the GATT service/characteristics
- `org.freedesktop.DBus.Properties.PropertiesChanged` — sends BLE notifications

### Why Web Bluetooth uses `acceptAllDevices: true`

The standard approach is to filter by name:
```js
navigator.bluetooth.requestDevice({
  filters: [{ namePrefix: "HospitalOS-NFC" }],
  optionalServices: [SERVICE_UUID],
})
```

This **did not work** — the device never appeared in Chrome's pairing dialog despite being correctly advertised. Switching to `acceptAllDevices: true` made it show up immediately:
```js
navigator.bluetooth.requestDevice({
  acceptAllDevices: true,
  optionalServices: [SERVICE_UUID],
})
```

This is likely a Chrome/macOS quirk where the `LocalName` field in the BLE advertisement packet isn't matched by the `namePrefix` filter. The device advertises correctly (verified via `btmgmt` and macOS), but Chrome's filter doesn't pick it up. Using `acceptAllDevices` bypasses the filter and lets the user pick from all visible BLE devices.

### BLE GATT Service Layout

**Service UUID:** `12345678-1234-5678-1234-56789abcdef0`

| Characteristic | UUID | Properties | Purpose |
|---------------|------|------------|---------|
| NFC Data | `...def1` | Read + Notify | NFC ID when card is tapped |
| Command | `...def2` | Write | Browser sends `READ`, `WRITE:<id>`, `FORMAT` |
| Status | `...def3` | Read + Notify | `idle` → `waiting` → `success` or `error:<msg>` |

### Read Flow

1. Browser connects to BLE device
2. Subscribes to NFC Data + Status notifications
3. Writes `READ` to Command characteristic
4. Pi starts polling PN532 (30s timeout)
5. Status: `idle` → `waiting` → `success`
6. NFC Data updates with the card ID
7. Browser receives notification, resolves Promise

### Write Flow

1. Browser writes `WRITE:<nfc_id>` to Command
2. Pi waits for card, writes data to it
3. Status: `waiting` → `success`

## Browser Side

The Next.js app has two NFC modes toggled in the `NfcTapButton` component:
- **Local NFC** — HTTP to `localhost:5532` (wired PN532 on kiosk Pi)
- **Bluetooth NFC** — Web Bluetooth to Pi Zero 2 W

Mode preference is saved to `localStorage` key `hospitalos-nfc-mode`.

### Files

| File | Purpose |
|------|---------|
| `lib/nfc.ts` | HTTP client for local PN532 (unchanged) |
| `lib/nfc-ble.ts` | Web Bluetooth client for BLE NFC reader |
| `components/NfcTapButton.tsx` | Tap button with Local/Bluetooth toggle |
| `components/patients/PatientsDashboard.tsx` | Uses BLE write when in Bluetooth mode |

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `i2cdetect` shows nothing at 0x24 | Check wiring. Check PN532 DIP switches are set to I2C. Is I2C enabled in `dietpi-config`? |
| `No BLE adapter found` | `sudo bluetoothctl power on` then `hciconfig` to check `hci0` exists |
| `Failed to register GATT` | Another BLE app may be using the adapter. `sudo systemctl restart bluetooth` and try again |
| `Failed to register advertisement` | Same as above — restart bluetooth service |
| Device doesn't show in Chrome pairing | Make sure the code uses `acceptAllDevices: true` (not name filter). Clear Mac's Bluetooth cache: forget device, toggle BT off/on |
| Chrome says "Bluetooth not available" | Web Bluetooth requires HTTPS or localhost. If accessing from another machine, set up HTTPS |
| Permission denied on Pi | Run as root (`sudo -E python3 ...`) — BlueZ D-Bus requires root |
| `ModuleNotFoundError: dbus` | Venv must use `--system-site-packages`. Recreate: `python3 -m venv --system-site-packages /root/ble-nfc-env` |
