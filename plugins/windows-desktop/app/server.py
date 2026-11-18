"""Local stdio MCP server for Windows UI Automation patterns."""
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
from desktop_tasks import Tasks, block, sample, changes
from tree_delta import TreeHistory

HERE = Path(__file__).resolve().parent
worker = None
lines = None
tasks = Tasks()
history = TreeHistory()


def start_worker():
    global worker, lines
    worker = subprocess.Popen(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-STA",
                               "-ExecutionPolicy", "Bypass", "-File", str(HERE / "worker.ps1")],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr,
                              text=True, encoding="utf-8", bufsize=1,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    lines = queue.Queue()
    process, output = worker, lines
    def read():
        try:
            for line in process.stdout:
                output.put(line)
        finally:
            output.put(None)
    threading.Thread(target=read, daemon=True).start()


def call_worker(request):
    global worker
    if worker is None or worker.poll() is not None:
        start_worker()
    try:
        worker.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        worker.stdin.flush()
        line = lines.get(timeout=12)
        if line is None:
            raise RuntimeError("UIA worker exited")
        response = json.loads(line)
        if not response.get("ok"):
            raise ValueError(response.get("error", "UIA operation failed"))
        return response["result"]
    except (queue.Empty, BrokenPipeError, json.JSONDecodeError, RuntimeError) as exc:
        history.last = None
        worker.kill()
        worker.wait(timeout=3)
        worker = None
        raise ValueError("UIA worker unavailable or timed out; observation invalidated") from exc


def schema(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}

integer = {"type": "integer", "minimum": 1}
string = {"type": "string", "maxLength": 4096}
target = {"hwnd": integer, "pid": integer}
TOOLS = [
    {"name": "list_windows", "description": "List accessible top-level windows without activating them.", "inputSchema": schema({})},
    {"name": "get_tree", "description": "Read a bounded UIA tree, optionally rooted at a uniquely named descendant; no screenshot or activation.",
     "inputSchema": schema({**target, "depth": {"type": "integer", "minimum": 0, "maximum": 32},
                              "limit": {"type": "integer", "minimum": 1, "maximum": 300}, "root_name": string,
                              "root_automation_id": string, "diff_from": string}, target)},
    {"name": "perform_action", "description": "Act on a fresh UIA observation without mouse/keyboard injection or explicit activation. Standard Edit/Button controls use background Win32 messages; other controls use UIA patterns. Reports observed foreground/cursor changes.",
     "inputSchema": schema({**target, "observation_id": string, "node_id": string,
                            "action": {"type": "string", "enum": ["invoke", "set_value", "select", "toggle", "expand", "collapse", "scroll"]},
                            "value": string, "horizontal": string, "vertical": string},
                           [*target, "observation_id", "node_id", "action"])}]

coordinate = {"type":"integer","minimum":0,"maximum":65535}
session = {"session_id":string}
TOOLS.extend([
    {"name":"begin_task","description":"Bind a task to one HWND and PID. Enable target-only images or foreground input only as requested by the user.",
     "inputSchema":schema({**target,"allow_capture":{"type":"boolean"},"allow_foreground":{"type":"boolean"}},target)},
    {"name":"capture_window","description":"Return the selected window's PNG and a one-use capture_id for its physical image coordinates.",
     "inputSchema":schema(session,session)},
    {"name":"window_input","description":"Send one window-targeted input. Coordinates require a fresh capture_id. An authorized foreground task can activate its target once and stops if focus is taken by another window. Read state to verify effects.",
     "inputSchema":schema({**session,"action":{"type":"string","enum":["click","double_click","right_click","drag","type_text","press_key","hotkey","scroll"]},
        "mode":{"type":"string","enum":["background","foreground"]},"capture_id":string,
        "x":coordinate,"y":coordinate,"to_x":coordinate,"to_y":coordinate,"text":string,"key":string,
        "keys":{"type":"array","minItems":1,"maxItems":8,"items":{"type":"string","minLength":1,"maxLength":40}},
        "direction":{"type":"string","enum":["up","down","left","right"]},"amount":{"type":"integer","minimum":1,"maximum":100}},
        ["session_id","action"])},
    {"name":"end_task","description":"Release the task and its image coordinates.","inputSchema":schema(session,session)}
])


def dispatch(method, params):
    if method == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": "windows-uia-background", "version": "0.2.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name"); args = params.get("arguments", {})
        spec = next((t for t in TOOLS if t["name"] == name), None)
        if spec is None or not isinstance(args, dict):
            raise ValueError("Unknown tool or invalid arguments")
        allowed = spec["inputSchema"]["properties"]
        if set(args) - set(allowed) or any(k not in args for k in spec["inputSchema"]["required"]):
            raise ValueError("Invalid tool arguments")
        for key, value in args.items():
            definition = allowed[key]
            if definition["type"] == "boolean" and type(value) is not bool:
                raise ValueError("Invalid boolean argument")
            if definition["type"] == "array" and (not isinstance(value,list) or not 1<=len(value)<=8 or
                    any(not isinstance(s,str) or not 1<=len(s)<=40 for s in value)):
                raise ValueError("Invalid key sequence")
            if definition["type"] == "integer" and (type(value) is not int or value < definition["minimum"] or value > definition.get("maximum", 2**63-1)):
                raise ValueError("Invalid integer argument")
            if definition["type"] == "string" and (not isinstance(value, str) or len(value) > definition.get("maxLength", 4096) or ("enum" in definition and value not in definition["enum"])):
                raise ValueError("Invalid string argument")
        if name in ("begin_task","capture_window","window_input","end_task"):
            try:
                return tasks.run(name,args,call_worker)
            except (ValueError,OSError) as exc:
                return {"isError":True,"content":[block({"error":str(exc)})]}
        if name == "get_tree":
            if "root_name" in args and "root_automation_id" in args:
                return {"isError":True,"content":[block({"error":"choose one subtree selector"})]}
            try:
                history.prepare(args)
            except ValueError as exc:
                return {"isError":True,"content":[block({"error":str(exc)})]}
            request = {"op": "tree", "depth": 16, "limit": 200, **args}
        elif name == "perform_action":
            if args["action"] == "set_value" and "value" not in args:
                raise ValueError("set_value requires value")
            if args["action"] == "scroll" and not {"horizontal", "vertical"} <= set(args):
                raise ValueError("scroll requires horizontal and vertical")
            tasks.invalidate(args["hwnd"],args["pid"])
            before=sample()
            request = {"op": "action", **args}
        else:
            request = {"op": "windows"}
        try:
            result = call_worker(request)
            if name == "get_tree":
                history.update(args,result)
            if name == "perform_action":
                result.update(hwnd=args["hwnd"],pid=args["pid"],status="dispatched",backend=result["transport"])
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
        except ValueError as exc:
            if name == "perform_action":
                refused = str(exc) in ("stale observation","window mismatch","unknown node","stale window",
                    "stale window process","stale node process","stale node or different window","unsupported UIA pattern",
                    "unsupported action","password value writes unsupported","password or disabled control","invalid scroll amount",
                    "text control is disabled or read-only","unsupported button parent")
                return {"isError":True,"content":[block({"error":str(exc),"hwnd":args["hwnd"],"pid":args["pid"],"backend":"local-uia",
                    "delivery":"not_dispatched" if refused else "unknown",**changes(before,sample())})]}
            return {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
    raise LookupError("Method not found")


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if "id" not in message:
                continue
            try:
                result = dispatch(message.get("method"), message.get("params") or {})
                reply = {"jsonrpc": "2.0", "id": message["id"], "result": result}
            except (ValueError, LookupError) as exc:
                reply = {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32602, "message": str(exc)}}
            print(json.dumps(reply, ensure_ascii=False), flush=True)
        except (ValueError, TypeError) as exc:
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}), flush=True)
    if worker is not None and worker.poll() is None:
        worker.terminate()
    tasks.driver.close()


if __name__ == "__main__":
    main()
