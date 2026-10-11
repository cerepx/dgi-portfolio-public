#!/usr/bin/env python3
"""
Non-destructive cell patcher for .xlsx files that came from Google Sheets.

Why this exists instead of openpyxl: a Google Sheets export is full of
__xludf.DUMMYFUNCTION formulas whose only useful content is the CACHED value.
Loading and saving with openpyxl discards every cached value and drops charts,
images, threaded comments and sharedStrings. Verified on a real file: 10 internal
parts lost and every price turned into None.

This script edits the sheet XML inside the zip directly and copies every other
part through byte for byte, so cached values, charts, drawings, tables and
comments all survive.

Never writes in place. Always produces a new file.

Usage:
    python3 patch_xlsx.py <input.xlsx> <changeset.json> <output.xlsx> [--dry-run]

Changeset format:
    {
      "sheet_name": "MyShares",
      "changes": [
        {"cell": "U16", "type": "string",  "value": "Financials", "reason": "..."},
        {"cell": "L22", "type": "string",  "value": "N/A",        "reason": "..."},
        {"cell": "F27", "type": "formula", "value": "SUM(F2:F26)","reason": "..."},
        {"cell": "B28", "type": "clear",                          "reason": "..."}
      ]
    }

Exit codes: 0 success, 1 validation failure, 2 verification failure.
"""

import argparse
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

RE_SI = re.compile(r"<si>.*?</si>|<si/>", re.S)
RE_T = re.compile(r"<t[^>]*>(.*?)</t>", re.S)
RE_SST_ROOT = re.compile(r"<sst([^>]*)>")
RE_UNIQUE_COUNT = re.compile(r'uniqueCount="(\d+)"')
RE_COUNT = re.compile(r'count="(\d+)"')

XML_ESCAPES = [("&", "&amp;"), ("<", "&lt;"), (">", "&gt;")]


def xml_escape(text):
    for old, new in XML_ESCAPES:
        text = text.replace(old, new)
    return text


class CellSpan:
    """
    Located cell element. Built with str.find rather than regex - the worksheet
    XML runs to megabytes on one line, and backtracking regexes take minutes on it.
    """

    __slots__ = ("ref", "start", "end", "attrs", "inner")

    def __init__(self, ref, start, end, attrs, inner):
        self.ref = ref
        self.start = start
        self.end = end
        self.attrs = attrs
        self.inner = inner

    def group(self, name):
        return {"attrs": self.attrs, "inner": self.inner}[name]


def find_cell(sheet_xml, ref, from_index=0):
    """Locate <c r="REF" ...> ... </c> or its self-closing form."""
    needle = f'<c r="{ref}"'
    while True:
        start = sheet_xml.find(needle, from_index)
        if start == -1:
            return None
        after = start + len(needle)
        # guard against r="L2" matching r="L22"
        if sheet_xml[after] not in ('/', '>', ' ', '\t', '\n'):
            from_index = after
            continue
        tag_end = sheet_xml.find(">", after)
        if tag_end == -1:
            return None
        attrs = sheet_xml[after:tag_end]
        if attrs.endswith("/"):
            return CellSpan(ref, start, tag_end + 1, attrs[:-1], "")
        close = sheet_xml.find("</c>", tag_end)
        if close == -1:
            return None
        return CellSpan(ref, start, close + 4, attrs,
                        sheet_xml[tag_end + 1:close])


# --------------------------------------------------------------------------- #
class SharedStrings:
    """Read/patch xl/sharedStrings.xml, reusing existing entries where possible."""

    def __init__(self, xml):
        self.xml = xml
        self.entries = RE_SI.findall(xml) if xml else []
        self.values = ["".join(RE_T.findall(e)) for e in self.entries]
        self.appended = []

    def index_of(self, value):
        """Return the index of value, appending a new <si> if it is absent."""
        if value in self.values:
            return self.values.index(value), False
        self.values.append(value)
        self.appended.append(value)
        return len(self.values) - 1, True

    def serialise(self):
        if not self.appended:
            return self.xml
        additions = "".join(
            f"<si><t xml:space=\"preserve\">{xml_escape(v)}</t></si>"
            for v in self.appended
        )
        xml = self.xml.replace("</sst>", additions + "</sst>")

        root = RE_SST_ROOT.search(xml)
        if root:
            attrs = root.group(1)
            new_attrs = RE_UNIQUE_COUNT.sub(
                lambda m: f'uniqueCount="{len(self.values)}"', attrs)
            if "uniqueCount=" not in new_attrs:
                new_attrs += f' uniqueCount="{len(self.values)}"'
            xml = xml[:root.start()] + f"<sst{new_attrs}>" + xml[root.end():]
        return xml


# --------------------------------------------------------------------------- #
def sheet_path_for(workbook_xml, rels_xml, sheet_name):
    """Resolve a sheet display name to its xl/worksheets/sheetN.xml path."""
    match = re.search(
        r'<sheet[^>]*name="%s"[^>]*r:id="(rId\d+)"' % re.escape(sheet_name),
        workbook_xml)
    if not match:
        match = re.search(
            r'<sheet[^>]*r:id="(rId\d+)"[^>]*name="%s"' % re.escape(sheet_name),
            workbook_xml)
    if not match:
        return None
    rel_id = match.group(1)
    rel = re.search(r'<Relationship[^>]*Id="%s"[^>]*Target="([^"]+)"' % rel_id,
                    rels_xml)
    if not rel:
        return None
    target = rel.group(1).lstrip("/")
    return target if target.startswith("xl/") else "xl/" + target


def describe_cell(sheet_xml, ref, shared_strings):
    """Human-readable current content of a cell, for the diff report."""
    match = find_cell(sheet_xml, ref)
    if not match:
        return "(empty / cell not present)"
    inner = match.group("inner") or ""
    attrs = match.group("attrs") or ""

    formula = re.search(r"<f[^>]*>([^<]*)</f>", inner)
    shared_stub = re.search(r'<f[^>]*t="shared"[^>]*/>', inner)
    value = re.search(r"<v>([^<]*)</v>", inner)

    if formula and formula.group(1).strip():
        cached = f" [cached: {value.group(1)}]" if value else ""
        return f"={formula.group(1).strip()}{cached}"
    if shared_stub:
        cached = f" [cached: {value.group(1)}]" if value else ""
        return f"(inherits shared formula){cached}"
    if 't="s"' in attrs and value:
        index = int(value.group(1))
        text = shared_strings.values[index] if index < len(shared_strings.values) else "?"
        return f"{text!r} (shared string {index})"
    if 't="b"' in attrs and value:
        return "TRUE" if value.group(1) == "1" else "FALSE"
    if 't="inlineStr"' in attrs:
        text = re.search(r"<t[^>]*>([^<]*)</t>", inner)
        return f"{text.group(1)!r} (inline)" if text else "(inline, empty)"
    if value:
        return value.group(1)
    return "(empty)"


def shared_formula_dependents(sheet_xml, ref):
    """
    If ref hosts a shared-formula group, return the cells that inherit from it.
    Editing the host without handling them leaves orphaned <f t="shared"/> stubs
    that Excel reports as corrupt.
    """
    match = find_cell(sheet_xml, ref)
    if not match:
        return []
    inner = match.group("inner") or ""
    host = re.search(r'<f[^>]*t="shared"[^>]*si="(\d+)"[^>]*>', inner)
    if not host:
        return []
    si = host.group(1)
    dependents = []
    needle = f'si="{si}"'
    index = 0
    while True:
        hit = sheet_xml.find(needle, index)
        if hit == -1:
            break
        index = hit + len(needle)
        # only inheriting stubs matter: <f t="shared" si="N"/>
        tag_start = sheet_xml.rfind("<f", 0, hit)
        tag_end = sheet_xml.find(">", hit)
        if tag_start == -1 or tag_end == -1:
            continue
        tag = sheet_xml[tag_start:tag_end + 1]
        if 't="shared"' not in tag or not tag.endswith("/>"):
            continue
        # walk back to the owning <c r="..."> element
        cell_start = sheet_xml.rfind('<c r="', 0, tag_start)
        if cell_start == -1:
            continue
        quote = sheet_xml.find('"', cell_start + 6)
        owner = sheet_xml[cell_start + 6:quote]
        if owner != ref:
            dependents.append(owner)
    return dependents


# --------------------------------------------------------------------------- #
RE_COL_ROW = re.compile(r"([A-Z]+)(\d+)")


def column_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def insert_cell(sheet_xml, ref, element):
    """
    Insert a new <c> element into its row, preserving ascending column order.
    Excel treats out-of-order cells within a row as a corrupt file.
    """
    col_letters, row_number = RE_COL_ROW.match(ref).groups()
    target_col = column_index(col_letters)

    row_open = re.search(r'<row r="%s"([^>]*?)(/?)>' % row_number, sheet_xml)
    if not row_open:
        raise ValueError(f"Row {row_number} has no <row> element; cannot insert {ref}")
    if row_open.group(2) == "/":
        # self-closing empty row: expand it
        attrs = row_open.group(1)
        replacement = f'<row r="{row_number}"{attrs}>{element}</row>'
        return sheet_xml[:row_open.start()] + replacement + sheet_xml[row_open.end():]

    row_end = sheet_xml.find("</row>", row_open.end())
    if row_end == -1:
        raise ValueError(f"Unterminated <row r=\"{row_number}\">")

    body_start = row_open.end()
    insert_at = row_end
    for cell in re.finditer(r'<c r="([A-Z]+)\d+"', sheet_xml[body_start:row_end]):
        if column_index(cell.group(1)) > target_col:
            insert_at = body_start + cell.start()
            break

    return sheet_xml[:insert_at] + element + sheet_xml[insert_at:]


def build_element(ref, kind, value, style_attr, shared_strings, notes):
    if kind == "string":
        index, appended = shared_strings.index_of(value)
        if appended:
            notes.append(f"appended new shared string {value!r} at index {index}")
        return f'<c r="{ref}"{style_attr} t="s"><v>{index}</v></c>'
    if kind == "boolean":
        flag = 1 if value in (True, "TRUE", "true", 1, "1") else 0
        return f'<c r="{ref}"{style_attr} t="b"><v>{flag}</v></c>'
    if kind == "formula":
        formula = str(value).lstrip("=")
        notes.append(f"{ref}: cached value dropped - Excel recalculates on open")
        return f'<c r="{ref}"{style_attr}><f>{xml_escape(formula)}</f></c>'
    if kind == "number":
        return f'<c r="{ref}"{style_attr}><v>{value}</v></c>'
    if kind == "clear":
        return f'<c r="{ref}"{style_attr}/>'
    raise ValueError(f"Unknown change type {kind!r} for {ref}")


def apply_change(sheet_xml, change, shared_strings, notes):
    ref = change["cell"]
    kind = change["type"]
    match = find_cell(sheet_xml, ref)

    if not match:
        element = build_element(ref, kind, change.get("value"),
                                change.get("style", ""), shared_strings, notes)
        notes.append(f"{ref}: cell did not exist, inserted into row")
        return insert_cell(sheet_xml, ref, element)

    attrs = match.group("attrs") or ""
    style = re.search(r'\ss="(\d+)"', attrs)
    style_attr = f' s="{style.group(1)}"' if style else ""

    replacement = build_element(ref, kind, change.get("value"), style_attr,
                                shared_strings, notes)
    return sheet_xml[:match.start] + replacement + sheet_xml[match.end:]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("changeset")
    parser.add_argument("output")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show the diff and validate, write nothing")
    args = parser.parse_args()

    source = Path(args.source)
    output = Path(args.output)
    spec = json.loads(Path(args.changeset).read_text(encoding="utf-8"))
    sheet_name = spec["sheet_name"]
    changes = spec["changes"]

    if output.resolve() == source.resolve():
        sys.exit("Refusing to write in place. Choose a different output path.")

    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
        rels_xml = archive.read("xl/_rels/workbook.xml.rels").decode("utf-8")
        sst_name = "xl/sharedStrings.xml"
        sst_xml = archive.read(sst_name).decode("utf-8") if sst_name in names else ""
        sheet_file = sheet_path_for(workbook_xml, rels_xml, sheet_name)
        if not sheet_file or sheet_file not in names:
            sys.exit(f"Could not resolve sheet {sheet_name!r} to a worksheet part.")
        sheet_xml = archive.read(sheet_file).decode("utf-8")

    shared_strings = SharedStrings(sst_xml)

    # ---- validate and build the diff before touching anything --------------
    print("=" * 78)
    print(f"PROPOSED CHANGES - {source.name} -> {output.name}")
    print(f"Sheet {sheet_name!r} ({sheet_file})")
    print("=" * 78)

    problems, notes = [], []
    inserts = []
    for change in changes:
        ref = change["cell"]
        exists = find_cell(sheet_xml, ref) is not None
        if not exists:
            row_number = RE_COL_ROW.match(ref).group(2)
            if not re.search(r'<row r="%s"[^>]*?/?>' % row_number, sheet_xml):
                problems.append(
                    f"{ref}: neither the cell nor row {row_number} exists. "
                    f"Inserting a whole row is out of scope for this tool.")
                continue
            inserts.append(ref)

        before = describe_cell(sheet_xml, ref, shared_strings) if exists \
            else "(cell absent, will be inserted)"
        after = change.get("value", "(cleared)")
        if change["type"] == "formula":
            after = "=" + str(after).lstrip("=")
        elif change["type"] == "string":
            after = repr(after)
        elif change["type"] == "boolean":
            after = "TRUE" if after in (True, "TRUE", "true", 1, "1") else "FALSE"

        dependents = shared_formula_dependents(sheet_xml, ref) if exists else []
        refs_being_changed = {c["cell"] for c in changes}
        orphans = [d for d in dependents if d not in refs_being_changed]
        if orphans:
            problems.append(
                f"{ref} hosts a shared formula inherited by {', '.join(orphans)}, "
                f"which are not in this changeset. Editing it would orphan them and "
                f"Excel would report the file as corrupt. Add them to the changeset.")

        print()
        print(f"  {ref}")
        print(f"    before: {before}")
        print(f"    after:  {after}")
        if dependents:
            print(f"    shared formula host, inherited by: {', '.join(dependents)}")
        if change.get("reason"):
            print(f"    reason: {change['reason']}")

    if problems:
        print()
        print("--- VALIDATION FAILED " + "-" * 55)
        for problem in problems:
            print(f"  ! {problem}")
        sys.exit(1)

    # ---- apply ------------------------------------------------------------
    patched = sheet_xml
    for change in changes:
        patched = apply_change(patched, change, shared_strings, notes)
    patched_sst = shared_strings.serialise()

    if notes:
        print()
        print("--- NOTES " + "-" * 67)
        for note in dict.fromkeys(notes):
            print(f"  - {note}")

    if args.dry_run:
        print()
        print("Dry run. Nothing written.")
        return

    # ---- write, copying every other part through untouched ----------------
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as out:
            for info in infos:
                data = archive.read(info.filename)
                if info.filename == sheet_file:
                    data = patched.encode("utf-8")
                elif info.filename == sst_name and shared_strings.appended:
                    data = patched_sst.encode("utf-8")
                out.writestr(info, data)

    # ---- verify -----------------------------------------------------------
    print()
    print("--- VERIFICATION " + "-" * 60)
    with zipfile.ZipFile(source) as a, zipfile.ZipFile(output) as b:
        names_a = {i.filename for i in a.infolist()}
        names_b = {i.filename for i in b.infolist()}
        missing = names_a - names_b
        print(f"  parts in source: {len(names_a)}, in output: {len(names_b)}")
        if missing:
            print(f"  ! MISSING PARTS: {sorted(missing)}")
            sys.exit(2)
        print("  OK  no internal parts lost")

        changed = {sheet_file} | ({sst_name} if shared_strings.appended else set())
        differing = [n for n in sorted(names_a)
                     if n not in changed and a.read(n) != b.read(n)]
        if differing:
            print(f"  ! UNEXPECTED CHANGES: {differing}")
            sys.exit(2)
        print(f"  OK  only {', '.join(sorted(changed))} modified, "
              f"all other parts byte-identical")

        out_sheet = b.read(sheet_file).decode("utf-8")
        out_sst = SharedStrings(b.read(sst_name).decode("utf-8") if sst_name in names_b else "")
        failures = []
        for change in changes:
            actual = describe_cell(out_sheet, change["cell"], out_sst)
            if change["type"] == "string":
                ok = repr(change["value"]) in actual
            elif change["type"] == "formula":
                ok = str(change["value"]).lstrip("=") in actual
            elif change["type"] == "boolean":
                want = "TRUE" if change["value"] in (True, "TRUE", "true", 1, "1") else "FALSE"
                ok = actual == want
            elif change["type"] == "clear":
                ok = "empty" in actual
            else:
                ok = str(change["value"]) in actual
            print(f"  {'OK ' if ok else '!  '} {change['cell']}: {actual}")
            if not ok:
                failures.append(change["cell"])
        if failures:
            print(f"  ! VERIFICATION FAILED for {failures}")
            sys.exit(2)

    print()
    print(f"Written: {output}")
    print("The source file was not modified.")


if __name__ == "__main__":
    main()
