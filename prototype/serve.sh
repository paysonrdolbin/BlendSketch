#!/bin/sh
# Builds a standalone page from blendmark.html and serves it at http://127.0.0.1:${PORT:-8080}
# Usage: ./serve.sh        (PORT=9000 ./serve.sh to pick another port; Ctrl+C to stop)
set -e
cd "$(dirname "$0")"
PORT="${PORT:-8080}"
mkdir -p local
{
  printf '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
  printf '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
  printf '<style>body{margin:0}img{max-width:100%%}[hidden]{display:none!important}</style>\n'
  cat blendmark.html
  printf '\n</html>\n'
} > local/index.html
PORT="$PORT" exec python3 server.py
