#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="https://github.com/LexouTasne/Astra-PC.git"
RAW_ROOT="https://raw.githubusercontent.com/LexouTasne/Astra-PC/main"
DEFAULT_DEST="${ASTRA_HOME:-$HOME/Astra-PC}"
FULL=0
EXTRA=()

for arg in "$@"; do
  case "$arg" in
    --full) FULL=1 ;;
    *) EXTRA+=("$arg") ;;
  esac
done

say() { printf '\n[Astra] %s\n' "$*"; }
fail() { printf '\n[Astra] ERROR: %s\n' "$*" >&2; exit 1; }

if [[ -f "./installer.py" && -d "./astra_pc" ]]; then
  DEST="$(pwd)"
else
  DEST="$DEFAULT_DEST"
fi

say "Installer universal -> $DEST"

if [[ -d "$DEST/.git" ]]; then
  say "Atualizando repositório..."
  git -C "$DEST" pull --ff-only || fail "git pull falhou. Resolva mudanças locais e rode novamente."
elif command -v git >/dev/null 2>&1; then
  if [[ -e "$DEST" && -n "$(find "$DEST" -mindepth 1 -maxdepth 1 2>/dev/null | head -n 1)" ]]; then
    fail "$DEST já existe e não é um clone Git vazio."
  fi
  mkdir -p "$(dirname "$DEST")"
  say "Clonando Astra-PC..."
  git clone --recursive "$REPO_URL" "$DEST"
else
  command -v curl >/dev/null 2>&1 || fail "Precisa de git ou curl."
  command -v tar >/dev/null 2>&1 || fail "git não existe e tar também não; instale um deles."
  say "git não encontrado; baixando snapshot do GitHub..."
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  curl -fsSL "https://github.com/LexouTasne/Astra-PC/archive/refs/heads/main.tar.gz" | tar -xz -C "$TMP"
  rm -rf "$DEST"
  mkdir -p "$(dirname "$DEST")"
  mv "$TMP/Astra-PC-main" "$DEST"
fi

find_uv() {
  command -v uv 2>/dev/null || true
  [[ -x "$HOME/.local/bin/uv" ]] && printf '%s\n' "$HOME/.local/bin/uv" && return
  [[ -x "$HOME/.cargo/bin/uv" ]] && printf '%s\n' "$HOME/.cargo/bin/uv" && return
}

UV="$(find_uv | head -n 1 || true)"
if [[ -z "$UV" ]]; then
  command -v curl >/dev/null 2>&1 || fail "curl é necessário para instalar uv."
  say "Instalando uv em user-space..."
  TMP_UV="$(mktemp)"
  curl -LsSf https://astral.sh/uv/install.sh -o "$TMP_UV"
  sh "$TMP_UV"
  rm -f "$TMP_UV"
  UV="$(find_uv | head -n 1 || true)"
fi
[[ -n "$UV" ]] || fail "uv não foi encontrado depois da instalação."

cd "$DEST"

say "Garantindo Python 3.12 isolado..."
"$UV" python install 3.12

VENV_PY="$DEST/.venv/bin/python"
NEED_VENV=1
if [[ -x "$VENV_PY" ]]; then
  VERSION="$("$VENV_PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
  [[ "$VERSION" == "3.12" ]] && NEED_VENV=0
fi
if [[ "$NEED_VENV" == "1" ]]; then
  "$UV" venv --clear --python 3.12 "$DEST/.venv"
fi

say "Executando Astra installer..."
if [[ "$FULL" == "1" || "${ASTRA_FULL:-0}" == "1" ]]; then
  exec "$VENV_PY" installer.py --full "${EXTRA[@]}"
else
  exec "$VENV_PY" installer.py --yes --autostart --start --awareness-extras "${EXTRA[@]}"
fi
