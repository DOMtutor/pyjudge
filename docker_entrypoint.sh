#!/usr/bin/env bash
set -euo pipefail

if [ -z "${1:-}" ]; then
    echo "Error: No tool specified."
    echo "Usage: docker run <image> [fuzzer|selfservice] [gunicorn options]"
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
        # Fuzzing runs and their state live in the worker process: use exactly one
        exec gunicorn --bind 0.0.0.0:8000 --workers 1 "pydomjudge.tools.fuzzer:run_app()" "$@"
        ;;
    *)
        echo "Error: Unknown tool '$TOOL'."
        exit 1
        ;;
esac
