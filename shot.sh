#!/usr/bin/env bash
# Quiet, non-interactive COSMIC screenshot for an AI observe→act loop.
# Prints the saved PNG path on stdout (last line) so callers can Read it.
# Usage: shot.sh [save-dir]   (default: /tmp/ai-screen)
set -euo pipefail
DIR="${1:-/tmp/ai-screen}"
mkdir -p "$DIR"
cosmic-screenshot --interactive=false --notify=false --save-dir "$DIR" | tail -n 1
