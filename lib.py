import itertools

from typing import Callable, Iterable, TextIO

from moon.env import Environment
from moon.syn import Config
from moon.util import dbg, set_dbg, dbg_print

from cfg import ZoneConfig

try:
    from moon.util import console
except ImportError:
    register_highlights = None
else:
    import re
    from rich.highlighter import ReprHighlighter
    from rich.theme import Theme

    theme = {
        'repr.luna_name': 'italic bright_yellow',
        'repr.luna_zone': 'bright_blue',
        'repr.luna_host': 'bold bright_red',
    }
    console.push_theme(Theme(theme))
    console.highlighter = ReprHighlighter()

    def register_highlights(rules: Iterable[tuple[str, Iterable[str]]]):
        console.highlighter.highlights[0:0] = [
            re.compile(r'\b(?P<luna_' + name + r'>' + r'|'.join(words) + r')\b')
            for name, strs in rules
            if (
                words := tuple(
                    re.escape(s) for s in sorted(strs, key=len, reverse=True)
                )
            )
        ]


def do_dbg(*args, must=False):
    args = ('#', *map(str, args))
    dbg_print(*args, must=must)
    dbg_buf.append(args)


dbg_buf = []
set_dbg(do_dbg)


def flush_dbg(file: TextIO):
    set_dbg()
    for args in dbg_buf:
        print(*args, file=file)

    if dbg_buf:
        dbg_buf.clear()
        print(file=file)


ctx = Environment()


def do_sub(cmd):
    if cmd in ctx:
        cmd = ctx[cmd]

    return cmd.strip()


def generate(args) -> Callable[[TextIO], None] | None:
    with open(args.input_file, encoding='utf-8') as fp:
        c = Config(fp)

    cfg = ZoneConfig(args.zone_file, c)
    host = args.host

    if register_highlights:
        highlights = (
            ('name', c.hosts()),
            ('zone', cfg.zones()),
            ('host', (host,) if host else ()),
        )
        register_highlights(highlights)

    if ctx:
        sub_res = c.sub(do_sub)

        for k, v in sub_res.items():
            if v:
                dbg(k + '\t| ' + v)

    if host and (real_host := cfg.resolve_direct(host)):
        dbg('Direct for', real_host, must=True)

    if args.output_file:
        args.state = state = cfg.get_state().strip()
        if args.last_state == state:
            dbg('Up to date, skipping:', args.state)
            return None

    g = cfg.route(host)

    for name in g.names():
        c.attach('d.' + name, name)

    g.inject(c)

    if host := args.host:
        dbg_query(c, host)

    def writer(file: TextIO):
        if args.header:
            print(args.header, file=file)

        if not file.isatty():
            flush_dbg(file)

        c.print(file, separator=args.header)

        if args.header:
            print(args.header, file=file)

    return writer


def resolve(host: str, args) -> tuple[str, str]:
    c = None
    if args.input_file:
        # The ssh_config is optional and only used for discovering hosts here.
        with open(args.input_file, encoding='utf-8') as fp:
            c = Config(fp)

    cfg = ZoneConfig(args.zone_file, c)

    if register_highlights:
        highlights = (
            ('name', c.hosts() if c else ()),
            ('zone', cfg.zones()),
            ('host', (host,)),
        )
        register_highlights(highlights)

    if real_host := cfg.resolve_direct(host):
        dbg('Direct for', real_host, must=True)
        return real_host, ''

    return cfg.route(host).resolve(host) or (host, '')


def dbg_query(c: Config, host: str):
    groups = itertools.groupby(c.query(host), key=lambda line: line.blk)
    for blk, lines in groups:
        hosts = '<auto>' if blk.ext else ', '.join(blk.hosts)
        dbg(f'{hosts}: {', '.join(lines)}')


def preview(file: str, args):
    if not (host := args.host):
        return

    with open(file, encoding='utf-8') as fp:
        c = Config(fp)

    if register_highlights:
        register_highlights((('name', c.hosts()), ('host', (host,))))

    dbg_query(c, host)
