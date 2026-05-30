#!/usr/bin/env bash
#
# install.sh — dev/local installer for the `embody` Hermes plugin.
#
# Installs this repo into your Hermes plugins dir as `embody/`, seeds an active
# config.yaml (if one doesn't already exist), and prints the next steps.
#
# This is the DEV path. The supported install for everyone else is:
#     hermes plugins install webdevtodayjason/hermes-embodiment --enable
#
# Usage:
#     ./install.sh [--link] [--minnie] [--help]
#
# Options:
#     --link     Symlink the repo into place instead of copying (live edits).
#     --minnie   Seed the active config from examples/minnie/config.yaml
#                instead of the generic config.yaml.example.
#     --help     Show this help and exit.
#
# Environment:
#     HERMES_HOME   Hermes home dir. Defaults to ~/.hermes.
#
set -euo pipefail

# --- Resolve paths -----------------------------------------------------------
# The repo root IS the plugin package (plugin.yaml lives here).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PLUGINS_DIR="$HERMES_HOME/plugins"
DEST="$PLUGINS_DIR/embody"

# --- Parse args --------------------------------------------------------------
LINK=0
MINNIE=0
for arg in "$@"; do
  case "$arg" in
    --link)   LINK=1 ;;
    --minnie) MINNIE=1 ;;
    -h|--help)
      sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "embody/install: unknown option '$arg' (try --help)" >&2
      exit 2
      ;;
  esac
done

echo "embody/install: HERMES_HOME = $HERMES_HOME"
mkdir -p "$PLUGINS_DIR"

# --- Place the plugin (copy or symlink) --------------------------------------
if [ "$LINK" -eq 1 ]; then
  # Symlink mode: live edits in this checkout take effect immediately.
  if [ -e "$DEST" ] && [ ! -L "$DEST" ]; then
    echo "embody/install: $DEST exists and is not a symlink; refusing to replace it." >&2
    echo "embody/install: remove it manually, or re-run without --link to copy." >&2
    exit 1
  fi
  ln -sfn "$SCRIPT_DIR" "$DEST"
  echo "embody/install: linked $DEST -> $SCRIPT_DIR"
else
  # Copy mode: sync the repo into the plugins dir, excluding junk + git.
  mkdir -p "$DEST"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete \
      --exclude '.git/' \
      --exclude '__pycache__/' \
      --exclude '*.pyc' \
      --exclude '.venv/' \
      --exclude 'venv/' \
      --exclude '/config.yaml' \
      "$SCRIPT_DIR"/ "$DEST"/
  else
    # Fallback without rsync: clean copy (preserves the active config below).
    find "$DEST" -mindepth 1 -maxdepth 1 ! -name 'config.yaml' -exec rm -rf {} +
    cp -R "$SCRIPT_DIR"/. "$DEST"/
    rm -rf "$DEST/.git" "$DEST"/__pycache__ "$DEST"/*/__pycache__ 2>/dev/null || true
    rm -f "$DEST/config.yaml" 2>/dev/null || true   # never ship the example as active
  fi
  echo "embody/install: copied repo -> $DEST"
fi

# --- Seed the active config (never clobber an existing one) -------------------
# Matches core/config.py's contract: an existing config.yaml is left untouched.
if [ "$MINNIE" -eq 1 ]; then
  SRC_CONFIG="$SCRIPT_DIR/examples/minnie/config.yaml"
  SRC_LABEL="examples/minnie/config.yaml (Minnie)"
else
  SRC_CONFIG="$SCRIPT_DIR/config.yaml.example"
  SRC_LABEL="config.yaml.example (generic)"
fi

DEST_CONFIG="$DEST/config.yaml"
if [ -e "$DEST_CONFIG" ]; then
  echo "embody/install: $DEST_CONFIG already exists — keeping it (not overwritten)."
elif [ -f "$SRC_CONFIG" ]; then
  cp "$SRC_CONFIG" "$DEST_CONFIG"
  echo "embody/install: seeded config.yaml from $SRC_LABEL"
else
  echo "embody/install: WARNING: $SRC_CONFIG not found; skipping config seed." >&2
fi

# --- Next steps --------------------------------------------------------------
cat <<EOF

embody installed. Next steps:

  1. (voice) export your ElevenLabs key so TTS works:
         export ELEVENLABS_API_KEY=...        # or add it to $HERMES_HOME/.env
     Leaving it unset is fine — the face + LEDs still run; voice falls back to
     Hermes' own configured TTS.

  2. Enable the plugin and restart the gateway:
         hermes plugins enable embody
         # restart your Hermes gateway

  3. Open the face:
         http://127.0.0.1:8830/

  4. Edit $DEST_CONFIG to pick a persona, voice, audio device, theme, and LEDs.
EOF
