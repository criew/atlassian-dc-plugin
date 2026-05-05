#!/usr/bin/env bash
set -euo pipefail

# Setup script for Atlassian DC Skills (Linux/macOS)
# Checks prerequisites and installs the requests module if missing.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }

echo "=== Atlassian DC Skills — Setup ==="
echo

# 1. Check Python
PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    fail "Python nicht gefunden. Bitte Python 3.6+ installieren."
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$("$PYTHON" -c "import sys; print(sys.version_info.major)")
PY_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 6 ]; }; then
    fail "Python $PY_VERSION gefunden, aber 3.6+ wird benötigt."
fi

ok "Python $PY_VERSION ($PYTHON)"

# 2. Check requests module
if "$PYTHON" -c "import requests" 2>/dev/null; then
    REQ_VERSION=$("$PYTHON" -c "import requests; print(requests.__version__)")
    ok "requests $REQ_VERSION"
else
    warn "Python-Modul 'requests' nicht gefunden. Wird installiert..."
    if "$PYTHON" -m pip install --user requests; then
        REQ_VERSION=$("$PYTHON" -c "import requests; print(requests.__version__)")
        ok "requests $REQ_VERSION installiert"
    else
        fail "Installation von 'requests' fehlgeschlagen. Bitte manuell installieren: $PYTHON -m pip install requests"
    fi
fi

# 3. Check instances.json
CONFIG_DIR="${ATLASSIAN_CONFIG_DIR:-$HOME/.config/atlassian}"
INSTANCES_FILE="${ATLASSIAN_INSTANCES_FILE:-$CONFIG_DIR/instances.json}"

if [ -f "$INSTANCES_FILE" ]; then
    ok "instances.json gefunden: $INSTANCES_FILE"
else
    warn "instances.json nicht gefunden unter: $INSTANCES_FILE"
    echo "    Erstelle Konfigurationsverzeichnis und kopiere Beispieldatei..."
    mkdir -p "$CONFIG_DIR"
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    if [ -f "$SCRIPT_DIR/instances.json.example" ]; then
        cp "$SCRIPT_DIR/instances.json.example" "$INSTANCES_FILE"
        ok "instances.json.example kopiert nach $INSTANCES_FILE"
        echo "    Bitte URL und PAT in $INSTANCES_FILE eintragen."
    else
        warn "Keine Beispieldatei gefunden. Bitte instances.json manuell anlegen."
    fi
fi

echo
echo -e "${GREEN}Setup abgeschlossen.${NC}"
echo "Skripte ausführen mit: $PYTHON skills/jira-dc/scripts/core/jira_issue.py get KEY-1"
