#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHONPATH="$SCRIPT_DIR/src" /usr/bin/python3 -c "from clipshot.capture import run; run()"
