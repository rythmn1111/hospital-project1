"""
HospitalOS BLE NFC Server
Runs on Pi Zero 2 W. Advertises a BLE GATT service that allows
browsers (via Web Bluetooth) to read/write NFC cards through a PN532 module.
Falls back to simulation mode if PN532 hardware is not connected.
"""

import time
import threading
import struct

# --- PN532 hardware setup ---
SIMULATE = False

try:
    import board
    import busio
    from adafruit_pn532.i2c import PN532_I2C

    i2c = busio.I2C(board.SCL, board.SDA)
    pn532 = PN532_I2C(i2c, debug=False)
    ic, ver, rev, support = pn532.firmware_version
    print(f"PN532 found: firmware {ver}.{rev}")
    pn532.SAM_configuration()
    HAS_HARDWARE = True
except Exception as e:
    print(f"PN532 not found ({e}), running in simulation mode")
    HAS_HARDWARE = False
    SIMULATE = True

# --- BLE imports ---
from bluezero import adapter, peripheral

# --- UUIDs ---
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
NFC_DATA_UUID = "12345678-1234-5678-1234-56789abcdef1"
COMMAND_UUID = "12345678-1234-5678-1234-56789abcdef2"
STATUS_UUID = "12345678-1234-5678-1234-56789abcdef3"

# --- Shared state ---
nfc_data_value = ""
status_value = "idle"
nfc_data_char = None
status_char = None


def encode_str(s):
    """Encode a string to bytes for BLE characteristic."""
    return list(s.encode("utf-8"))


def decode_bytes(value):
    """Decode BLE characteristic bytes to string."""
    return bytes(value).decode("utf-8", errors="ignore").strip("\x00")


# --- NFC operations (reused from nfc_server.py) ---

def read_nfc_card(timeout=30):
    if SIMULATE:
        time.sleep(2)
        return {"nfc_id": None, "raw": ""}

    start = time.time()
    while time.time() - start < timeout:
        uid = pn532.read_passive_target(timeout=1.0)
        if uid is not None:
            try:
                key = b'\xFF\xFF\xFF\xFF\xFF\xFF'
                if pn532.mifare_classic_authenticate_block(uid, 4, 0x60, key):
                    full_data = bytearray()
                    for block in [4, 5, 6]:
                        block_data = pn532.mifare_classic_read_block(block)
                        if block_data:
                            full_data.extend(block_data)
                    text = full_data.decode('utf-8', errors='ignore').strip('\x00').strip()
                    return {"nfc_id": text if text else None, "uid": uid.hex()}
            except Exception:
                pass
            try:
                full_data = bytearray()
                for page in range(4, 16):
                    page_data = pn532.ntag2xx_read_block(page)
                    if page_data:
                        full_data.extend(page_data)
                text = full_data.decode('utf-8', errors='ignore').strip('\x00').strip()
                return {"nfc_id": text if text else None, "uid": uid.hex()}
            except Exception:
                return {"nfc_id": None, "uid": uid.hex()}
    return None


def write_nfc_card(nfc_id, timeout=30):
    if SIMULATE:
        time.sleep(2)
        return {"success": True, "nfc_id": nfc_id}

    start = time.time()
    while time.time() - start < timeout:
        uid = pn532.read_passive_target(timeout=1.0)
        if uid is not None:
            data = nfc_id.encode('utf-8').ljust(48, b'\x00')
            try:
                key = b'\xFF\xFF\xFF\xFF\xFF\xFF'
                if pn532.mifare_classic_authenticate_block(uid, 4, 0x60, key):
                    for i, block in enumerate([4, 5, 6]):
                        pn532.mifare_classic_write_block(block, data[i*16:(i+1)*16])
                    return {"success": True, "nfc_id": nfc_id}
            except Exception:
                pass
            try:
                padded = data.ljust(48, b'\x00')
                for i in range(12):
                    pn532.ntag2xx_write_block(4 + i, padded[i*4:(i+1)*4])
                return {"success": True, "nfc_id": nfc_id}
            except Exception as e:
                return {"success": False, "error": str(e)}
    return None


def format_nfc_card(timeout=30):
    if SIMULATE:
        time.sleep(1)
        return {"success": True}

    start = time.time()
    while time.time() - start < timeout:
        uid = pn532.read_passive_target(timeout=1.0)
        if uid is not None:
            zeros = b'\x00' * 16
            try:
                key = b'\xFF\xFF\xFF\xFF\xFF\xFF'
                if pn532.mifare_classic_authenticate_block(uid, 4, 0x60, key):
                    for block in [4, 5, 6]:
                        pn532.mifare_classic_write_block(block, zeros)
                    return {"success": True}
            except Exception:
                pass
            try:
                for page in range(4, 16):
                    pn532.ntag2xx_write_block(page, b'\x00\x00\x00\x00')
                return {"success": True}
            except Exception as e:
                return {"success": False, "error": str(e)}
    return None


# --- BLE characteristic callbacks ---

def update_status(new_status):
    """Update status characteristic and send notification."""
    global status_value
    status_value = new_status
    if status_char:
        status_char.set_value(encode_str(status_value))
        status_char.changed()
    print(f"[BLE] Status: {new_status}")


def update_nfc_data(data):
    """Update NFC data characteristic and send notification."""
    global nfc_data_value
    nfc_data_value = data
    if nfc_data_char:
        nfc_data_char.set_value(encode_str(nfc_data_value))
        nfc_data_char.changed()
    print(f"[BLE] NFC Data: {data}")


def on_nfc_data_read():
    """Called when browser reads NFC Data characteristic."""
    return encode_str(nfc_data_value)


def on_status_read():
    """Called when browser reads Status characteristic."""
    return encode_str(status_value)


def on_command_write(value, options):
    """Called when browser writes to Command characteristic."""
    cmd = decode_bytes(value)
    print(f"[BLE] Command received: {cmd}")

    # Process command in a background thread so BLE isn't blocked
    thread = threading.Thread(target=process_command, args=(cmd,), daemon=True)
    thread.start()


def process_command(cmd):
    """Process an NFC command from the browser."""
    cmd = cmd.strip()

    if cmd == "READ":
        update_status("waiting")
        result = read_nfc_card(timeout=30)
        if result is None:
            update_nfc_data("")
            update_status("error:timeout")
        else:
            nfc_id = result.get("nfc_id") or ""
            update_nfc_data(nfc_id)
            update_status("success")

    elif cmd.startswith("WRITE:"):
        nfc_id = cmd[6:]
        if not nfc_id:
            update_status("error:missing_id")
            return
        update_status("waiting")
        result = write_nfc_card(nfc_id, timeout=30)
        if result is None:
            update_status("error:timeout")
        elif result.get("success"):
            update_status("success")
        else:
            update_status(f"error:{result.get('error', 'write_failed')}")

    elif cmd == "FORMAT":
        update_status("waiting")
        result = format_nfc_card(timeout=30)
        if result is None:
            update_status("error:timeout")
        elif result.get("success"):
            update_status("success")
        else:
            update_status(f"error:{result.get('error', 'format_failed')}")

    else:
        update_status(f"error:unknown_command")


# --- Main ---

def main():
    global nfc_data_char, status_char

    # Find the default Bluetooth adapter
    adapters = adapter.list_adapters()
    if not adapters:
        print("No Bluetooth adapter found!")
        return
    adapter_address = adapters[0]
    print(f"Using Bluetooth adapter: {adapter_address}")

    # Create peripheral
    nfc_peripheral = peripheral.Peripheral(
        adapter_address,
        local_name="HospitalOS-NFC",
        appearance=0x0000,
    )

    # Add NFC service
    nfc_peripheral.add_service(
        srv_id=1,
        uuid=SERVICE_UUID,
        primary=True,
    )

    # NFC Data characteristic (Read + Notify)
    nfc_peripheral.add_characteristic(
        srv_id=1,
        chr_id=1,
        uuid=NFC_DATA_UUID,
        value=encode_str(""),
        notifying=False,
        flags=["read", "notify"],
        read_callback=on_nfc_data_read,
        write_callback=None,
        notify_callback=None,
    )

    # Command characteristic (Write)
    nfc_peripheral.add_characteristic(
        srv_id=1,
        chr_id=2,
        uuid=COMMAND_UUID,
        value=[],
        notifying=False,
        flags=["write", "write-without-response"],
        read_callback=None,
        write_callback=on_command_write,
        notify_callback=None,
    )

    # Status characteristic (Read + Notify)
    nfc_peripheral.add_characteristic(
        srv_id=1,
        chr_id=3,
        uuid=STATUS_UUID,
        value=encode_str("idle"),
        notifying=False,
        flags=["read", "notify"],
        read_callback=on_status_read,
        write_callback=None,
        notify_callback=None,
    )

    # Store references for notification updates
    # bluezero stores characteristics internally; we access them via the peripheral
    nfc_data_char = nfc_peripheral.characteristics[0]
    status_char = nfc_peripheral.characteristics[2]

    print("Starting BLE advertising as 'HospitalOS-NFC'...")
    print(f"Hardware: {HAS_HARDWARE}, Simulate: {SIMULATE}")
    print(f"Service UUID: {SERVICE_UUID}")

    try:
        nfc_peripheral.publish()
    except KeyboardInterrupt:
        print("\nShutting down BLE NFC server")


if __name__ == "__main__":
    main()
