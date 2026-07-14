#!/usr/bin/env bash
set -euo pipefail
IFS="\n"

# Default to displaying help if no argument is provided
if [ -z "$1" ]; then
    echo "Error: No tool specified."
    echo "Usage: docker run <image> [fuzzer|selfservice]"
    exit 1
fi

TOOL=$1
shift

case "$TOOL" in
    "selfservice")
        echo "Starting Self-Service via Gunicorn..."
        exec gunicorn --bind 0.0.0.0:8000 "pydomjudge.tools.selfservice:create_app()" "$@"
        ;;
    "fuzzer")
        echo "Starting Fuzzer via Gunicorn"
        exec gunicorn --bind 0.0.0.0:8000 "pydomjudge.tools.fuzzer:run_app()" "$@"
        # exec python -m tools.my_cli_tool "$@"
        ;;
    *)
        echo "Error: Unknown tool '$TOOL'."
        exit 1
        ;;
esac