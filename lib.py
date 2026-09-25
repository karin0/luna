import itertools

from typing import TYPE_CHECKING, NamedTuple, TextIO

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


class Writer(NamedTuple):
    write: Callable[[TextIO], None]
    write_flat: Callable[[TextIO], None]


def generate(input_file: str, args: Args) -> Writer | None:
    with open(input_file, encoding='utf-8') as fp:
        c = Config(fp)

    cfg = ZoneConfig(args.zone_file, c)
    host = args.host
    cfg_hosts = tuple(c.hosts())

    highlight(
        (
            (NAME, cfg_hosts),
            (ZONE, cfg.zones()),
            (HOST, (host,) if host else ()),
        )
    )

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

    def write(file: TextIO, cfg: Config = c, *, annotate: bool = True) -> None:
        if args.header:
            print(args.header, file=file)

        if annotate and not file.isatty():
            flush_dbg(file)

        cfg.print(file, separator=args.header, annotate=annotate)

        if args.header:
            print(args.header, file=file)

    # VS Code Remote - SSH fails on inline comments and lists every `Host`, so the
    # flat config omits annotations and the generated 'd.' hosts, and keeps zone
    # aliases, which routes still jump through, out of the list.
    def write_flat(file: TextIO) -> None:
        aliases = frozenset(g.aliases())
        listed = (h for h in cfg_hosts if h not in aliases)
        unlisted = (h for h in cfg_hosts if h in aliases)
        write(file, c.select(listed, unlisted), annotate=False)

    return Writer(write, write_flat)


def resolve(host: str, args: Args) -> tuple[str, str]:
    c = None
    if args.input_file:
        # The ssh_config is optional and only used for discovering hosts here.
        with open(args.input_file, encoding='utf-8') as fp:
            c = Config(fp)

    cfg = ZoneConfig(args.zone_file, c)

    highlight(((NAME, c.hosts() if c else ()), (ZONE, cfg.zones()), (HOST, (host,))))

    if real_host := cfg.resolve_direct(host):
        dbg('Direct for', real_host, must=True)
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
