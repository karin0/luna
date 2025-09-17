#!/bin/bash
set -eo pipefail

# To use in wrapper mode, we need exact paths.
: "${LUNA_SSH:=ssh}" \
  "${LUNA_ENTRY:=~/.ssh/luna/luna.py}" \
  "${LUNA_ZONE:=~/.ssh/zone.ini}"

arg="$*"
if [ -t 1 ] && [ -n "$arg" ]; then
  arg="\e[1;31m$arg\e[0m"
fi

if [ -n "$LUNA_SSH_DIRECT" ]; then
  echo -e "luna: direct to $arg"
  exec "$LUNA_SSH" "$@"
fi

if command -v python3 >/dev/null 2>&1; then
  py=python3
else
  py=python
fi

if rev="$(git -C "$(dirname -- "$LUNA_ZONE")" rev-parse --short HEAD)"; then
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

echo -e "luna: connecting to $arg$at"
LUNA_SSH_DIRECT=1 exec $py "$LUNA_ENTRY" -x "$LUNA_SSH" -z "$LUNA_ZONE" -- "$@"
