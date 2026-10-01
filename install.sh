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

if [ -n "$arg" ]; then
  dbg "connecting to $arg"
else
  dbg "generating $file"
fi

exec $py "$here"/luna.py -o "$file" -i "$input_file" "$@"
