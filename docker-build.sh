#!/bin/bash
# Build and run the public standalone ModelSEED API profile.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

docker compose --project-directory "$SCRIPT_DIR" up --build "$@"
