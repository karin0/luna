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


def dbg(*args, **kwargs):
    _dbg(*args, **kwargs)


def set_dbg(f=dbg_print):
    global _dbg
    _dbg = f


def get_stem(line: str) -> str:
    p = line.find('#')
    if p >= 0:
        line = line[:p]
    return line.strip()
