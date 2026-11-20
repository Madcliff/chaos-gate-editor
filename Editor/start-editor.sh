#!/bin/sh
set -eu
editor_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
exec "$editor_dir/runtime/bin/python3" -IB "$editor_dir/editor.py" "$@"
