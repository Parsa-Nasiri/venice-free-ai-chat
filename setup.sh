#!/usr/bin/env bash
# setup.sh — one-shot install for venice-free-ai-chat
set -euo pipefail
REPO="https://github.com/Parsa-Nasiri/venice-free-ai-chat.git"
DEST="${VENICE_CHAT_DIR:-$HOME/venice-free-ai-chat}"

echo "==> cloning $REPO into $DEST"
if [ -d "$DEST/.git" ]; then
  echo "    (already exists — pulling instead)"
  cd "$DEST" && git pull --ff-only
elif [ -d "$DEST" ]; then
  echo "    (dir exists, not a git repo — clobbering)"
  rm -rf "$DEST" && git clone --depth 1 "$REPO" "$DEST"
else
  git clone --depth 1 "$REPO" "$DEST" 2>/dev/null || { echo "clone failed"; exit 1; }
fi
cd "$DEST"

echo "==> installing browser-act (the browser driver)"
if ! command -v browser-act >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    uv tool install browser-act-cli --python 3.12
  else
    echo "ERROR: need uv (https://astral.sh) or python+pip"
    exit 1
  fi
fi

echo
echo "==> Done. Now run:"
echo "    browser-act --session venice browser open chrome https://venice.ai"
echo "    browser-act --session venice navigate https://venice.ai/chat/agent"
echo "    python3 venice_chat.py \"<ws endpoint>\" \"your message\""
echo
echo "(get the ws endpoint from: browser-act --session venice browser cdp)"