"""Shared logic for taking a formula-level snapshot of the live spreadsheet.

Lives in `mcp/` rather than in the audit skill because it has two callers that
must never drift apart:

- `bridge_snapshot`, a tool on the sheet-bridge MCP server, which is how an
  agent takes a snapshot without a manual step;
- `skills/portfolio-audit/scripts/snapshot_fetch.py`, the standalone CLI, for
  when the plugin is not installed or the user wants to run it by hand.

Both run on the user's machine. The agent sandbox has no route to
script.google.com and no copy of the bridge token, so neither caller can work
from inside it -- that constraint is the whole reason this is a bridge tool and
not a sandbox script.

The snapshot deliberately carries formulas, raw values AND display values. The
extra copies cost disk, never conversation context, because the whole point is
that the data lands in a file and only a summary is returned.
"""

# Skip the write log (unbounded) and the hidden backups (copies by definition).
SKIP_PREFIXES = ("_bk_",)
SKIP_EXACT = ("_DGI_Log",)

FIELDS = ["formulas", "raw", "values"]

DEFAULT_MAX_ROWS = 400


def column_letter(index):
    """1 -> A, 27 -> AA. Sheets grids are wider than 26 columns."""
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def wanted(name, only):
    if name in SKIP_EXACT or name.startswith(SKIP_PREFIXES):
        return False
    return not only or name in only


def build_snapshot(call_bridge, sheets=None, max_rows=DEFAULT_MAX_ROWS,
                   progress=None):
    """Read every wanted sheet through `call_bridge` and return a snapshot dict.

    `call_bridge(action, payload)` is injected rather than imported so this
    module stays free of transport and token concerns, and so tests can drive
    it with a fake.
    """
    import datetime

    structure = call_bridge("structure", {})
    if not structure.get("ok"):
        raise RuntimeError("structure failed: %s" % structure)

    # `structure` returns only the sheet list. The spreadsheet's name and id
    # come from `ping` -- without this call both land in the snapshot as null,
    # which makes an archived snapshot impossible to attribute later.
    identity = call_bridge("ping", {})

    snapshot = {
        "fetched_at": datetime.datetime.now().astimezone().isoformat(),
        "spreadsheet": identity.get("spreadsheet"),
        "spreadsheet_id": identity.get("id"),
        "source": "live Google Sheet via Apps Script bridge",
        "fields": list(FIELDS),
        "sheets": {},
        "skipped": [],
    }

    for sheet in structure["sheets"]:
        name = sheet["name"]
        if not wanted(name, sheets):
            snapshot["skipped"].append(name)
            continue

        rows = min(int(sheet["rows"]), max_rows)
        cols = int(sheet["columns"])
        cell_range = "A1:%s%d" % (column_letter(cols), rows)

        if progress:
            progress(name, cell_range)

        result = call_bridge("read", {"sheet": name, "range": cell_range,
                                      "fields": ",".join(FIELDS)})
        if not result.get("ok"):
            raise RuntimeError("read failed on %s: %s" % (name, result))

        snapshot["sheets"][name] = {
            "range": cell_range,
            "rows": rows,
            "columns": cols,
            "hidden": sheet.get("hidden", False),
            "formulas": result.get("formulas", []),
            "rawValues": result.get("rawValues", []),
            "displayValues": result.get("displayValues", []),
        }

    return snapshot


def summarise(snapshot, out_path):
    """A small, context-cheap description of a snapshot that is now on disk."""
    return {
        "ok": True,
        "written_to": out_path,
        "spreadsheet": snapshot.get("spreadsheet"),
        "fetched_at": snapshot.get("fetched_at"),
        "sheets": {name: {"range": s["range"],
                          "rows": s["rows"],
                          "columns": s["columns"]}
                   for name, s in snapshot["sheets"].items()},
        "skipped": snapshot["skipped"],
        "next_step": (
            "Run snapshot_to_xlsx.py on this file, then audit_formulas.py on "
            "the workbook it produces. Both run fine in the sandbox."),
    }
