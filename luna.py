#!/usr/bin/env python3
import argparse
import glob
import os
import sys
import time

from contextlib import contextmanager
from io import StringIO
from typing import TYPE_CHECKING

from moon.syn import Directive
from moon.util import dbg

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable, Iterator, Sequence

    from lib import Writer


# ssh(1): the options that take no argument.
FLAGS = frozenset('46AaCfGgKkMNnqsTtVvXxYy')

JUMP_OPTS = frozenset(('proxycommand', 'proxyjump'))


def walk(argv: Iterable[str]) -> Iterator[tuple[int, str, str]]:
    # Yields each option that takes an argument as (index, letter, value), and
    # the destination, the first positional argument, as (index, '', host).
    # ssh keeps parsing options after the destination, up to the command.
    it = iter(enumerate(argv))
    found = False
    for i, a in it:
        if a == '--':
            if not found and (t := next(it, None)):
                yield t[0], '', t[1]
            return

        if not a or a[0] != '-':
            if found or not a:
                return
            found = True
            yield i, '', a
            continue

        for j, c in enumerate(a[1:], 2):
            if c not in FLAGS:
                # The value is the rest of the word, or else the next word.
                yield i, c, a[j:] or next(it, (i, ''))[1]
                break


def find_host(argv: Iterable[str]) -> tuple[int, str] | None:
    return next(((i, v) for i, c, v in walk(argv) if not c), None)


def sets_jump(opts: Iterable[str]) -> bool:
    # An `-o` value is written in ssh_config(5) syntax.
    return any(c == 'J' or (c == 'o' and Directive(v).opt in JUMP_OPTS) for _, c, v in walk(opts))


class Args(argparse.Namespace):
    input_file: str | None
    zone_file: str
    output_file: str | None
    header: str | None
    ssh_executable: str | None
    force: int
    print_cmd: bool
    host_or_args: list[str]

    # Set by `main` before generating or rewriting.
    host: str | None = None
    state: str | None = None
    last_state: str | None = None


def rewrite(argv: list[str], args: Args) -> Sequence[str]:
    if not (t := find_host(argv)):
        return argv

    idx, host = t
    if sets_jump(argv):
        # The command line takes precedence over ssh_config in generator mode too.
        return argv

    if (p := host.find('@')) >= 0:
        prefix = host[: p + 1]
        host = host[p + 1 :]
    else:
        prefix = ''

    from lib import resolve

    args.host = host
    host, jumps = resolve(host, args)

    argv[idx] = prefix + host
    if jumps:
        return ('-J', jumps, *argv)

    return argv


@contextmanager
def open_output(file: str) -> Generator[StringIO]:
    buf = StringIO()
    yield buf
    # Only write the file at the last moment to avoid truncating it on error.
    with open(file, 'w', encoding='utf-8') as fp:
        fp.write(buf.getvalue())


def write_outputs(r: Writer, file: str) -> None:
    with open_output(file) as fp:
        r.write(fp)

    with open_output(file + '.flat') as fp:
        r.write_flat(fp)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--input-file')
    parser.add_argument('-z', '--zone-file', default='zone.ini')
    parser.add_argument('-o', '--output-file')
    parser.add_argument('-H', '--header')
    parser.add_argument('-x', '--ssh-executable')
    parser.add_argument('-f', '--force', action='count', default=0)
    parser.add_argument('-p', '--print-cmd', action='store_true')
    parser.add_argument('host_or_args', nargs='*')
    a = parser.parse_args(namespace=Args())

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

            ret = subprocess.run(cmd).returncode  # noqa: PLW1510, S603
            sys.exit(ret)
        else:
            os.execvp(cmd[0], cmd)

        return None

    if not (input_file := a.input_file):
        parser.error('generator mode requires -i/--input-file')

    from lib import generate, preview
    from moon.lock import wait_lock

    a.host = a.host_or_args[0] if a.host_or_args else None

    if (file := a.output_file) == '-':
        file = a.output_file = None

    if not file or a.force > 1:
        if r := generate(input_file, a):
            if file:
                write_outputs(r, file)
            else:
                r.write(sys.stdout)
        return None

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
        # A missing state means the file carries no routes, as after a direct run.
        if not a.force and last_state is not None:
            try:
                mtime = os.path.getmtime(file)
            except FileNotFoundError:
                pass
            else:
                if (dt := time.time() - mtime) <= 2:
                    base = os.path.basename(file)
                    dbg(f'{base}: updated {dt * 1000:.3f} ms ago, skipping')
                    return preview(file, a)

                here = os.path.dirname(__file__)
                sources = (os.path.join(here, '*.py'), os.path.join(here, 'moon', '*.py'))
                deps = (input_file, a.zone_file, *(f for s in sources for f in glob.glob(s)))
                dep_mtime = max(map(os.path.getmtime, deps))
                if mtime >= dep_mtime:
                    a.last_state = last_state

        if r := generate(input_file, a):
            write_outputs(r, file)

            if (state := a.state) is not None and state != last_state:
                with open(state_file, 'w', encoding='utf-8') as fp:
                    fp.write(state)
        else:
            return preview(file, a)


if __name__ == '__main__':
    main()
