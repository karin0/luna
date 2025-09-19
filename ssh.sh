#!/bin/bash
set -eo pipefail

# To use in wrapper mode, we need exact paths.
: "${LUNA_SSH:=ssh}" \
  "${LUNA_ENTRY:=~/.ssh/luna/luna.py}" \
  "${LUNA_ZONE:=~/.ssh/zone.ini}"

# `-i` is passed even if LUNA_CONFIG is empty to disable host discovery.
luna=("$LUNA_ENTRY" -x "$LUNA_SSH" -z "$LUNA_ZONE" -i "$LUNA_CONFIG")

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
export LUNA_SSH_DIRECT=1

if [ "$OS" = "Windows_NT" ]; then
  # Windows doesn't support exec properly.
  export FORCE_COLOR=1 TTY_INTERACTIVE=1
  eval "exec $($py "${luna[@]}" -p -- "$@")"
else
  exec $py "${luna[@]}" -- "$@"
fi
