"""Exact window capture and a private, allowlisted Cua Driver MCP client."""

import ctypes as ct
from ctypes import wintypes as wt
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib


VERSION = "0.53.0"
BACKEND = "cua-driver"
HERE = Path(__file__).resolve().parent
VENDOR = HERE / "vendor" / "cua"
BINARIES = {
    "cua-driver.exe": "6af3b8bb340caf3578af23cb34e6ec6a9cd29e0144a66801a85da7ac033f516b",
    "cua-driver-uia.exe": "4e1475f720b27e0b53c26b8a91be8587d846cba2c5b2b8e5edeb31c2722b7b7e",
}
MAX_PIXELS = 20_000_000
# A native RGBA PNG with base64 expansion plus metadata must fit on one MCP line.
MAX_WIRE = 128 * 1024 * 1024
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class DriverError(ValueError):
    """A concise adapter failure safe for the outer MCP to report."""


@dataclass(frozen=True)
class CaptureContext:
    hwnd: int
    pid: int
    width: int
    height: int
    frame: tuple
    source: str = "win32-printwindow"


def _bind(dll, name, result, *arguments):
    function = getattr(dll, name)
    function.argtypes = arguments
    function.restype = result
    return function


class _BitmapHeader(ct.Structure):
    _fields_ = [
        ("size", wt.DWORD), ("width", wt.LONG), ("height", wt.LONG),
        ("planes", wt.WORD), ("bits", wt.WORD), ("compression", wt.DWORD),
        ("image_size", wt.DWORD), ("x_density", wt.LONG), ("y_density", wt.LONG),
        ("colors_used", wt.DWORD), ("colors_important", wt.DWORD),
    ]


class _WindowAPI:
    def __init__(self):
        user = ct.WinDLL("user32", use_last_error=True)
        dwm = ct.WinDLL("dwmapi", use_last_error=True)
        self.owner = _bind(user, "GetWindowThreadProcessId", wt.DWORD, wt.HWND, ct.POINTER(wt.DWORD))
        self.ancestor = _bind(user, "GetAncestor", wt.HWND, wt.HWND, wt.UINT)
        self.visible = _bind(user, "IsWindowVisible", wt.BOOL, wt.HWND)
        self.iconic = _bind(user, "IsIconic", wt.BOOL, wt.HWND)
        self.rect = _bind(user, "GetWindowRect", wt.BOOL, wt.HWND, ct.POINTER(wt.RECT))
        self.attribute = _bind(dwm, "DwmGetWindowAttribute", ct.c_long, wt.HWND, wt.DWORD, ct.c_void_p, wt.DWORD)
        self.dpi_context = _bind(user, "SetThreadDpiAwarenessContext", wt.HANDLE, wt.HANDLE)
        self.window_dpi = _bind(user, "GetDpiForWindow", wt.UINT, wt.HWND)
        self.foreground = _bind(user, "GetForegroundWindow", wt.HWND)
        self.at_point = _bind(user, "WindowFromPoint", wt.HWND, wt.POINT)
        self.print_window = _bind(user, "PrintWindow", wt.BOOL, wt.HWND, wt.HDC, wt.UINT)
        self.affinity = _bind(user, "GetWindowDisplayAffinity", wt.BOOL, wt.HWND, ct.POINTER(wt.DWORD))

    def validate(self, hwnd, pid):
        if (type(hwnd) is not int or not 0 < hwnd < 2**63
                or type(pid) is not int or not 0 < pid <= 0xFFFFFFFF):
            raise DriverError("Invalid window handle or process ID")
        owner = wt.DWORD()
        thread = self.owner(hwnd, ct.byref(owner))
        if not thread or owner.value != pid or self.ancestor(hwnd, 2) != hwnd:
            raise DriverError("Target window is no longer valid for its process")
        return thread

    def frame(self, hwnd, pid):
        thread = self.validate(hwnd, pid)
        if not self.visible(hwnd) or self.iconic(hwnd):
            raise DriverError("The target window is hidden or minimized")
        cloaked = wt.DWORD()
        if self.attribute(hwnd, 14, ct.byref(cloaked), ct.sizeof(cloaked)) != 0 or cloaked.value:
            raise DriverError("The target window is cloaked or unavailable")
        protection = wt.DWORD()
        if self.affinity(hwnd, ct.byref(protection)) and protection.value:
            raise DriverError("The target window excludes screen capture")
        previous = self.dpi_context(ct.c_void_p(-4))  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if not previous:
            raise DriverError("Could not establish physical pixel coordinates")
        try:
            window, dwm = wt.RECT(), wt.RECT()
            if not self.rect(hwnd, ct.byref(window)):
                raise DriverError("Could not read the target window bounds")
            outer = window.left, window.top, window.right, window.bottom
            if self.attribute(hwnd, 9, ct.byref(dwm), ct.sizeof(dwm)) == 0:
                # Cua 0.53.0's bitmap_to_screen uses the DWM bounds with this inset.
                crop = dwm.left + 1, dwm.top + 1, dwm.right - 1, dwm.bottom - 1
            else:
                crop = outer
        finally:
            self.dpi_context(previous)
        left, top, right, bottom = crop
        if not outer[0] <= left < right <= outer[2] or not outer[1] <= top < bottom <= outer[3]:
            raise DriverError("Could not establish the target window's pixel frame")
        dpi = self.window_dpi(hwnd)
        if not dpi:
            raise DriverError("Could not determine the target window DPI")
        return thread, outer, crop, dpi

    def require_uncovered(self, hwnd, points):
        previous = self.dpi_context(ct.c_void_p(-4))
        if not previous:
            raise DriverError("Could not verify the window at the input point")
        try:
            for x, y in points:
                hit = self.at_point(wt.POINT(x, y))
                if not hit or self.ancestor(hit, 2) != hwnd:
                    raise DriverError("Another window covers the input point. No input was sent.")
        finally:
            self.dpi_context(previous)


def _png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _print_window(hwnd, pid):
    """Run in a child so a hung window cannot block the main MCP server."""
    api = _WindowAPI()
    frame = api.frame(hwnd, pid)
    _, (left, top, right, bottom), (crop_left, crop_top, crop_right, crop_bottom), _ = frame
    width, height = right - left, bottom - top
    if width * height > MAX_PIXELS:
        raise DriverError("The target window exceeds the capture size limit")
    gdi = ct.WinDLL("gdi32", use_last_error=True)
    create_dc = _bind(gdi, "CreateCompatibleDC", wt.HDC, wt.HDC)
    create_bitmap = _bind(gdi, "CreateDIBSection", wt.HBITMAP, wt.HDC, ct.c_void_p, wt.UINT,
                          ct.POINTER(ct.c_void_p), wt.HANDLE, wt.DWORD)
    select_object = _bind(gdi, "SelectObject", wt.HGDIOBJ, wt.HDC, wt.HGDIOBJ)
    delete_object = _bind(gdi, "DeleteObject", wt.BOOL, wt.HGDIOBJ)
    delete_dc = _bind(gdi, "DeleteDC", wt.BOOL, wt.HDC)
    flush = _bind(gdi, "GdiFlush", wt.BOOL)
    previous = api.dpi_context(ct.c_void_p(-4))
    dc = bitmap = old_bitmap = None
    try:
        if not previous or not (dc := create_dc(None)):
            raise DriverError("Could not allocate private window capture resources")
        header = _BitmapHeader(ct.sizeof(_BitmapHeader), width, -height, 1, 32)
        pixels = ct.c_void_p()
        bitmap = create_bitmap(dc, ct.byref(header), 0, ct.byref(pixels), None, 0)
        if not bitmap or not pixels.value:
            raise DriverError("Could not allocate the target window bitmap")
        old_bitmap = select_object(dc, bitmap)
        if not old_bitmap or old_bitmap == ct.c_void_p(-1).value:
            raise DriverError("Could not select the target window bitmap")
        ct.memset(pixels, 0, width * height * 4)
        # Only the exact HWND can contribute pixels. Never copy a screen DC.
        if not api.print_window(hwnd, dc, 2) or not flush():  # PW_RENDERFULLCONTENT
            raise DriverError("The target window did not render into the capture bitmap")
        raw = ct.string_at(pixels, width * height * 4)
    finally:
        if dc and old_bitmap and old_bitmap != ct.c_void_p(-1).value:
            select_object(dc, old_bitmap)
        if bitmap:
            delete_object(bitmap)
        if dc:
            delete_dc(dc)
        if previous:
            api.dpi_context(previous)
    if api.frame(hwnd, pid) != frame:
        raise DriverError("Target window changed during capture")
    out_width, out_height = crop_right - crop_left, crop_bottom - crop_top
    rows = bytearray()
    has_content = False
    for y in range(crop_top - top, crop_bottom - top):
        start = (y * width + crop_left - left) * 4
        bgra = raw[start:start + out_width * 4]
        rgb = bytearray(out_width * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
        has_content = has_content or bool(rgb.strip(b"\0"))
        rows.append(0)
        rows.extend(rgb)
    if not has_content:
        raise DriverError("The target returned a blank capture frame")
    png = (PNG_SIGNATURE + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", out_width, out_height, 8, 2, 0, 0, 0))
           + _png_chunk(b"IDAT", zlib.compress(rows, 3)) + _png_chunk(b"IEND", b""))
    return frame, png


_ACTION_FIELDS = {
    "click": {"x", "y"}, "double_click": {"x", "y"}, "right_click": {"x", "y"},
    "drag": {"from_x", "from_y", "to_x", "to_y", "duration_ms"},
    "type_text": {"text", "x", "y", "delay_ms"},
    "press_key": {"key", "modifiers", "x", "y"},
    "hotkey": {"keys", "x", "y"},
    "scroll": {"direction", "amount", "by", "x", "y"},
}
_SAFE_CODES = {
    "background_unavailable", "background_occluded", "background_uipi_blocked",
    "background_delivery_failed", "background_provider_unavailable", "invalid_arguments", "target_changed",
    "capture_target_mismatch", "capture_frame_mismatch", "capture_coordinate_invalid", "capture_not_found",
    "foreground_unavailable", "target_not_found", "unsupported_action", "no_target", "type_text_noop",
}
_SAFE_ROUTES = {"accessibility", "synthetic_events", "global_input", "system_api", "dom", "trusted_input",
                "pixel", "ax", "uia", "post_message"}
_SAFE_EFFECTS = {"confirmed", "partial", "suspected_noop", "unverifiable", "refused", "changed", "unknown"}


def _safe_result(response, mode, action):
    if not isinstance(response, dict) or type(response.get("isError", False)) is not bool:
        raise DriverError("Cua Driver returned an invalid input result. Delivery status is unknown.")
    record = response.get("structuredContent")
    record = record if isinstance(record, dict) else {}
    raw_error = record.get("error")
    code = raw_error.get("code") if isinstance(raw_error, dict) else record.get("code")
    error = response.get("isError", False) or record.get("effect") == "refused"
    result = {"backend": BACKEND, "backend_version": VERSION, "action": action,
              "requested_delivery": mode, "status": "driver_error" if error else "dispatched"}
    if isinstance(code, str) and code in _SAFE_CODES:
        result["code"] = code
    if error:
        if record.get("effect") == "refused":
            result["status"] = "refused"
        result["delivery_verified"] = False
    route = record.get("route", record.get("path"))
    effect = record.get("effect")
    if isinstance(route, str) and route in _SAFE_ROUTES:
        result["route"] = route
    if isinstance(effect, str) and effect in _SAFE_EFFECTS:
        result["effect"] = effect
    delivery = record.get("delivery")
    if isinstance(delivery, dict):
        reported = delivery.get("mode")
        if reported in ("background", "foreground", "not_applicable", "unknown"):
            result["delivery_mode"] = reported
        count = delivery.get("delivered_count")
        if type(count) is int and 0 <= count <= 65536:
            result["delivered_count"] = count
    if not error:
        result["delivery_verified"] = record.get("verified") is True or effect == "confirmed"
    return result


class Driver:
    def __init__(self):
        self._lock = threading.RLock()
        self._process = None
        self._output = None
        self._state = None
        self._next_id = 0
        self._window = None

    def _api(self):
        if os.name != "nt":
            raise DriverError("The window driver is available on Windows only")
        if self._window is None:
            self._window = _WindowAPI()
        return self._window

    def validate_capture(self, hwnd, pid, context):
        if not isinstance(context, CaptureContext) or (hwnd, pid) != (context.hwnd, context.pid):
            raise DriverError("Coordinate input requires the target window's current capture")
        if self._api().frame(hwnd, pid) != context.frame:
            raise DriverError("The target pixel frame has changed. Capture the window again.")

    def capture(self, hwnd, pid):
        before = self._api().frame(hwnd, pid)
        try:
            process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--capture", str(hwnd), str(pid)],
                                     stdin=subprocess.DEVNULL, capture_output=True, timeout=6, creationflags=NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DriverError("The target window capture failed or timed out") from exc
        if process.returncode:
            if process.returncode == 2 and len(process.stderr) <= 200:
                raise DriverError(process.stderr.decode("ascii", errors="replace").strip())
            raise DriverError("The target window capture failed")
        frame_line, separator, png = process.stdout.partition(b"\n")
        if not separator or len(frame_line) > 256 or len(png) < 32 or not png.startswith(PNG_SIGNATURE):
            raise DriverError("The target window capture returned invalid data")
        if (frame_line != json.dumps(before, separators=(",", ":")).encode("ascii")
                or self._api().frame(hwnd, pid) != before):
            raise DriverError("Target window changed during capture")
        width, height = struct.unpack_from(">II", png, 16)
        x0, y0, x1, y1 = before[2]
        if (width, height) != (x1 - x0, y1 - y0):
            raise DriverError("The captured image did not match the target window frame")
        return png, CaptureContext(hwnd, pid, width, height, before)

    def _start(self):
        self.close()
        for name, expected in BINARIES.items():
            try:
                with (VENDOR / name).open("rb") as handle:
                    digest = hashlib.file_digest(handle, "sha256").hexdigest()
            except OSError as exc:
                raise DriverError("The bundled Cua Driver executable is unavailable") from exc
            if digest != expected:
                raise DriverError("The bundled Cua Driver executable failed integrity validation")
        self._state = tempfile.TemporaryDirectory(prefix="windows-desktop-mcp-cua-")
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("CUA_")}
        env.update({"CUA_DRIVER_HOME": self._state.name, "CUA_DRIVER_RS_TELEMETRY_ENABLED": "0",
                    "DO_NOT_TRACK": "1", "RUST_LOG": "off"})
        try:
            self._process = subprocess.Popen([str(VENDOR / "cua-driver.exe"), "mcp", "--direct", "--embedded", "--no-overlay"],
                                             cwd=self._state.name, env=env, stdin=subprocess.PIPE,
                                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
            process = self._process
            out = self._output = queue.Queue(maxsize=8)

            def read():
                try:
                    while line := process.stdout.readline(MAX_WIRE + 1):
                        if len(line) > MAX_WIRE or not line.endswith(b"\n"):
                            break
                        out.put(line, timeout=1)
                except (OSError, ValueError, queue.Full):
                    pass
                finally:
                    try:
                        out.put_nowait(None)
                    except queue.Full:
                        pass

            threading.Thread(target=read, daemon=True).start()
            result = self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                               "clientInfo": {"name": "windows-desktop-mcp", "version": "1"}})
            info = result.get("serverInfo", {})
            if not isinstance(info, dict) or info.get("name") != BACKEND or info.get("version") != VERSION:
                raise DriverError("The bundled driver returned an unexpected version")
            self._write({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except (OSError, ValueError, queue.Empty) as exc:
            self.close()
            raise DriverError("Could not initialize the private Cua Driver process") from exc

    def _write(self, message):
        self._process.stdin.write(json.dumps(message, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n")
        self._process.stdin.flush()

    def _rpc(self, method, params):
        self._next_id += 1
        request_id = self._next_id
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + 15
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise queue.Empty
            line = self._output.get(timeout=remaining)
            if line is None:
                raise DriverError("The private Cua Driver process became unavailable")
            response = json.loads(line)
            if not isinstance(response, dict) or response.get("jsonrpc") != "2.0":
                raise DriverError("The private Cua Driver returned an invalid response")
            if "id" not in response:
                continue
            if response["id"] != request_id or not isinstance(response.get("result"), dict):
                raise DriverError("The private Cua Driver returned a failed request")
            return response["result"]

    def _register_coordinate_frame(self, hwnd, pid, context):
        # Cua consumes its own per-window screenshot context to translate pixel actions.
        # Discard the private screenshot bytes in memory. Only PrintWindow's pixels leave the adapter.
        reply = self._rpc("tools/call", {"name": "get_window_state", "arguments": {
            "pid": pid, "window_id": hwnd, "include_accessibility_tree": False,
            "include_screenshot": True, "max_image_dimension": 0,
        }})
        state = reply.get("structuredContent")
        if (reply.get("isError") or not isinstance(state, dict)
                or (state.get("window_id"), state.get("pid")) != (hwnd, pid)
                or (state.get("screenshot_width"), state.get("screenshot_height")) != (context.width, context.height)
                or state.get("screenshot_mime_type") != "image/png"):
            raise DriverError("Cua Driver could not establish a matching coordinate frame. No input was sent.")
        token = state.get("capture_id")
        return token if isinstance(token, str) and len(token) < 200 else None

    def input(self, hwnd, pid, action, args, capture_context=None, foreground=False):
        if action not in _ACTION_FIELDS or not isinstance(args, dict) or set(args) - _ACTION_FIELDS[action]:
            raise DriverError("Unsupported Cua Driver input arguments")
        if type(foreground) is not bool:
            raise DriverError("Invalid input delivery mode")
        points = [("from_x", "from_y"), ("to_x", "to_y")] if action == "drag" else []
        if action in ("click", "double_click", "right_click") or "x" in args or "y" in args:
            points = [("x", "y")]
        for x_key, y_key in points:
            x, y = args.get(x_key), args.get(y_key)
            if (type(x) not in (int, float) or type(y) not in (int, float)
                    or not 0 <= x < 2**31 or not 0 <= y < 2**31 or not math.isfinite(x) or not math.isfinite(y)):
                raise DriverError("Coordinate input requires valid pixel coordinates")
        if points and action in {"type_text", "press_key", "hotkey"} and not foreground:
            raise DriverError("Cua Driver requires foreground permission for keyboard input at a pixel")
        if points and action == "scroll" and not foreground:
            raise DriverError("Cua Driver supports background scroll for the whole window only")
        mode = "foreground" if foreground else "background"
        with self._lock:
            self._api().validate(hwnd, pid)
            if points:
                self.validate_capture(hwnd, pid, capture_context)
                for x_key, y_key in points:
                    if args[x_key] >= capture_context.width or args[y_key] >= capture_context.height:
                        raise DriverError("Input coordinates are outside the captured window")
            if self._process is None or self._process.poll() is not None:
                self._start()
            token = None
            if points:
                try:
                    token = self._register_coordinate_frame(hwnd, pid, capture_context)
                except (OSError, ValueError, queue.Empty) as exc:
                    self.close()
                    raise DriverError("Cua Driver could not establish a matching coordinate frame. No input was sent.") from exc
            if points:
                self.validate_capture(hwnd, pid, capture_context)
            else:
                self._api().validate(hwnd, pid)
            request = {"pid": pid, "window_id": hwnd, "delivery_mode": mode, **args}
            tool = action
            if action in {"double_click", "right_click"}:
                tool = "click"
                request.update({"count": 2} if action == "double_click" else {"button": "right"})
            if tool == "click" and token:
                request["capture_id"] = token
            if foreground:
                if points:
                    left, top, _, _ = capture_context.frame[2]
                    screen_points = [(left + int(args[x]), top + int(args[y])) for x, y in points]
                    self._api().require_uncovered(hwnd, screen_points)
                elif action == "scroll":
                    _, (left, top, right, bottom), _, _ = self._api().frame(hwnd, pid)
                    self._api().require_uncovered(hwnd, [((left + right) // 2, (top + bottom) // 2)])
                if self._api().foreground() != hwnd:
                    raise DriverError("The target window is no longer foreground. No input was sent.")
            try:
                response = self._rpc("tools/call", {"name": tool, "arguments": request})
                return _safe_result(response, mode, action)
            except (DriverError, OSError, queue.Empty, ValueError) as exc:
                self.close()
                raise DriverError("Cua Driver lost the input response. Delivery status is unknown. Observe the target before retrying.") from exc

    def close(self):
        with self._lock:
            process, self._process = self._process, None
            if process is not None:
                try:
                    process.stdin.close()
                    process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    process.kill()
                    process.wait(timeout=2)
                finally:
                    process.stdout.close()
            if self._state is not None:
                self._state.cleanup()
                self._state = None


if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "--capture":
    try:
        frame, image = _print_window(int(sys.argv[2]), int(sys.argv[3]))
        sys.stdout.buffer.write(json.dumps(frame, separators=(",", ":")).encode("ascii") + b"\n" + image)
    except (DriverError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
