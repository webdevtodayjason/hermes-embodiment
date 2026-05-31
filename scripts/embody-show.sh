#!/usr/bin/env bash
# embody-show.sh — push content onto the face "content stage" (the embody control server).
#
#   • Talks to the loopback embody control server at localhost:8830.
#     That port is UNauthenticated (unlike the :8644 webhook), so a plain curl is enough.
#   • Shows content on the stage beside the face, or hides it to return to full-screen.
#   • Content may come from positional args OR stdin — so you can pipe into it:
#         echo "..." | embody-show.sh --title "Results"
#   • Can also show an IMAGE: --image <path> base64-encodes the file into a
#     data: URI and shows it with format "image" (e.g. what the camera just saw).
#   • Builds the JSON with python3 (json.dumps), so quotes / newlines / backslashes
#     in the content can NEVER break the request — the payload is never hand-concatenated.
#
# Usage:
#   embody-show.sh [--title "T"] [--format text|markdown] [content ...]
#   echo "..." | embody-show.sh --title "Search results"
#   embody-show.sh --image /tmp/embody_view.jpg [--title "What I see"]
#   embody-show.sh --hide          # (or no content at all) → clear the stage
#
# Prints a single status line ("shown" / "hidden" / SHOW_ERROR: ...); never raises.
#
# Deployed to ~/.local/bin/embody-show.sh on the Pi; versioned here in the repo.
set -uo pipefail

URL="http://localhost:8830/control/show"
ERRLOG="/tmp/embody-show.err"

TITLE=""
FORMAT="markdown"
HIDE=0
IMAGE=""
ARGS=()

# --- parse flags; everything else is positional content -----------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --title)  TITLE="${2:-}";  shift 2 || shift ;;
    --format) FORMAT="${2:-markdown}"; shift 2 || shift ;;
    --image)  IMAGE="${2:-}"; shift 2 || shift ;;
    --hide)   HIDE=1; shift ;;
    --)       shift; while [ $# -gt 0 ]; do ARGS+=("$1"); shift; done ;;
    *)        ARGS+=("$1"); shift ;;
  esac
done

# the stage only understands text|markdown — fall back to markdown for anything else
case "$FORMAT" in
  text|markdown) ;;
  *) FORMAT="markdown" ;;
esac

# --- resolve content: args win, else stdin (when piped), else nothing ---------
# (skipped entirely for --image, which carries its own content)
CONTENT=""
if [ "$HIDE" -eq 0 ] && [ -z "$IMAGE" ]; then
  if [ "${#ARGS[@]}" -gt 0 ]; then
    CONTENT="${ARGS[*]}"
  elif [ ! -t 0 ]; then
    CONTENT="$(cat)"
  fi
  [ -z "$CONTENT" ] && HIDE=1   # no content to show → just hide
fi

# --- POST helper: reads the JSON body on stdin --------------------------------
post() {
  curl -fsS --max-time 5 -X POST "$URL" \
    -H 'Content-Type: application/json' \
    --data-binary @- >/dev/null 2>"$ERRLOG"
}

if [ -n "$IMAGE" ]; then
  # read + base64 the file in python3 (binary-safe), build a data: URI, json.dumps it.
  # errors + the >3MB size warning go to stderr; only the JSON payload reaches stdout.
  PAYLOAD="$(IMAGE_PATH="$IMAGE" TITLE="$TITLE" python3 -c '
import os, sys, json, base64

path = os.environ.get("IMAGE_PATH", "")
ext  = os.path.splitext(path)[1].lower()
mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(ext, "image/jpeg")
try:
    with open(path, "rb") as fh:
        raw = fh.read()
except OSError as e:
    sys.stderr.write("cannot read image %r: %s\n" % (path, e))
    sys.exit(1)
uri = "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii"))
if len(uri) > 3000000:
    sys.stderr.write("WARNING: image data URI is %d chars (>3MB) — the stage backend will reject it\n" % len(uri))
sys.stdout.write(json.dumps({
    "title":   os.environ.get("TITLE", ""),
    "content": uri,
    "format":  "image",
}))
')"
  if [ $? -ne 0 ]; then
    echo "SHOW_ERROR: could not load image '$IMAGE' (see detail above)"
    exit 1
  fi
  if printf '%s' "$PAYLOAD" | post; then
    echo "shown"
  else
    echo "SHOW_ERROR: could not reach the stage — $(tail -1 "$ERRLOG" 2>/dev/null)"
    exit 1
  fi
elif [ "$HIDE" -eq 1 ]; then
  if printf '%s' '{"action":"hide"}' | post; then
    echo "hidden"
  else
    echo "SHOW_ERROR: could not clear the stage — $(tail -1 "$ERRLOG" 2>/dev/null)"
    exit 1
  fi
else
  # json-encode the payload safely via python3 (env vars dodge all quoting issues)
  if TITLE="$TITLE" CONTENT="$CONTENT" FORMAT="$FORMAT" python3 -c '
import os, json, sys
sys.stdout.write(json.dumps({
    "title":   os.environ.get("TITLE", ""),
    "content": os.environ.get("CONTENT", ""),
    "format":  os.environ.get("FORMAT", "markdown"),
}))
' | post; then
    echo "shown"
  else
    echo "SHOW_ERROR: could not reach the stage — $(tail -1 "$ERRLOG" 2>/dev/null)"
    exit 1
  fi
fi
