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

arg="$*"
if [ -t 1 ] && [ -n "$arg" ]; then
  arg="\e[1;31m$arg\e[0m"
fi

if [ -n "$LUNA_SSH_DIRECT" ]; then
  echo -e "luna: direct to $arg"
  exec cp -- sshconfig "$file"
fi

if command -v python3 >/dev/null 2>&1; then
  py=python3
else
  py=python
fi

if rev="$(git rev-parse --short HEAD)"; then
  at=" @ $rev"
fi

# https://stackoverflow.com/a/37216784
if [[ $VIRTUAL_ENV && $PATH =~ (^|:)"$VIRTUAL_ENV/bin"($|:) ]]; then
  echo "luna: detaching from $VIRTUAL_ENV"
  PATH=${PATH%":$VIRTUAL_ENV/bin"}
  PATH=${PATH#"$VIRTUAL_ENV/bin:"}
  PATH=${PATH//":$VIRTUAL_ENV/bin:"/}
  unset PYTHONHOME VIRTUAL_ENV
fi

if [ -n "$arg" ]; then
  echo -e "luna: connecting to $arg$at"
else
  echo "luna: generating $file$at"
fi

header="# Generated from 🥮$at at $(date). DO NOT EDIT!"
exec $py "$here"/luna.py -H "$header" -o "$file" -i "$input_file" "$@"
