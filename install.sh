#!/usr/bin/env bash
# Install the `venice` CLI (flat) into a PATH dir. Works on Windows git-bash + cmd/PowerShell.
set -euo pipefail
TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  case "$(uname -s)" in
    Darwin)            TARGET="$(brew --prefix 2>/dev/null || echo /usr/local)/bin";;
    Linux)             TARGET="$HOME/.local/bin";;
    MINGW*|MSYS*|CYGWIN*) TARGET="$HOME/venice-cli";;
    *)                 TARGET="$HOME/venice-cli";;
  esac
fi
mkdir -p "$TARGET"
D="$(cd "$(dirname "$0")" && pwd)"
cp "$D/venice.py" "$TARGET/venice.py"

# bash/git-bash shim (MSYS /c/... -> native c:/... so native python3 can open it)
cat > "$TARGET/venice" <<'SHIM'
#!/usr/bin/env bash
D="$(cd "$(dirname "$0")" && pwd)"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) DP="$(printf '%s' "$D" | sed 's|^/\([a-zA-Z]\)/|\1:/|')" ;;
  *) DP="$D" ;;
esac
exec python3 "$DP/venice.py" "$@"
SHIM

# cmd / PowerShell shim (uses %~dp0 -> native path, works natively)
printf '@echo off\npython "%%~dp0venice.py" %%*\n' > "$TARGET/venice.bat"

chmod +x "$TARGET/venice" "$TARGET/venice.py"
echo "installed: $TARGET/venice  (+ venice.bat for cmd.exe/PowerShell)"
echo "add $TARGET to your PATH, then:  venice deploy"
