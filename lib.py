import itertools

from typing import TYPE_CHECKING, TextIO

from cfg import ZoneConfig
from moon import util
from moon.syn import Config
from moon.util import dbg, highlight

if TYPE_CHECKING:
    from collections.abc import Callable

    from luna import Args

# Styles for the host names from ssh_config, the zones and the destination.
NAME = 'italic bright_yellow'
ZONE = 'bright_blue'
HOST = 'bold bright_red'


def flush_dbg(file: TextIO) -> None:
    for line in util.lines:
        print(*line, file=file)

    if util.lines:
        util.lines.clear()
        print(file=file)


def generate(input_file: str, args: Args) -> Callable[[TextIO], None] | None:
    with open(input_file, encoding='utf-8') as fp:
        c = Config(fp)

    cfg = ZoneConfig(args.zone_file, c)
    host = args.host
    highlight(
        (
            (NAME, c.hosts()),
            (ZONE, cfg.zones()),
            (HOST, (host,) if host else ()),
        )
    )

    if host and (real_host := cfg.resolve_direct(host)):
        dbg('Direct for', real_host, must=real_host != host)

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

    # A zone alias is another address of its canonical host, so host lists leave it out.
    c.unlist(frozenset(g.aliases()))

    def write(file: TextIO) -> None:
        if args.header:
            print(args.header, file=file)

        if not file.isatty():
            flush_dbg(file)

        c.print(file, separator=args.header)

        if args.header:
            print(args.header, file=file)

    return write


def resolve(host: str, args: Args) -> tuple[str, str]:
    c = None
    if args.input_file:
        # The ssh_config is optional and only used for discovering hosts here.
        with open(args.input_file, encoding='utf-8') as fp:
            c = Config(fp)

    cfg = ZoneConfig(args.zone_file, c)

    highlight(((NAME, c.hosts() if c else ()), (ZONE, cfg.zones()), (HOST, (host,))))

    if real_host := cfg.resolve_direct(host):
        dbg('Direct for', real_host, must=real_host != host)
        return real_host, ''

    return cfg.route(host).resolve(host) or (host, '')


def dbg_query(c: Config, host: str) -> None:
    groups = itertools.groupby(c.query(host), key=lambda line: line.blk)
    for blk, lines in groups:
        hosts = '<auto>' if blk.ext else ', '.join(blk.hosts)
        dbg(f'{hosts}: {', '.join(lines)}')


def preview(file: str, args: Args) -> None:
    if not (host := args.host):
        return

    with open(file, encoding='utf-8') as fp:
        c = Config(fp)

    highlight(((NAME, c.hosts()), (HOST, (host,))))

    dbg_query(c, host)
