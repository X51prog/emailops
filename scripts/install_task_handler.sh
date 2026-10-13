#!/usr/bin/env bash
# Register the emailops-task:// URL scheme (macOS) so the task board's "Open" button
# opens the task in Herdr: tasks.py open-in-herdr focuses the task's agent or starts
# Claude in a new Herdr tab with /work-on-task typed in.
#
# Installs ~/Applications/EmailOps Task Handler.app, a small AppleScript applet that
# calls this checkout's scripts/tasks.py, so run it from the main checkout (a removed
# worktree would leave the handler pointing nowhere). Re-run to update; delete the app
# to uninstall. Failures go to ~/Library/Logs/emailops-task-handler.log.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$HOME/Applications/EmailOps Task Handler.app"
LOG="$HOME/Library/Logs/emailops-task-handler.log"
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister

[ "$(uname)" = Darwin ] || { echo "macOS only" >&2; exit 1; }
command -v herdr >/dev/null || [ -x "$HOME/.local/bin/herdr" ] || { echo "herdr not found" >&2; exit 1; }

src="$(mktemp -t task-handler).applescript"
trap 'rm -f "$src"' EXIT
cat > "$src" <<EOF
on open location theURL
	try
		do shell script "/usr/bin/python3 " & quoted form of "$ROOT/scripts/tasks.py" & " open-in-herdr " & quoted form of theURL & " 2>> " & quoted form of "$LOG"
	on error errMsg
		display notification errMsg with title "EmailOps task"
	end try
end open location
EOF

mkdir -p "$HOME/Applications"
rm -rf "$APP"
osacompile -o "$APP" "$src"
plist="$APP/Contents/Info.plist"
plutil -replace CFBundleIdentifier -string dev.emailops.task-handler "$plist"
plutil -replace LSBackgroundOnly -bool true "$plist"
plutil -replace CFBundleURLTypes -json '[{"CFBundleURLName":"EmailOps task","CFBundleURLSchemes":["emailops-task"]}]' "$plist"
codesign --force --sign - "$APP"  # editing Info.plist invalidated osacompile's ad-hoc signature
"$LSREGISTER" -f "$APP"
echo "installed $APP -> $ROOT/scripts/tasks.py"
