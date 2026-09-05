"""HTTP/JSON client for the in-process ZWMechMCP ZRX bridge.

The wrapper classes mirror the pyzwcadmech surface used by server.py.  They
keep mechanical calls in the ZWCAD process, avoiding Python-side generation of
the ZwmToolKit type library.
"""

import json
import os
import urllib.request


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 17890


class MechBridgeError(RuntimeError):
    """The ZRX bridge could not complete a request."""


class MechBridge:
    """Low-level client for the localhost bridge."""

    def __init__(self, host=None, port=None, timeout=30):
        self.host = host or os.environ.get("ZWMECH_BRIDGE_HOST", DEFAULT_HOST)
        port = port or os.environ.get("ZWMECH_BRIDGE_PORT")
        self.port = int(port) if port else DEFAULT_PORT
        self.timeout = timeout

    def call(self, method, **params):
        body = json.dumps(
            {"method": method, "params": params}, ensure_ascii=False
        ).encode("utf-8")
        request = urllib.request.Request(
            f"http://{self.host}:{self.port}/call",
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise MechBridgeError(
                f"Cannot connect to ZWMechMCP bridge ({self.host}:{self.port}). "
                "Ensure ZWCAD Mechanical is running and ZWMechMCP.zrx is loaded. "
                f"Original error: {exc}"
            ) from exc

        if not payload.get("ok"):
            raise MechBridgeError(str(payload.get("error", "unknown bridge error")))
        return payload.get("data", {})

    def ping(self):
        return self.call("ping")


_FRAME_STR_PROPS = (
    "std_name", "title_style_name", "bom_style_name", "dhl_style_name",
    "fjl_style_name", "csl_style_name", "ggl_style_name", "scale1",
    "scale2", "frame_size_name", "frame_style_name", "orientation",
)
_FRAME_LONG_PROPS = ("width", "height")
_FRAME_BOOL_PROPS = ("have_dhl", "have_fjl", "have_btl", "have_csl", "have_ggl")
FRAME_PROPS = _FRAME_STR_PROPS + _FRAME_LONG_PROPS + _FRAME_BOOL_PROPS


class ZwmTitle:
    def __init__(self, bridge, items):
        self._bridge = bridge
        self._items = items

    def get_item_count(self):
        return len(self._items)

    def get_item(self, index):
        item = self._items[index]
        return item.get("label", ""), item.get("name", ""), item.get("value", "")

    def set_item(self, key, value):
        self._bridge.call("title_set_item", key=key, value=str(value))


class ZwmBomRow:
    """A BOM row whose changes are staged until the parent BOM submits it."""

    def __init__(self, bridge, items=None):
        self._bridge = bridge
        self._items = items or []
        self._pending = {}

    def get_item_count(self):
        return len(self._items)

    def get_item(self, index):
        item = self._items[index]
        return item.get("label", ""), item.get("name", ""), item.get("value", "")

    def set_item(self, key, value):
        self._pending[key] = str(value)


class ZwmBom:
    def __init__(self, bridge):
        self._bridge = bridge

    def get_item_count(self):
        return self._bridge.call("bom_get_item_count").get("count", 0)

    def _rows(self):
        return self._bridge.call("bom_get_items").get("rows", [])

    def get_item(self, index):
        rows = self._rows()
        if index < 0 or index >= len(rows):
            return None
        return ZwmBomRow(self._bridge, rows[index])

    def get_items(self):
        return [ZwmBomRow(self._bridge, row) for row in self._rows()]

    def create_bom_row(self):
        return ZwmBomRow(self._bridge)

    def set_item(self, index, bom_row):
        self._bridge.call("bom_set_item", index=index, fields=bom_row._pending)

    def add_item(self, bom_row):
        self._bridge.call("bom_add_item", fields=bom_row._pending)

    def insert_item(self, index, bom_row):
        self._bridge.call("bom_insert_item", index=index, fields=bom_row._pending)

    def delete_item(self, index):
        self._bridge.call("bom_delete_item", index=index)


def _normalize_frame_value(name, value):
    if name in _FRAME_BOOL_PROPS:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if name in _FRAME_LONG_PROPS:
        return int(float(value))
    return value


class ZwmFrame:
    def __init__(self, bridge, data):
        object.__setattr__(self, "_bridge", bridge)
        object.__setattr__(self, "_data", dict(data))

    def __getattr__(self, name):
        if name in FRAME_PROPS:
            return self._data.get(name)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name in FRAME_PROPS:
            self.set_props({name: value})
        else:
            object.__setattr__(self, name, value)

    def set_props(self, props):
        normalized = {key: _normalize_frame_value(key, value) for key, value in props.items()}
        result = self._bridge.call("frame_set", props=normalized)
        self._data.update(normalized)
        return result.get("updated", list(normalized))


class _NextFrameInfo:
    def __init__(self, width, height):
        self.width = width
        self.height = height


class ZwmApp:
    def __init__(self, bridge):
        self._bridge = bridge

    def get_version(self):
        return self._bridge.call("get_version").get("version", "")

    def get_about(self):
        return self._bridge.call("get_about").get("about", "")

    def get_cad_path(self):
        return self._bridge.call("get_cad_path").get("path", "")

    def get_zwm_path(self):
        return self._bridge.call("get_zwm_path").get("path", "")

    def get_style_path(self):
        return self._bridge.call("get_style_path").get("path", "")

    def send_command(self, command):
        self._bridge.call("send_command", cmd=command)

    def open_doc(self, file_path):
        self._bridge.call("open_doc", file_path=file_path)

    def new_doc(self, file_path):
        self._bridge.call("new_doc", file_path=file_path)

    def new_named_doc(self, file_path, template):
        self._bridge.call("new_named_doc", file_path=file_path, template=template)


class ZwmDb:
    def __init__(self, bridge):
        self._bridge = bridge

    def open_file(self, filepath):
        self._bridge.call("open_file", file_path=filepath)

    def save(self, flag=33):
        self._bridge.call("save", flag=flag)

    def close(self):
        self._bridge.call("close")

    def switch_frame(self, frame_name):
        self._bridge.call("frame_switch", frame_name=frame_name)

    def get_title(self):
        data = self._bridge.call("title_get_items")
        return ZwmTitle(self._bridge, data.get("items", [])) if data.get("found") else None

    def get_bom(self):
        data = self._bridge.call("bom_get_item_count")
        return ZwmBom(self._bridge) if data.get("found") else None

    def get_frame(self):
        data = self._bridge.call("frame_get")
        return ZwmFrame(self._bridge, data) if data.get("found") else None

    def get_next_frm_name(self):
        data = self._bridge.call("frame_get_next_name")
        name = data.get("name", "") or ""
        if data.get("has_frame"):
            return _NextFrameInfo(data.get("width"), data.get("height")), name
        return None, name

    def refresh_title(self):
        self._bridge.call("title_refresh")

    def refresh_bom(self):
        self._bridge.call("bom_refresh")

    def refresh_frame(self):
        self._bridge.call("frame_refresh")

    def build_frame(self, switch_type=511):
        self._bridge.call("frame_build", mask=switch_type)

    def get_frame_count(self):
        return self._bridge.call("frame_list").get("count", 0)

    def get_frame_name(self, index):
        return self._bridge.call("frame_get_name", index=index).get("name", "")

    def get_frame_name2(self, point):
        return self._bridge.call(
            "frame_get_name2", x=point[0], y=point[1], z=point[2] if len(point) > 2 else 0
        ).get("name", "")

    def cad_environment_init(self, std_name):
        self._bridge.call("cad_environment_init", std_name=std_name)

    def get_balloon(self, text=""):
        data = self._bridge.call("balloon_get", text=text)
        return data if data.get("found") else None


class ZwCADMech:
    """Drop-in replacement for the pyzwcadmech calls used by this project."""

    def __init__(self, cad_app=None, host=None, port=None, timeout=30):
        self._bridge = MechBridge(host=host, port=port, timeout=timeout)
        self._zwm_app = ZwmApp(self._bridge)
        self._zwm_db = ZwmDb(self._bridge)

    @property
    def bridge(self):
        return self._bridge

    @property
    def zwm_app(self):
        return self._zwm_app

    @property
    def zwm_db(self):
        return self._zwm_db

    def open_file(self, filepath=""):
        self._zwm_db.open_file(filepath)

    def close(self):
        self._zwm_db.close()

    def save(self, flag=33):
        self._zwm_db.save(flag)

    def get_title(self):
        return self._zwm_db.get_title()

    def get_bom(self):
        return self._zwm_db.get_bom()

    def get_frame(self):
        return self._zwm_db.get_frame()

    def insert_balloon(self, arrow, symbol, text="3", seq_type=2, has_leader=False, mode=0):
        return self._bridge.call(
            "balloon_insert",
            arrow={"x": arrow[0], "y": arrow[1], "z": arrow[2] if len(arrow) > 2 else 0.0},
            symbol={"x": symbol[0], "y": symbol[1], "z": symbol[2] if len(symbol) > 2 else 0.0},
            text=text,
            seq_type=seq_type,
            has_leader=has_leader,
            mode=mode,
        )

    def diagnose_environment(self):
        result = {"bridge_host": self._bridge.host, "bridge_port": self._bridge.port}
        try:
            result["plugin_info"] = self._bridge.ping()
            result["bridge_ok"] = True
        except Exception as exc:
            result["bridge_ok"] = False
            result["bridge_error"] = str(exc)
        return result
