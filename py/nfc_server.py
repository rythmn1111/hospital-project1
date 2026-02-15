"""
HospitalOS NFC Server
Runs on port 5532, provides REST endpoints for NFC card read/write via PN532.
Falls back to simulation mode if PN532 hardware is not connected.
"""

import json
import uuid
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 5532
SIMULATE = False  # Set True to simulate without hardware

# Try importing PN532 library
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


def read_nfc_card(timeout=30):
    """Wait for a card tap and read the stored NFC ID."""
    if SIMULATE:
        # Simulate: wait a bit, return a fake card
        time.sleep(2)
        # Return None to simulate blank card, or a test ID
        return {"nfc_id": None, "raw": ""}

    start = time.time()
    while time.time() - start < timeout:
        uid = pn532.read_passive_target(timeout=1.0)
        if uid is not None:
            # Try to read data from block 4 (first user data block on NTAG/MIFARE)
            try:
                # For MIFARE Classic: authenticate then read
                key = b'\xFF\xFF\xFF\xFF\xFF\xFF'
                if pn532.mifare_classic_authenticate_block(uid, 4, 0x60, key):
                    data = pn532.mifare_classic_read_block(4)
                    if data:
                        # Read blocks 4,5,6 for full ID (up to 48 bytes)
                        full_data = bytearray()
                        for block in [4, 5, 6]:
                            block_data = pn532.mifare_classic_read_block(block)
                            if block_data:
                                full_data.extend(block_data)
                        text = full_data.decode('utf-8', errors='ignore').strip('\x00').strip()
                        nfc_id = text if text else None
                        return {"nfc_id": nfc_id, "uid": uid.hex()}
            except Exception:
                pass

            # For NTAG213/215/216
            try:
                full_data = bytearray()
                for page in range(4, 16):  # Pages 4-15 = user data
                    page_data = pn532.ntag2xx_read_block(page)
                    if page_data:
                        full_data.extend(page_data)
                text = full_data.decode('utf-8', errors='ignore').strip('\x00').strip()
                nfc_id = text if text else None
                return {"nfc_id": nfc_id, "uid": uid.hex()}
            except Exception:
                return {"nfc_id": None, "uid": uid.hex()}

    return None  # Timeout


def write_nfc_card(nfc_id, timeout=30):
    """Write an NFC ID to a card."""
    if SIMULATE:
        time.sleep(2)
        return {"success": True, "nfc_id": nfc_id}

    start = time.time()
    while time.time() - start < timeout:
        uid = pn532.read_passive_target(timeout=1.0)
        if uid is not None:
            data = nfc_id.encode('utf-8')
            # Pad to 48 bytes (3 blocks of 16)
            data = data.ljust(48, b'\x00')

            try:
                # MIFARE Classic
                key = b'\xFF\xFF\xFF\xFF\xFF\xFF'
                if pn532.mifare_classic_authenticate_block(uid, 4, 0x60, key):
                    for i, block in enumerate([4, 5, 6]):
                        chunk = data[i*16:(i+1)*16]
                        pn532.mifare_classic_write_block(block, chunk)
                    return {"success": True, "nfc_id": nfc_id}
            except Exception:
                pass

            try:
                # NTAG: write 4 bytes per page
                padded = data.ljust(48, b'\x00')
                for i in range(12):  # Pages 4-15
                    page_data = padded[i*4:(i+1)*4]
                    pn532.ntag2xx_write_block(4 + i, page_data)
                return {"success": True, "nfc_id": nfc_id}
            except Exception as e:
                return {"success": False, "error": str(e)}

    return None  # Timeout


def format_nfc_card(timeout=30):
    """Wipe card data (write zeros)."""
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


class NFCHandler(BaseHTTPRequestHandler):
    def _send_json(self, status, data):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_OPTIONS(self):
        self._send_json(200, {})

    def do_GET(self):
        if self.path == '/status':
            self._send_json(200, {
                "status": "ok",
                "hardware": HAS_HARDWARE,
                "simulate": SIMULATE
            })
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b'{}'
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {}

        if self.path == '/read':
            timeout = payload.get('timeout', 30)
            result = read_nfc_card(timeout=timeout)
            if result is None:
                self._send_json(408, {"error": "Timeout — no card detected"})
            else:
                self._send_json(200, result)

        elif self.path == '/write':
            nfc_id = payload.get('nfc_id')
            if not nfc_id:
                self._send_json(400, {"error": "nfc_id is required"})
                return
            timeout = payload.get('timeout', 30)
            result = write_nfc_card(nfc_id, timeout=timeout)
            if result is None:
                self._send_json(408, {"error": "Timeout — no card detected"})
            else:
                self._send_json(200, result)

        elif self.path == '/format':
            timeout = payload.get('timeout', 30)
            result = format_nfc_card(timeout=timeout)
            if result is None:
                self._send_json(408, {"error": "Timeout — no card detected"})
            else:
                self._send_json(200, result)

        else:
            self._send_json(404, {"error": "Not found"})

    def log_message(self, format, *args):
        print(f"[NFC] {args[0]}")


if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', PORT), NFCHandler)
    print(f"NFC Server running on port {PORT}")
    print(f"Hardware: {HAS_HARDWARE}, Simulate: {SIMULATE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down NFC server")
        server.server_close()
