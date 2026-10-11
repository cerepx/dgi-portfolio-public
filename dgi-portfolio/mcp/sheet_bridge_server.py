#!/usr/bin/env python3
"""
Local MCP stdio server bridging Claude to the Apps Script web app on the
user's portfolio sheet (ClaudePortofoliu).

Why this exists: Claude's shell sandbox has no network route to
script.google.com, and pasting the access token into the conversation burns
it. This server runs on the user's machine (launched by the Claude app via
the plugin's .mcp.json), reads the token from a local file, and exposes the
bridge's actions as MCP tools. The token never appears in the conversation,
in tool call arguments, or in URLs - it travels only in POST bodies from
this process to Google.

Credentials file (create once, chmod 600):

    ~/.dgi/sheet-bridge.json
    {"webapp_url": "https://script.google.com/macros/s/.../exec",
     "token": "<48-char token from generateToken()>"}

No third-party dependencies. Python 3.8+.

Transport: MCP stdio, newline-delimited JSON-RPC 2.0.

Safety model, mirrored from the Apps Script side:
- Writes are refused by the bridge unless ALLOW_WRITES = true over there.
  That flag stays a manual, human-operated switch by design.
- Every write requires a reason, is capped at 60 cells, is validated
  all-or-nothing, takes an automatic hidden backup, and is logged with old
  values to the _DGI_Log sheet.
- This server adds nothing on top except transport and token custody. The
  calling model is expected to show the user a diff and obtain explicit
  consent before any bridge_write call - that rule lives in the skill
  instructions, not here, because a transport should not pretend to enforce
  policy it cannot verify.
"""

import json
import os
import sys
import urllib.error
import urllib.request

# Same directory as this file; the plugin ships both. Importing it must not
# leave a __pycache__ behind in the user's working folder.
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import snapshot_core  # noqa: E402

CONFIG_PATH = os.path.expanduser("~/.dgi/sheet-bridge.json")
HTTP_TIMEOUT_SECONDS = 90  # Apps Script cold starts are slow
PROTOCOL_VERSION_FALLBACK = "2024-11-05"
# Kept in step with .claude-plugin/plugin.json so a log line identifies the build.
SERVER_INFO = {"name": "dgi-sheet-bridge", "version": "0.4.4"}

# --------------------------------------------------------------------------- #
# Credentials


class ConfigError(Exception):
    pass


def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise ConfigError(
            "Credentials file not found: %s. Create it with "
            '{"webapp_url": "...", "token": "..."} and chmod 600 it.'
            % CONFIG_PATH)
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        try:
            cfg = json.load(fh)
        except json.JSONDecodeError as err:
            raise ConfigError("Credentials file is not valid JSON: %s" % err)
    for key in ("webapp_url", "token"):
        if not cfg.get(key):
            raise ConfigError("Credentials file is missing %r." % key)
    if not cfg["webapp_url"].startswith("https://script.google.com/"):
        raise ConfigError(
            "webapp_url does not look like an Apps Script /exec URL.")
    return cfg


def redact(text, token):
    """Never let the token leak through an error message or echo."""
    if token:
        text = text.replace(token, "***TOKEN***")
    return text


# --------------------------------------------------------------------------- #
# Bridge HTTP client. Everything is a POST with token in the body; Apps
# Script answers 302 -> script.googleusercontent.com, which urllib follows
# as a GET, which is exactly what Google expects.


def call_bridge(action, payload=None):
    cfg = load_config()
    body = dict(payload or {})
    body["action"] = action
    body["token"] = cfg["token"]
    request = urllib.request.Request(
        cfg["webapp_url"],
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as err:
        raise RuntimeError(redact(
            "Bridge HTTP %d: %s" % (err.code, err.read(500).decode(
                "utf-8", errors="replace")), cfg["token"]))
    except urllib.error.URLError as err:
        raise RuntimeError(redact(
            "Cannot reach the bridge: %s" % err.reason, cfg["token"]))
    raw = redact(raw, cfg["token"])
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        snippet = raw[:400]
        if "accounts.google.com" in raw or "ServiceLogin" in raw:
            raise RuntimeError(
                "The bridge redirected to a Google login page. The web app "
                "deployment has lost 'Who has access: Anyone' - fix the "
                "deployment, do not retry.")
        raise RuntimeError("Bridge returned non-JSON: %s" % snippet)


# --------------------------------------------------------------------------- #
# Tool definitions

TOOLS = [
    {
        "name": "bridge_ping",
        "description": (
            "Health check against the portfolio sheet bridge. Returns "
            "spreadsheet name, id, whether writes are currently allowed, "
            "time zone and server time."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "bridge_structure",
        "description": (
            "List every sheet in the spreadsheet with row/column counts, "
            "hidden state, and whether it is write-whitelisted."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "bridge_read",
        "description": (
            "Read a range from a sheet. Returns DISPLAY VALUES ONLY by "
            "default; request other representations through `fields`. "
            "Request the minimum that answers the question - the old "
            "always-four-way payload was the project's largest single "
            "context cost. Read-only and always safe."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string", "description": "Sheet name, e.g. MyShares"},
                "range": {"type": "string", "description": "A1 range, e.g. A1:Z30"},
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["values", "formulas", "raw", "formats", "all"],
                    },
                    "description": (
                        "Representations to return. values = display values "
                        "(default), formulas, raw = unformatted values, "
                        "formats = number formats, all = every one of them."),
                },
                "formulas_only": {
                    "type": "boolean", "default": False,
                    "description": "Legacy shorthand for fields=[\"formulas\"]."},
            },
            "required": ["sheet", "range"],
        },
    },
    {
        "name": "bridge_write",
        "description": (
            "Apply cell changes through the bridge. HARD RULES: (1) never "
            "call this without having shown the user the exact cells, old "
            "and new values, and received explicit approval for this exact "
            "batch in this conversation; (2) the bridge refuses writes "
            "unless the user has manually enabled ALLOW_WRITES on the Apps "
            "Script side - if refused, relay that to the user, do not work "
            "around it. Values: JSON booleans become real sheet booleans, "
            "strings starting with '=' become formulas, null or '' clears "
            "the cell. Max 60 cells. A hidden backup and a _DGI_Log entry "
            "are created automatically."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Mandatory justification, goes to the audit log"},
                "changes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "sheet": {"type": "string"},
                            "cell": {"type": "string"},
                            "value": {},
                        },
                        "required": ["sheet", "cell"],
                    },
                },
            },
            "required": ["reason", "changes"],
        },
    },
    {
        "name": "bridge_backup",
        "description": (
            "Take a hidden timestamped backup copy of a sheet without "
            "writing anything else."),
        "inputSchema": {
            "type": "object",
            "properties": {"sheet": {"type": "string"}},
            "required": ["sheet"],
        },
    },
    {
        "name": "bridge_log",
        "description": ("Read the last N entries of the _DGI_Log write "
                        "history. Default 10 - ask for more only when "
                        "actually digging."),
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 10}},
        },
    },
    {
        "name": "bridge_prune",
        "description": (
            "Delete hidden _bk_* backup sheets, keeping the newest `keep` per "
            "source sheet (default 5). DRY RUN BY DEFAULT: without apply=true "
            "it only returns the plan. Deleting sheets is irreversible and "
            "backups are the only safety net, so never call it with "
            "apply=true before showing the user the exact list from a dry run "
            "and getting approval for that list. Applying also requires "
            "ALLOW_WRITES, like a cell write."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "keep": {
                    "type": "integer",
                    "default": 5,
                    "description": (
                        "How many of the newest backups to keep PER SOURCE "
                        "SHEET. Clamped to at least 1; this tool can never "
                        "delete every backup.")},
                "apply": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "False (default) previews. True performs the deletion "
                        "and needs prior explicit approval of the previewed "
                        "list.")},
            },
        },
    },
    {
        "name": "bridge_snapshot",
        "description": (
            "Read every visible sheet and write a formula-level snapshot to a "
            "JSON file on this machine. Returns only a summary - the cell data "
            "goes to disk, never into the conversation. This is the supported "
            "way to audit live data: the agent sandbox cannot reach "
            "script.google.com, so the fetch has to happen here. Read-only; "
            "does not need ALLOW_WRITES. Skips _DGI_Log and every _bk_* "
            "backup."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "out_path": {
                    "type": "string",
                    "description": (
                        "Absolute path for the JSON snapshot, e.g. "
                        "/Users/you/Desktop/claude-dgi/sheet-snapshot.json. "
                        "Required, because the installed plugin has no way to "
                        "guess where the working folder is.")},
                "sheets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Limit to these sheet names. Omit for all visible "
                        "sheets, which is what an audit wants.")},
                "max_rows": {
                    "type": "integer",
                    "default": 400,
                    "description": "Safety cap on rows read per sheet."},
            },
            "required": ["out_path"],
        },
    },
]

ACTION_FOR_TOOL = {
    "bridge_ping": "ping",
    "bridge_structure": "structure",
    "bridge_read": "read",
    "bridge_write": "write",
    "bridge_backup": "backup",
    "bridge_log": "log",
    "bridge_prune": "prune",
    # bridge_snapshot is deliberately absent: it is not a single bridge action
    # but an orchestration of structure + one read per sheet, handled in
    # run_tool before this table is consulted.
}


def run_snapshot(args):
    """bridge_snapshot: many reads in, one file out, a summary back.

    Kept separate from the thin action-passthrough tools because it is the only
    tool that touches the local filesystem, and the only one whose return value
    is deliberately not the bridge's own response.
    """
    out_path = args.get("out_path")
    if not out_path:
        raise RuntimeError("bridge_snapshot needs out_path (absolute).")
    out_path = os.path.abspath(os.path.expanduser(out_path))

    parent = os.path.dirname(out_path)
    if not os.path.isdir(parent):
        raise RuntimeError(
            "Directory does not exist: %s. Pass a path inside the working "
            "folder." % parent)

    snapshot = snapshot_core.build_snapshot(
        call_bridge,
        sheets=args.get("sheets"),
        max_rows=args.get("max_rows", snapshot_core.DEFAULT_MAX_ROWS))

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=1)

    return snapshot_core.summarise(snapshot, out_path)


def run_tool(name, arguments):
    args = dict(arguments or {})

    if name == "bridge_snapshot":
        return run_snapshot(args)

    if name not in ACTION_FOR_TOOL:
        raise RuntimeError("Unknown tool: %s" % name)
    if name == "bridge_read":
        payload = {
            "sheet": args["sheet"],
            "range": args["range"],
        }
        if args.get("formulas_only"):
            # Legacy path, kept because it also works against an old deployed
            # Apps Script version that predates `fields`.
            payload["formulasOnly"] = "true"
        elif args.get("fields"):
            # CSV, not a JSON array: survives both GET params and POST body,
            # and an old Apps Script version simply ignores it (returning the
            # fat payload - wasteful but never wrong).
            payload["fields"] = ",".join(args["fields"])
    elif name == "bridge_write":
        payload = {"reason": args["reason"], "changes": args["changes"]}
    elif name == "bridge_backup":
        payload = {"sheet": args["sheet"]}
    elif name == "bridge_log":
        payload = {"limit": args.get("limit", 10)}
    elif name == "bridge_prune":
        # apply is sent explicitly rather than defaulted on the Apps Script
        # side, so a truncated or malformed call can never read as "delete".
        payload = {"keep": args.get("keep", 5),
                   "apply": bool(args.get("apply", False))}
    else:
        payload = {}
    return call_bridge(ACTION_FOR_TOOL[name], payload)


# --------------------------------------------------------------------------- #
# MCP stdio plumbing: newline-delimited JSON-RPC 2.0


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def result_for(request):
    method = request.get("method")
    params = request.get("params") or {}

    if method == "initialize":
        return {
            "protocolVersion": params.get(
                "protocolVersion", PROTOCOL_VERSION_FALLBACK),
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        try:
            outcome = run_tool(params.get("name"), params.get("arguments"))
            # Compact on purpose: pretty-printing a sheet read puts every cell
            # on its own indented line, which multiplied the payload several
            # times over. Nested value arrays are perfectly readable inline.
            text = json.dumps(outcome, ensure_ascii=False,
                              separators=(",", ":"))
            is_error = not (isinstance(outcome, dict) and outcome.get("ok"))
        except KeyError as err:
            text = "ERROR: missing required argument %s" % err
            is_error = True
        except (RuntimeError, ConfigError) as err:
            text = "ERROR: %s" % err
            is_error = True
        return {"content": [{"type": "text", "text": text}],
                "isError": is_error}
    raise LookupError(method)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue  # not ours to answer
        if "id" not in request:
            continue  # notification, no response allowed
        try:
            send({"jsonrpc": "2.0", "id": request["id"],
                  "result": result_for(request)})
        except LookupError:
            send({"jsonrpc": "2.0", "id": request["id"],
                  "error": {"code": -32601,
                            "message": "Method not found: %s"
                                       % request.get("method")}})
        except Exception as err:  # last-resort guard: never crash the loop
            send({"jsonrpc": "2.0", "id": request["id"],
                  "error": {"code": -32603, "message": str(err)}})


if __name__ == "__main__":
    main()
