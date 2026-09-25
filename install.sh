#!/bin/bash
set -eo pipefail

exec 1>&2
file="$HOME/.ssh/config.inc"
input_file=sshconfig
here="$(realpath -m "$0/..")"

# `--` is not handled to allow passing `-z` in `config`.
while true; do
  case "$1" in
    -c) cd "$2"; shift 2 ;;
    -i) input_file="$2"; shift 2 ;;
    -o) file="$2"; shift 2 ;;
    *) break ;;
  esac
done

# shellcheck source=prelude.sh
source "$here/prelude.sh"

if [ -n "$LUNA_SSH_DIRECT" ]; then
  dbg "direct to $arg"
  # The copy carries no routes, so the next routed run has to regenerate.
  rm -f -- "$file.state"
  exec cp -- "$input_file" "$file"
fi

find_python

if rev="$(git rev-parse --short HEAD 2>/dev/null)"; then
  at=" @ $rev"
fi

if [ -n "$arg" ]; then
  dbg "connecting to $arg$at"
else
  dbg "generating $file$at"
fi

header="# Generated from 🥮$at at $(date). DO NOT EDIT!"
exec $py "$here"/luna.py -H "$header" -o "$file" -i "$input_file" "$@"
