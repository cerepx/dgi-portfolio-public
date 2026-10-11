#!/usr/bin/env bash
# Install a built dgi-portfolio archive into the Claude desktop app's local
# plugin store - the same place the app's own "upload plugin" writes to - so a
# new build installs from one command instead of Settings -> Plugins -> upload.
#
#   bash install-plugin.sh dgi-portfolio-0.11.7.plugin
#
# What the app's upload does, and therefore what this does (BACKLOG item 24):
# unpack into ~/.claude/plugins/marketplaces/local-desktop-app-uploads/
# dgi-portfolio/ and record the version in that marketplace's manifest. Then
# `claude plugin update` refreshes the install registry. Nothing is written
# until every check passes. No backup of the previous install is kept (user
# decision 2026-10-10): every delivered archive is in git as dgi-portfolio.plugin.
set -euo pipefail

ARCHIVE="${1:-}"
if [ -z "$ARCHIVE" ] || [ ! -f "$ARCHIVE" ]; then
  echo "usage: bash install-plugin.sh <dgi-portfolio-X.Y.Z.plugin>" >&2
  exit 1
fi

STORE="$HOME/.claude/plugins/marketplaces/local-desktop-app-uploads"
TARGET="$STORE/dgi-portfolio"
MARKETPLACE="$STORE/.claude-plugin/marketplace.json"

if [ ! -d "$TARGET" ] || [ ! -f "$MARKETPLACE" ]; then
  echo "No local plugin store at $STORE." >&2
  echo "Install once through the app (Settings -> Plugins -> upload) first." >&2
  exit 1
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
unzip -q "$ARCHIVE" -d "$STAGE"

# --- checks: refuse anything that is not a complete dgi-portfolio build ------
read -r NAME VERSION < <(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print(d["name"], d["version"])' "$STAGE/.claude-plugin/plugin.json")

if [ "$NAME" != "dgi-portfolio" ]; then
  echo "Archive is plugin '$NAME', not dgi-portfolio. Nothing installed." >&2
  exit 1
fi
if [ ! -f "$STAGE/.mcp.json" ]; then
  # A missing .mcp.json installs cleanly and registers no MCP server at all.
  echo "Archive has no .mcp.json - no MCP server would register. Nothing installed." >&2
  exit 1
fi
if find "$STAGE" -name '__pycache__' -o -name '*.pyc' | grep -q .; then
  echo "Archive carries bytecode. Rebuild it. Nothing installed." >&2
  exit 1
fi

OLD="$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print(d.get("version", "unknown"))' "$TARGET/.claude-plugin/plugin.json" 2>/dev/null || echo unknown)"

# --- install -----------------------------------------------------------------
rsync -a --delete "$STAGE/" "$TARGET/"

python3 - "$MARKETPLACE" "$VERSION" <<'EOF'
import json, sys
path, version = sys.argv[1], sys.argv[2]
data = json.load(open(path))
for plugin in data.get("plugins", []):
    if plugin.get("name") == "dgi-portfolio":
        plugin["version"] = version
json.dump(data, open(path, "w"), indent=2)
EOF

if command -v claude >/dev/null 2>&1; then
  claude plugin update dgi-portfolio@local-desktop-app-uploads \
    || echo "WARNING: 'claude plugin update' failed - files are installed, the registry may still show $OLD." >&2
fi

# --- proof -------------------------------------------------------------------
if diff -rq "$STAGE" "$TARGET" >/dev/null; then
  echo "Installed dgi-portfolio $OLD -> $VERSION, byte-identical to $(basename "$ARCHIVE")."
else
  echo "WARNING: installed tree differs from the archive:" >&2
  diff -rq "$STAGE" "$TARGET" >&2 || true
  exit 1
fi
# `claude plugin update` copies the plugin into ~/.claude/plugins/cache/... and
# points the registry there (seen 2026-10-10), so prove that copy too.
REGISTERED="$(python3 -c '
import json, os
d = json.load(open(os.path.expanduser("~/.claude/plugins/installed_plugins.json")))
entries = (d.get("plugins") or d).get("dgi-portfolio@local-desktop-app-uploads", [])
print(entries[0]["installPath"] if entries else "")' 2>/dev/null || true)"
if [ -n "$REGISTERED" ] && [ "$REGISTERED" != "$TARGET" ]; then
  if diff -rq "$STAGE" "$REGISTERED" >/dev/null 2>&1; then
    echo "Registry points at $REGISTERED - also byte-identical."
  else
    echo "WARNING: the registry points at $REGISTERED, which differs from the archive." >&2
    exit 1
  fi
fi
echo "Open a new session (or restart Claude) to load it - a running session keeps its old copy."
