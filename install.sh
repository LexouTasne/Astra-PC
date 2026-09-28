#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="https://github.com/LexouTasne/Astra-PC.git"
DEFAULT_DEST="${ASTRA_INSTALL_DIR:-${ASTRA_HOME:-$HOME/Astra-PC}}"
FULL=0
YES=0
PORTABLE_DATA=0
DEST_ARG=""
RUNTIME_ARG="${ASTRA_RUNTIME_DIR:-}"
DATA_ARG="${ASTRA_DATA_DIR:-}"
CACHE_ARG="${ASTRA_CACHE_DIR:-}"
EXTRA=()

say() { printf '\n[Astra] %s\n' "$*"; }
fail() { printf '\n[Astra] ERROR: %s\n' "$*" >&2; exit 1; }

expand_path() {
  local p="$1"
  case "$p" in
    "~") p="$HOME" ;;
    "~/"*) p="$HOME/${p#~/}" ;;
  esac
  printf '%s\n' "$p"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --full) FULL=1; shift ;;
    --yes|-y) YES=1; shift ;;
    --portable|--portable-data) PORTABLE_DATA=1; shift ;;
    --dest|--install-dir)
      [[ $# -ge 2 ]] || fail "$1 requires a path"
      DEST_ARG="$2"; shift 2 ;;
    --runtime-dir)
      [[ $# -ge 2 ]] || fail "$1 requires a path"
      RUNTIME_ARG="$2"; shift 2 ;;
    --data-dir)
      [[ $# -ge 2 ]] || fail "$1 requires a path"
      DATA_ARG="$2"; shift 2 ;;
    --cache-dir)
      [[ $# -ge 2 ]] || fail "$1 requires a path"
      CACHE_ARG="$2"; shift 2 ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
IN_REPO=0
if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/installer.py" && -d "$SCRIPT_DIR/astra_pc" ]]; then
  IN_REPO=1
fi

if [[ -n "$DEST_ARG" ]]; then
  DEST="$(expand_path "$DEST_ARG")"
elif [[ "$IN_REPO" == "1" ]]; then
  DEST="$SCRIPT_DIR"
else
  DEST="$(expand_path "$DEFAULT_DEST")"
  if [[ "$YES" != "1" && -t 0 ]]; then
    printf '\nAstra install folder [%s]: ' "$DEST"
    read -r answer || true
    [[ -n "${answer:-}" ]] && DEST="$(expand_path "$answer")"
  fi
fi

DEST="$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$DEST" 2>/dev/null || printf '%s' "$DEST")"
mkdir -p "$(dirname "$DEST")" || fail "Cannot create parent folder for $DEST"

say "Application folder -> $DEST"

if [[ -d "$DEST/.git" ]]; then
  say "Updating repository..."
  git -C "$DEST" pull --ff-only || fail "git pull failed. Resolve local changes and retry."
elif command -v git >/dev/null 2>&1; then
  if [[ -e "$DEST" && -n "$(find "$DEST" -mindepth 1 -maxdepth 1 2>/dev/null | head -n 1)" ]]; then
    fail "$DEST exists and is not an Astra Git checkout or empty folder."
  fi
  mkdir -p "$(dirname "$DEST")"
  say "Cloning Astra-PC..."
  git clone --recursive "$REPO_URL" "$DEST" || fail "git clone failed."
else
  command -v curl >/dev/null 2>&1 || fail "git or curl is required."
  command -v tar >/dev/null 2>&1 || fail "git is unavailable and tar is also missing."
  say "git not found; downloading GitHub snapshot..."
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  curl -fsSL "https://github.com/LexouTasne/Astra-PC/archive/refs/heads/main.tar.gz" | tar -xz -C "$TMP"
  rm -rf "$DEST"
  mkdir -p "$(dirname "$DEST")"
  mv "$TMP/Astra-PC-main" "$DEST"
fi

# Verify the destination is writable before downloading runtimes/models.
touch "$DEST/.astra-write-test" 2>/dev/null || fail "Destination is not writable: $DEST"
rm -f "$DEST/.astra-write-test"

if [[ "$PORTABLE_DATA" == "1" ]]; then
  DATA_ARG="${DATA_ARG:-$DEST/.astra-data}"
  CACHE_ARG="${CACHE_ARG:-$DEST/.astra-cache}"
fi
if [[ -n "$DATA_ARG" && -z "$CACHE_ARG" ]]; then
  CACHE_ARG="$DATA_ARG/cache"
fi

# Python venvs can be unreliable on FAT/exFAT/NTFS mounts under Linux because
# symlink/permission semantics differ. Keep the code/data on the chosen disk,
# but automatically keep the runtime on the local user filesystem when needed.
FSTYPE=""
if command -v findmnt >/dev/null 2>&1; then
  FSTYPE="$(findmnt -no FSTYPE -T "$DEST" 2>/dev/null | head -n1 || true)"
fi

if [[ -n "$RUNTIME_ARG" ]]; then
  VENV_DIR="$(expand_path "$RUNTIME_ARG")"
else
  case "${FSTYPE,,}" in
    vfat|fat|msdos|exfat|ntfs|ntfs3|fuseblk)
      if command -v sha256sum >/dev/null 2>&1; then
        KEY="$(printf '%s' "$DEST" | sha256sum | cut -c1-12)"
      else
        KEY="$(basename "$DEST" | tr -cd '[:alnum:]_-')"
      fi
      VENV_DIR="$HOME/.local/share/astra-pc/runtimes/${KEY:-portable}/.venv"
      say "Filesystem '$FSTYPE' detected. Python runtime will stay local -> $VENV_DIR"
      ;;
    *) VENV_DIR="$DEST/.venv" ;;
  esac
fi

if [[ -n "$DATA_ARG" ]]; then
  DATA_ARG="$(expand_path "$DATA_ARG")"
  mkdir -p "$DATA_ARG"
  export ASTRA_DATA_DIR="$DATA_ARG"
  say "Astra data -> $ASTRA_DATA_DIR"
fi
if [[ -n "$CACHE_ARG" ]]; then
  CACHE_ARG="$(expand_path "$CACHE_ARG")"
  mkdir -p "$CACHE_ARG"
  export ASTRA_CACHE_DIR="$CACHE_ARG"
  say "Astra cache -> $ASTRA_CACHE_DIR"
fi
export ASTRA_INSTALL_DIR="$DEST"
export ASTRA_RUNTIME_DIR="$VENV_DIR"

find_uv() {
  command -v uv 2>/dev/null || true
  [[ -x "$HOME/.local/bin/uv" ]] && printf '%s\n' "$HOME/.local/bin/uv" && return
  [[ -x "$HOME/.cargo/bin/uv" ]] && printf '%s\n' "$HOME/.cargo/bin/uv" && return
}

UV="$(find_uv | head -n 1 || true)"
if [[ -z "$UV" ]]; then
  command -v curl >/dev/null 2>&1 || fail "curl is required to install uv."
  say "Installing uv in user space..."
  TMP_UV="$(mktemp)"
  curl -LsSf https://astral.sh/uv/install.sh -o "$TMP_UV"
  sh "$TMP_UV"
  rm -f "$TMP_UV"
  UV="$(find_uv | head -n 1 || true)"
fi
[[ -n "$UV" ]] || fail "uv was not found after installation."

mkdir -p "$(dirname "$VENV_DIR")"
cd "$DEST"

say "Ensuring isolated Python 3.12 runtime -> $VENV_DIR"
VENV_PY="$VENV_DIR/bin/python"
NEED_VENV=1
if [[ -x "$VENV_PY" ]]; then
  VERSION="$("$VENV_PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
  [[ "$VERSION" == "3.12" ]] && NEED_VENV=0
fi
if [[ "$NEED_VENV" == "1" ]]; then
  "$UV" venv --clear --seed --python 3.12 "$VENV_DIR" || fail "Failed creating Python runtime."
fi

if ! "$VENV_PY" -m pip --version >/dev/null 2>&1; then
  say "Repairing runtime without pip..."
  "$UV" pip install --python "$VENV_PY" pip setuptools wheel
fi

say "Running Astra guided installer..."
ARGS=()
[[ "$YES" == "1" ]] && ARGS+=("--yes")
if [[ "$FULL" == "1" || "${ASTRA_FULL:-0}" == "1" ]]; then
  ARGS+=("--full")
fi
ARGS+=("${EXTRA[@]}")

exec "$VENV_PY" installer.py "${ARGS[@]}"
