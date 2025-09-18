import itertools

from typing import Iterable, TextIO

from moon.env import Environment
from moon.syn import Config
from moon.route import ZoneSet
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

    console.push_theme(
        Theme(
            {
                'repr.luna_name': 'italic bright_yellow',
                'repr.luna_zone': 'bright_blue',
                'repr.luna_host': 'bold bright_red',
            }
        )
    )
    console.highlighter = ReprHighlighter()

    def register_highlights(rules: Iterable[tuple[str, Iterable[str]]]):
        console.highlighter.highlights[0:0] = [
            re.compile(
                r'\b(?P<luna_'
                + name
                + r'>'
                + r'|'.join(map(re.escape, sorted(strs, key=len, reverse=True)))
                + r')\b'
            )
            for name, strs in rules
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


def generate(file: TextIO, args):
    if args.header:
        print(args.header, file=file)

    with open(args.input_file, encoding='utf-8') as fp:
        c = Config(fp)

    cfg = ZoneConfig(args.zone_file)
    host = args.host

    if register_highlights:
        highlights = [
            ('name', c.hosts()),
            ('zone', cfg.zones.keys()),
        ]
        if host:
            highlights.append(('host', (host,)))
        register_highlights(highlights)

    if ctx:
        sub_res = c.sub(do_sub)

        for k, v in sub_res.items():
            if v:
                dbg(k + '\t| ' + v)

    if host and (real_host := cfg.resolve_direct_mode(host)):
        dbg('Direct for', real_host, must=True)
        c.attach(host, real_host)
    else:
        g = cfg.route()
        dbg_zones(g, host)

        if host and g.trace(host) is None:
            dbg('No route to host', host, must=True)

        g.inject(c)

    if host:
        dbg_query(c, host)

    if not file.isatty():
        flush_dbg(file)

    c.print(file, separator=args.header)

    if args.header:
        print(args.header, file=file)


def resolve(args) -> tuple[str, str]:
    cfg = ZoneConfig(args.zone_file)
    host = args.host
    assert host

    if register_highlights:
        highlights = (
            ('zone', cfg.zones.keys()),
            ('host', (host,)),
        )
        register_highlights(highlights)

    if real_host := cfg.resolve_direct_mode(host):
        dbg('Direct for', real_host, must=True)
        return real_host, ''

    g = cfg.route()
    dbg_zones(g, host)

    if res := g.resolve(host):
        return res

    dbg('No route to host', host, must=True)
    return host, ''


def dbg_zones(g: ZoneSet, host: str):
    for z, dist, way in g.iter_zones():
        if way is not None:
            must = host and g.contains(z, host)
            dbg('[' + ', '.join(way) + ']', '->', z, f'({dist})', must=must)


def dbg_query(c: Config, host: str):
    groups = itertools.groupby(c.query(host), key=lambda line: line.blk)
    for blk, lines in groups:
        hosts = ', '.join(blk.hosts) if blk.hosts else '<auto>'
        dbg(f'{hosts}: {', '.join(lines)}')


def preview(file: str, args):
    if not (host := args.host):
        return

    with open(file, encoding='utf-8') as fp:
        c = Config(fp)

    if register_highlights:
        register_highlights((('name', c.hosts()), ('host', (host,))))

    dbg_query(c, host)
