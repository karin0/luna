import os
import sys

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


def _plain(line: tuple[str, ...], must: bool) -> None:
    print(*line, file=sys.stderr, flush=True)


_emit: Callable[[tuple[str, ...], bool], None] = _plain
if sys.stderr.isatty():
    try:
        from rich.console import Console
    except ImportError:
        pass
    else:
        from rich.markup import escape

        console = Console(file=sys.stderr)

        def _rich(line: tuple[str, ...], must: bool) -> None:
            console.print(*map(escape, line), style=None if must else 'dim')

        _emit = _rich

_MUTE = 'LUNA_MUTE' in os.environ
_VERBOSE = 'LUNA_VERBOSE' in os.environ

# Every diagnostic line, which generator mode writes into its output as comments.
lines: list[tuple[str, ...]] = []
# Monotonic milliseconds of the first and the latest `trace`.
_clock: tuple[float, float] | None = None


def dbg(*args: object, must: bool = False) -> None:
    line = ('#', *map(str, args))
    lines.append(line)
    if not _MUTE and (must or _VERBOSE):
        _emit(line, must)


if os.environ.get('MOON_TRACE'):

    def trace(*args: object, must: bool = False) -> None:
        import time

        global _clock
        t = time.monotonic() * 1000
        start, last = _clock or (t, t)
        _clock = (start, t)
        dbg(f'[{t - last:6.3f} {t - start:7.3f}]', *args, must=must)

else:

    def trace(*args: object, must: bool = False) -> None:
        pass
