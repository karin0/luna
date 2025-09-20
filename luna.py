#!/usr/bin/env python3
import os
import sys
import time
import argparse
from typing import Iterable, Sequence

from moon.util import dbg


def find_host(argv: Iterable[str]) -> tuple[int, str] | None:
    # ssh(1)
    FLAGS = frozenset('46AaCfGgKkMNnqsTtVvXxYy')

    # Find the first positional argument (host/destination).
    it = iter(enumerate(argv))
    while t := next(it, None):
        if (a := t[1]) and a[0] == '-':
            if a == '--':
                return next(it, None)

            a = a[1:]
            for i, c in enumerate(a):
                if c not in FLAGS:
                    # All other options take an argument.
                    if i == len(a) - 1:
                        # The next argument is its value.
                        next(it, None)
                    break
        else:
            return t if a else None


def rewrite(argv: list[str], args) -> Sequence[str]:
    if not (t := find_host(argv)):
        return argv

    idx, host = t
    if (p := host.find('@')) >= 0:
        host = host[p + 1 :]
        prefix = host[: p + 1]
    else:
        prefix = ''

    from lib import resolve

    args.host = host
    host, jumps = resolve(host, args)

    argv[idx] = prefix + host
    if jumps:
        return ('-J', jumps, *argv)

    return argv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--input-file', default='config')
    parser.add_argument('-z', '--zone-file', default='zone.ini')
    parser.add_argument('-o', '--output-file')
    parser.add_argument('-H', '--header')
    parser.add_argument('-f', '--force', action='count', default=0)
    parser.add_argument('-x', '--ssh-executable')
    parser.add_argument('-p', '--print-cmd', action='store_true')
    parser.add_argument('host_or_args', nargs='*')
    a = parser.parse_args()

    if (ssh := a.ssh_executable) or a.print_cmd:
        # We intercept and modify the `argv` in this wrapper mode, instead of
        # parsing and generating ssh_config(5) files with our unreliable parser.
        #
        # This should be more robust and respectful to existing configs, but
        # requires the wrapper to be set up in PATH for all integrations to work.

        if argv := a.host_or_args:
            try:
                argv = rewrite(argv, a)
            except Exception:
                # Keep the original argv on error.
                import traceback

                traceback.print_exc()

        dbg('luna: executing', repr(' '.join(argv)), must=True)
        cmd = (ssh or 'ssh', *argv)
        if a.print_cmd:
            import shlex

            print(shlex.join(cmd))
        elif os.name == 'nt':
            import subprocess

            ret = subprocess.run(cmd).returncode
            sys.exit(ret)
        else:
            os.execvp(ssh, cmd)

        return

    from moon.lock import wait_lock
    from lib import preview, generate
    from io import StringIO

    a.host = a.host_or_args[0] if a.host_or_args else None
    a.state = a.last_state = None

    if (file := a.output_file) == '-':
        file = a.output_file = None

    if not file or a.force > 1:
        if writer := generate(a):
            writer(open(file, 'w', encoding='utf-8') if file else sys.stdout)
        return

    with wait_lock(file + '.lock') as waited:
        if waited:
            # XXX: It's possible that the previous holder generated a conflicting
            # config, but it could be even worse if we overwrite it with ours
            # before the previous SSH session finishes reading the file.
            # This can be hardly avoided with support for 'd.' hosts.
            return preview(file, a)

        state_file = file + '.state'

        try:
            with open(state_file, encoding='utf-8') as fp:
                last_state = fp.read().strip()
        except FileNotFoundError:
            last_state = None

        # Check if the file is updated too recently.
        # We check this after acquiring the lock, to avoid terminating before
        # the holding process finishes writing.
        if not a.force:
            try:
                mtime = os.path.getmtime(file)
            except FileNotFoundError:
                pass
            else:
                if (dt := time.time() - mtime) <= 2:
                    base = os.path.basename(file)
                    dbg(f'{base}: updated {dt * 1000:.3f} ms ago, skipping')
                    return preview(file, a)

                dep_mtime = max(
                    os.path.getmtime(f) for f in (a.input_file, a.zone_file)
                )
                if mtime >= dep_mtime:
                    a.last_state = last_state

        if writer := generate(a):
            buf = StringIO()
            writer(buf)
            buf = buf.getvalue()

            # Only write the file at the last moment to avoid truncating it on error.
            with open(file, 'w', encoding='utf-8') as fp:
                fp.write(buf)

            if (state := a.state) and state != last_state:
                with open(state_file, 'w', encoding='utf-8') as fp:
                    fp.write(state)
        else:
            return preview(file, a)


if __name__ == '__main__':
    main()
