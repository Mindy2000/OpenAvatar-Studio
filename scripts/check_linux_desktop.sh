#!/usr/bin/env bash
set -euo pipefail
# Runs only on disposable CI runners, inside a private D-Bus session.
eval "$(printf '%s' 'ci-disposable-keyring' | gnome-keyring-daemon --unlock --components=secrets)"
xvfb-run -a python "$1"
