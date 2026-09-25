#!/bin/bash
set -eo pipefail

# To use in wrapper mode, we need exact paths.
: "${LUNA_SSH:=ssh}" \
  "${LUNA_ENTRY:=~/.ssh/luna/luna.py}" \
  "${LUNA_ZONE:=~/.ssh/zone.ini}"

luna=("$LUNA_ENTRY" -x "$LUNA_SSH" -z "$LUNA_ZONE" -i "$LUNA_CONFIG")

# The wrapper is often a copy or a link on PATH, so the repository is found from LUNA_ENTRY.
# shellcheck source=prelude.sh
source "$(dirname -- "$LUNA_ENTRY")/prelude.sh"

if [ -n "$verbose" ] && rev="$(git -C "$(dirname -- "$LUNA_ZONE")" rev-parse --short HEAD 2>/dev/null)"; then
  at=" @ $rev"
fi

if [ -n "$LUNA_SSH_DIRECT" ]; then
  dbg "direct to $arg"
  exec "$LUNA_SSH" "$@"
fi

find_python

dbg "connecting to $arg$at"
export LUNA_SSH_DIRECT=1

if [ "$OS" = "Windows_NT" ]; then
  # Windows doesn't support exec properly.
  export FORCE_COLOR=1 TTY_INTERACTIVE=1
  eval "exec $($py "${luna[@]}" -p -- "$@")"
else
  exec $py "${luna[@]}" -- "$@"
fi
