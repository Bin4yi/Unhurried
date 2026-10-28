#!/usr/bin/env sh
# Start Unhurried and open the split-screen demo.
# Usage: sh scripts/demo.sh   (needs META_API_KEY in .env)
set -e
cd "$(dirname "$0")/.."
PORT="${PORT:-8000}"
python -m pip install -q -r requirements.txt
URL="http://127.0.0.1:$PORT/web/demo.html"
( sleep 2
  case "$(uname -s)" in
    Darwin) open "$URL" ;;
    MINGW*|MSYS*|CYGWIN*) start "$URL" ;;
    *) xdg-open "$URL" >/dev/null 2>&1 || echo "Open $URL" ;;
  esac ) &
exec python -m uvicorn server.main:app --port "$PORT"
