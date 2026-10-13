#!/bin/bash
# Double-click on macOS to run Avelora LAN Combat Manager.
cd "$(dirname "$0")" || exit 1
printf '\n  ╔══════════════════════════════════════╗\n  ║  AVELORA — LOCAL COMBAT MANAGER       ║\n  ╚══════════════════════════════════════╝\n\n'
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 isn't installed yet."
  echo "Install Python 3.9 or newer from https://www.python.org/downloads/macos/"
  echo "Then double-click START_Avelora.command again."
  echo "Your campaign files will stay in this folder."
  read -r -p "Press Return to close this window…" _
  exit 1
fi
python3 -c 'import sys; assert sys.version_info >= (3,9)' >/dev/null 2>&1
if [ $? -ne 0 ]; then
  echo "Please upgrade to Python 3.9 or newer from python.org."
  read -r -p "Press Return to close this window…" _
  exit 1
fi
echo "Starting local server. Keep this window OPEN during your session."
echo "If macOS asks for incoming network access, select Allow."
echo
python3 server.py --port 8765
status=$?
if [ "$status" -ne 0 ]; then
 echo "\nServer exited with an error. It may be that port 8765 is already in use."
 echo "Try quitting any other copy of Avelora first."
 read -r -p "Press Return to close this window…" _
fi
