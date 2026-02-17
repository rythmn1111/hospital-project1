"""
HospitalOS BLE NFC Server
Runs on Pi Zero 2 W. Advertises a BLE GATT service that allows
browsers (via Web Bluetooth) to read/write NFC cards through a PN532 module.
Falls back to simulation mode if PN532 hardware is not connected.

Uses BlueZ D-Bus API directly for reliable BLE advertising + GATT.
"""

import time
import threading
import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

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

# --- UUIDs ---
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
NFC_DATA_UUID = "12345678-1234-5678-1234-56789abcdef1"
COMMAND_UUID = "12345678-1234-5678-1234-56789abcdef2"
STATUS_UUID = "12345678-1234-5678-1234-56789abcdef3"

# --- D-Bus constants ---
BLUEZ_SERVICE = "org.bluez"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"

mainloop = None


# ============================================================
# NFC operations (same as nfc_server.py)
# ============================================================

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


# ============================================================
# BLE Advertisement (registers with BlueZ LEAdvertisingManager)
# ============================================================

class Advertisement(dbus.service.Object):
    PATH_BASE = "/org/bluez/hospitalos/advertisement"

    def __init__(self, bus, index):
        self.path = f"{self.PATH_BASE}{index}"
        self.bus = bus
        self.ad_type = "peripheral"
        self.local_name = "HospitalOS-NFC"
        self.service_uuids = [SERVICE_UUID]
        self.include_tx_power = True
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        props = {
            LE_ADVERTISEMENT_IFACE: {
                "Type": self.ad_type,
                "LocalName": dbus.String(self.local_name),
                "ServiceUUIDs": dbus.Array(self.service_uuids, signature="s"),
                "IncludeTxPower": dbus.Boolean(self.include_tx_power),
            }
        }
        return props

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != LE_ADVERTISEMENT_IFACE:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs",
                f"Unknown interface: {interface}",
            )
        return self.get_properties()[LE_ADVERTISEMENT_IFACE]

    @dbus.service.method(LE_ADVERTISEMENT_IFACE, in_signature="", out_signature="")
    def Release(self):
        print("[BLE] Advertisement released")


# ============================================================
# GATT Application (service + characteristics)
# ============================================================

class Application(dbus.service.Object):
    PATH = "/org/bluez/hospitalos"

    def __init__(self, bus):
        self.path = self.PATH
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        self.services.append(service)

    @dbus.service.method(DBUS_OM_IFACE, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            for chrc in service.characteristics:
                response[chrc.get_path()] = chrc.get_properties()
        return response


class Service(dbus.service.Object):
    PATH_BASE = "/org/bluez/hospitalos/service"

    def __init__(self, bus, index, uuid, primary):
        self.path = f"{self.PATH_BASE}{index}"
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, chrc):
        self.characteristics.append(chrc)

    def get_properties(self):
        return {
            GATT_SERVICE_IFACE: {
                "UUID": self.uuid,
                "Primary": self.primary,
                "Characteristics": dbus.Array(
                    [c.get_path() for c in self.characteristics],
                    signature="o",
                ),
            }
        }

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != GATT_SERVICE_IFACE:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs",
                f"Unknown interface: {interface}",
            )
        return self.get_properties()[GATT_SERVICE_IFACE]


class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.path = f"{service.path}/char{index}"
        self.bus = bus
        self.uuid = uuid
        self.flags = flags
        self.service = service
        self.value = []
        self.notifying = False
        dbus.service.Object.__init__(self, bus, self.path)
        service.add_characteristic(self)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        return {
            GATT_CHRC_IFACE: {
                "Service": self.service.get_path(),
                "UUID": self.uuid,
                "Flags": self.flags,
            }
        }

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != GATT_CHRC_IFACE:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs",
                f"Unknown interface: {interface}",
            )
        return self.get_properties()[GATT_CHRC_IFACE]

    @dbus.service.method(GATT_CHRC_IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        return self.value

    @dbus.service.method(GATT_CHRC_IFACE, in_signature="aya{sv}")
    def WriteValue(self, value, options):
        self.value = value

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self):
        self.notifying = True

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        self.notifying = False

    @dbus.service.signal(DBUS_PROP_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

    def send_notify(self, value):
        """Update value and send notification if subscribed."""
        self.value = value
        if self.notifying:
            self.PropertiesChanged(
                GATT_CHRC_IFACE,
                {"Value": dbus.Array(value, signature="y")},
                [],
            )


# ============================================================
# Our concrete characteristics
# ============================================================

class NfcDataCharacteristic(Characteristic):
    def __init__(self, bus, service):
        super().__init__(bus, 0, NFC_DATA_UUID, ["read", "notify"], service)
        self.value = dbus.Array([], signature="y")


class CommandCharacteristic(Characteristic):
    def __init__(self, bus, service, on_write):
        super().__init__(bus, 1, COMMAND_UUID, ["write", "write-without-response"], service)
        self.on_write = on_write

    @dbus.service.method(GATT_CHRC_IFACE, in_signature="aya{sv}")
    def WriteValue(self, value, options):
        cmd = bytes(value).decode("utf-8", errors="ignore").strip("\x00")
        print(f"[BLE] Command received: {cmd}")
        self.on_write(cmd)


class StatusCharacteristic(Characteristic):
    def __init__(self, bus, service):
        super().__init__(bus, 2, STATUS_UUID, ["read", "notify"], service)
        self.value = dbus.Array(b"idle", signature="y")


# ============================================================
# Command handler
# ============================================================

class NfcCommandHandler:
    def __init__(self, nfc_data_chrc, status_chrc):
        self.nfc_data = nfc_data_chrc
        self.status = status_chrc

    def _set_status(self, s):
        print(f"[BLE] Status: {s}")
        self.status.send_notify(dbus.Array(s.encode("utf-8"), signature="y"))

    def _set_nfc_data(self, d):
        print(f"[BLE] NFC Data: {d}")
        self.nfc_data.send_notify(dbus.Array(d.encode("utf-8"), signature="y"))

    def handle(self, cmd):
        # Run in background thread so BLE main loop isn't blocked
        thread = threading.Thread(target=self._process, args=(cmd,), daemon=True)
        thread.start()

    def _process(self, cmd):
        cmd = cmd.strip()

        if cmd == "READ":
            GLib.idle_add(self._set_status, "waiting")
            result = read_nfc_card(timeout=30)
            if result is None:
                GLib.idle_add(self._set_nfc_data, "")
                GLib.idle_add(self._set_status, "error:timeout")
            else:
                nfc_id = result.get("nfc_id") or ""
                GLib.idle_add(self._set_nfc_data, nfc_id)
                GLib.idle_add(self._set_status, "success")

        elif cmd.startswith("WRITE:"):
            nfc_id = cmd[6:]
            if not nfc_id:
                GLib.idle_add(self._set_status, "error:missing_id")
                return
            GLib.idle_add(self._set_status, "waiting")
            result = write_nfc_card(nfc_id, timeout=30)
            if result is None:
                GLib.idle_add(self._set_status, "error:timeout")
            elif result.get("success"):
                GLib.idle_add(self._set_status, "success")
            else:
                GLib.idle_add(self._set_status, f"error:{result.get('error', 'write_failed')}")

        elif cmd == "FORMAT":
            GLib.idle_add(self._set_status, "waiting")
            result = format_nfc_card(timeout=30)
            if result is None:
                GLib.idle_add(self._set_status, "error:timeout")
            elif result.get("success"):
                GLib.idle_add(self._set_status, "success")
            else:
                GLib.idle_add(self._set_status, f"error:{result.get('error', 'format_failed')}")

        else:
            GLib.idle_add(self._set_status, "error:unknown_command")


# ============================================================
# Main
# ============================================================

def find_adapter(bus):
    """Find the first Bluetooth adapter object path."""
    remote_om = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE, "/"), DBUS_OM_IFACE
    )
    objects = remote_om.GetManagedObjects()
    for path, interfaces in objects.items():
        if LE_ADVERTISING_MANAGER_IFACE in interfaces:
            return path
    return None


def main():
    global mainloop

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    adapter_path = find_adapter(bus)
    if not adapter_path:
        print("No BLE adapter found! Is Bluetooth enabled?")
        return

    print(f"Using adapter: {adapter_path}")

    # Power on the adapter and set alias
    adapter_props = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE, adapter_path), DBUS_PROP_IFACE
    )
    adapter_props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
    adapter_props.Set("org.bluez.Adapter1", "Alias", dbus.String("HospitalOS-NFC"))

    # --- Register GATT application ---
    app = Application(bus)
    service = Service(bus, 0, SERVICE_UUID, True)

    nfc_data_chrc = NfcDataCharacteristic(bus, service)
    status_chrc = StatusCharacteristic(bus, service)
    handler = NfcCommandHandler(nfc_data_chrc, status_chrc)
    command_chrc = CommandCharacteristic(bus, service, handler.handle)

    app.add_service(service)

    gatt_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE, adapter_path), GATT_MANAGER_IFACE
    )
    gatt_manager.RegisterApplication(
        app.get_path(), {},
        reply_handler=lambda: print("[BLE] GATT application registered"),
        error_handler=lambda e: print(f"[BLE] Failed to register GATT: {e}"),
    )

    # --- Register BLE advertisement ---
    ad = Advertisement(bus, 0)
    ad_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE, adapter_path), LE_ADVERTISING_MANAGER_IFACE
    )
    ad_manager.RegisterAdvertisement(
        ad.get_path(), {},
        reply_handler=lambda: print("[BLE] Advertisement registered"),
        error_handler=lambda e: print(f"[BLE] Failed to register advertisement: {e}"),
    )

    print("Advertising as 'HospitalOS-NFC' via BLE...")
    print(f"Hardware: {HAS_HARDWARE}, Simulate: {SIMULATE}")
    print(f"Service UUID: {SERVICE_UUID}")

    mainloop = GLib.MainLoop()
    try:
        mainloop.run()
    except KeyboardInterrupt:
        print("\nShutting down BLE NFC server")
        ad_manager.UnregisterAdvertisement(ad.get_path())
        mainloop.quit()


if __name__ == "__main__":
    main()
