#!/usr/bin/env bash
# Install the `venice` command globally so it works from any folder / cmd.exe.
set -euo pipefail
TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  case "$(uname -s)" in
    Darwin) TARGET="$(brew --prefix 2>/dev/null || echo /usr/local)/bin";;
    Linux)  TARGET="$HOME/.local/bin";;
    *)      TARGET="$HOME/venice-cli";;
  esac
fi
mkdir -p "$TARGET"
D="$(cd "$(dirname "$0")" && pwd)"
cp "$D/bin/venice" "$TARGET/venice"
cp "$D/venice.py"   "$TARGET/venice.py"
cp "$D/bin/venice.bat" "$TARGET/venice.bat" 2>/dev/null || true
chmod +x "$TARGET/venice"
echo "installed: $TARGET/venice"
echo "add $TARGET to your PATH, then run:  venice deploy"
