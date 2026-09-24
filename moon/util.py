import os
import sys

from typing import Protocol


class DbgSink(Protocol):
    def __call__(self, *args: object, must: bool = False) -> None: ...


if 'LUNA_MUTE' in os.environ:

    def dbg_print(*args: object, must: bool = False) -> None:
        pass

elif sys.stderr.isatty():
    try:
        from rich.console import Console
    except ImportError:

        def dbg_print(*args: object, must: bool = False) -> None:
            print(*args, file=sys.stderr)

    else:
        from rich.markup import escape

        console = Console(file=sys.stderr)

        def dbg_print(*args: object, must: bool = False) -> None:
            console.print(*(escape(str(x)) for x in args), style=None if must else 'dim')

else:

    def dbg_print(*args: object, must: bool = False) -> None:
        if must:
            print(*args, file=sys.stderr)
            sys.stderr.flush()


_dbg: DbgSink = dbg_print
# Monotonic milliseconds of the first and the latest `trace`.
_clock: tuple[float, float] | None = None


def dbg(*args: object, must: bool = False) -> None:
    _dbg(*args, must=must)


def set_dbg(f: DbgSink = dbg_print) -> None:
    global _dbg
    _dbg = f


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
