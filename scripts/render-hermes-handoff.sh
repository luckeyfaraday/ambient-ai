#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHONPATH=src python3 -m ambient_ai render-hermes --output context/hermes-handoff.md
