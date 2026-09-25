# shellcheck shell=bash
# Sourced by install.sh and ssh.sh with the arguments that name the destination.

if [ -v LUNA_MUTE ] || [ ! -v LUNA_VERBOSE ]; then
  verbose=
  dbg() { :; }
  arg=
else
  verbose=1
  dbg() { echo -e "luna: $*" >&2; }
  arg="$*"
  if [ -t 2 ] && [ -n "$arg" ]; then
    arg="\e[1;31m$arg\e[0m"
  fi
fi

# Sets `py` to the Python found on PATH once any active virtualenv is left.
find_python() {
  if command -v python3 >/dev/null 2>&1; then
    py=python3
  else
    py=python
  fi

  # https://stackoverflow.com/a/37216784
  if [[ $VIRTUAL_ENV && $PATH =~ (^|:)"$VIRTUAL_ENV/bin"($|:) ]]; then
    dbg "detaching from $VIRTUAL_ENV"
    PATH=${PATH%":$VIRTUAL_ENV/bin"}
    PATH=${PATH#"$VIRTUAL_ENV/bin:"}
    PATH=${PATH//":$VIRTUAL_ENV/bin:"/}
    unset PYTHONHOME VIRTUAL_ENV
  fi
}
