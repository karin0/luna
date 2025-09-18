import os
import sys

if sys.stderr.isatty():
    try:
        from rich.console import Console
    except ImportError:

        def dbg_print(*args, must=False):
            print(*args, file=sys.stderr)

    else:
        from rich.markup import escape

        console = Console(file=sys.stderr)

        def dbg_print(*args, must=False):
            console.print(
                *(escape(str(x)) for x in args), style=None if must else 'dim'
            )

else:

    def dbg_print(*args, must=False):
        if must:
            print(*args, file=sys.stderr)
            sys.stderr.flush()


_dbg = dbg_print
_time = None
_time0 = None


def dbg(*args, **kwargs):
    _dbg(*args, **kwargs)


def set_dbg(f=dbg_print):
    global _dbg
    _dbg = f


if os.environ.get('MOON_TRACE'):

    def trace(*args, **kwargs):
        import time

        t = time.monotonic() * 1000
        global _time, _time0
        if _time:
            dt = t - _time
            dt0 = t - _time0
            _time = t
        else:
            _time = _time0 = t
            dt = dt0 = 0

        dbg(f'[{dt:6.3f} {dt0:7.3f}]', *args, **kwargs)

else:

    def trace(*args, **kwargs):
        pass
