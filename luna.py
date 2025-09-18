#!/usr/bin/env python3
import os
import sys
import time
import argparse
from typing import Iterable

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
    parser.add_argument('-x', '--ssh-executable')
    parser.add_argument('host_or_args', nargs='*')
    a = parser.parse_args()

    if ssh := a.ssh_executable:
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
        cmd = (ssh, *argv)
        if os.name == 'nt':
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

    if file := a.output_file:
        with wait_lock(file + '.lock') as waited:
            if waited:
                return preview(file, a)

            # Check if the file is updated too recently.
            # We check this after acquiring the lock, to avoid terminating before
            # the holding process finishes writing.
            try:
                mtime = os.path.getmtime(file)
            except FileNotFoundError:
                pass
            else:
                if (dt := time.time() - mtime) <= 2:
                    dbg(f'{file}: updated {dt * 1000:.3f} ms ago, skipping')
                    return preview(file, a)

            buf = StringIO()
            generate(buf, a)
            buf = buf.getvalue()

            # Only write the file at the last moment to avoid truncating it on error.
            with open(file, 'w', encoding='utf-8') as fp:
                fp.write(buf)
    else:
        generate(sys.stdout, a)


if __name__ == '__main__':
    main()
