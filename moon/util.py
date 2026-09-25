import os
import re
import sys

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

# (style, pattern) pairs for rich to apply to the matching words.
_highlights: tuple[tuple[str, str], ...] = ()


def highlight(rules: Iterable[tuple[str, Iterable[str]]]) -> None:
    global _highlights
    _highlights = tuple(
        (style, r'\b(?:' + '|'.join(words) + r')\b')
        for style, strs in rules
        if (words := tuple(re.escape(s) for s in sorted(strs, key=len, reverse=True)))
    )


def _plain(line: tuple[str, ...], must: bool) -> None:
    print(*line, file=sys.stderr, flush=True)


def _init_rich(line: tuple[str, ...], must: bool) -> None:
    # Importing rich costs about as much as starting Python, so a run that
    # prints nothing never pays for it.
    global _emit
    try:
        from rich.console import Console
    except ImportError:
        _emit = _plain
    else:
        from rich.highlighter import ReprHighlighter
        from rich.markup import escape
        from rich.text import Text

        class Highlighter(ReprHighlighter):
            def highlight(self, text: Text) -> None:
                for style, pattern in _highlights:
                    text.highlight_regex(pattern, style)
                super().highlight(text)

        console = Console(file=sys.stderr, highlighter=Highlighter())

        def emit(line: tuple[str, ...], must: bool) -> None:
            console.print(*map(escape, line), style=None if must else 'dim')

        _emit = emit

    _emit(line, must)


_emit: Callable[[tuple[str, ...], bool], None] = _init_rich if sys.stderr.isatty() else _plain

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
