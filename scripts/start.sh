#!/usr/bin/env bash
# Start Prompt Vault from a source checkout: creates backend/.venv, installs the app (editable),
# builds the UI when Node is available, then runs `promptvault serve`.
#
#   scripts/start.sh [--port N] [--host H] [--no-ui-build] [--rebuild-ui] [--help]
#
# Needs uv (preferred) or Python 3.11+ with venv. Node 20+ and npm are only needed to build the UI.
# Writes only inside the repository (backend/.venv, frontend/node_modules, the built UI) and the
# data directory (PV_DATA_DIR, default ~/.promptvault). Never uses sudo.
#
# Environment: PV_PORT, PV_HOST and the other PV_* settings are honoured; flags win over them.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/start.sh [options]

  --port N        port to listen on (default: PV_PORT or 8080)
  --host H        address to bind (default: PV_HOST or loopback only)
  --no-ui-build   never build the UI; serve the API only if it is not built yet
  --rebuild-ui    rebuild the UI even if it looks up to date
  -h, --help      show this help

Exit codes: 0 ok or help, 1 a tool or step failed, 2 bad usage.
Prompt Vault v1 has no authentication: only bind to a non-loopback address behind a
reverse proxy that adds authentication and TLS.
EOF
}

die() { echo "start.sh: $*" >&2; exit 1; }
info() { echo "start.sh: $*"; }

PORT=""
HOST=""
UI_MODE="auto"   # auto | never | force

while [ $# -gt 0 ]; do
  case "$1" in
    --port) [ $# -ge 2 ] || { echo "start.sh: --port needs a value" >&2; exit 2; }; PORT="$2"; shift 2 ;;
    --port=*) PORT="${1#--port=}"; shift ;;
    --host) [ $# -ge 2 ] || { echo "start.sh: --host needs a value" >&2; exit 2; }; HOST="$2"; shift 2 ;;
    --host=*) HOST="${1#--host=}"; shift ;;
    --no-ui-build) UI_MODE="never"; shift ;;
    --rebuild-ui) UI_MODE="force"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "start.sh: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ -n "$PORT" ]; then
  case "$PORT" in
    ''|*[!0-9]*) echo "start.sh: --port must be a number" >&2; exit 2 ;;
  esac
  if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
    echo "start.sh: --port must be between 1 and 65535" >&2; exit 2
  fi
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND="$REPO/backend"
FRONTEND="$REPO/frontend"
STATIC="$BACKEND/src/promptvault/static"
[ -f "$BACKEND/pyproject.toml" ] || die "run this script from a checkout of the repository (backend/pyproject.toml not found)"

# ---- host warning
EFFECTIVE_HOST="${HOST:-${PV_HOST:-}}"
case "$EFFECTIVE_HOST" in
  ''|localhost|::1|127.*) ;;
  *) echo "WARNING: binding to '$EFFECTIVE_HOST'. Prompt Vault v1 has no authentication; anyone who can reach this port can read and change your library." >&2 ;;
esac

# ---- Python tooling
USE_UV=0
if command -v uv >/dev/null 2>&1; then
  USE_UV=1
  info "using uv $(uv --version | awk '{print $2}')"
else
  PY=""
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      PY="$c"; break
    fi
  done
  [ -n "$PY" ] || die "need uv (https://docs.astral.sh/uv/) or Python 3.11+; neither was found"
  info "uv not found, using $PY ($("$PY" --version 2>&1)) with venv + pip"
fi

# ---- UI
ui_is_stale() {
  [ ! -f "$STATIC/index.html" ] && return 0
  [ -d "$FRONTEND/src" ] || return 1
  [ -n "$(find "$FRONTEND/src" "$FRONTEND/index.html" "$FRONTEND/package.json" -newer "$STATIC/index.html" -type f 2>/dev/null | head -n 1)" ]
}

if [ "$UI_MODE" != "never" ] && { [ "$UI_MODE" = "force" ] || ui_is_stale; }; then
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1 && [ -f "$FRONTEND/package.json" ]; then
    info "building the UI (node $(node --version))"
    (
      cd "$FRONTEND"
      if [ ! -d node_modules ]; then npm ci; fi
      npm run build
    ) || die "the UI build failed (re-run with --no-ui-build to skip it)"
  elif [ ! -f "$STATIC/index.html" ]; then
    echo "WARNING: the UI is not built and Node/npm were not found: serving the API only (docs at /docs). Install Node 20+ and re-run, or use the Docker image or 'pipx install prompt-vault', which include the UI." >&2
  fi
elif [ "$UI_MODE" = "never" ] && [ ! -f "$STATIC/index.html" ]; then
  echo "WARNING: --no-ui-build and the UI is not built: serving the API only (docs at /docs)." >&2
fi

# ---- install + run
SERVE_ARGS=()
[ -n "$HOST" ] && SERVE_ARGS+=(--host "$HOST")
[ -n "$PORT" ] && SERVE_ARGS+=(--port "$PORT")

if [ "$USE_UV" = "1" ]; then
  cd "$BACKEND"
  info "installing dependencies (uv sync)"
  uv sync --extra xlsx || die "uv sync failed"
  info "starting Prompt Vault (Ctrl+C to stop)"
  exec uv run --no-sync promptvault serve "${SERVE_ARGS[@]}"
else
  VENV="$BACKEND/.venv"
  if [ ! -d "$VENV" ]; then
    info "creating $VENV"
    "$PY" -m venv "$VENV" || die "could not create the virtual environment"
  fi
  if [ -x "$VENV/bin/python" ]; then VPY="$VENV/bin/python"; else VPY="$VENV/Scripts/python.exe"; fi
  info "installing dependencies (pip, editable)"
  "$VPY" -m pip install --quiet --disable-pip-version-check -e "$BACKEND[xlsx]" || die "pip install failed"
  info "starting Prompt Vault (Ctrl+C to stop)"
  exec "$VPY" -m promptvault.cli serve "${SERVE_ARGS[@]}"
fi
