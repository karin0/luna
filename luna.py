#!/usr/bin/env python3
import os
import sys
import time
import datetime
import argparse
import itertools
import configparser
import importlib.util

from io import StringIO
from typing import Iterable, TextIO

from moon.env import Environment
from moon.syn import Config
from moon.lock import wait_lock
from moon.intf import Interfaces
from moon.route import Zone, ZoneSet
from moon.util import dbg, set_dbg, dbg_print

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


interfaces = None
timezone = None


def check_timezone(hours: int) -> bool:
    global timezone
    if timezone is None:
        timezone = (
            datetime.datetime.now(datetime.timezone.utc)
            .astimezone()
            .utcoffset()
            .total_seconds()
        )

    return timezone == hours * 3600


def in_zone(cfg, zone):
    if subnets := cfg.get(zone, 'subnet', fallback='').split():
        global interfaces
        if not interfaces:
            interfaces = Interfaces()

        for s in subnets:
            if not interfaces.check_subnet(s):
                return False

    if tz := cfg.get(zone, 'timezone', fallback=None):
        if not check_timezone(float(tz)):
            return False

    return True


CWD = os.path.realpath(os.getcwd())


def load_hook(file):
    # The hook file must be inside the cwd.
    if os.path.commonpath((CWD, os.path.realpath(file))) != CWD:
        raise ValueError(file)

    spec = importlib.util.spec_from_file_location('hook', file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ZoneConfig:
    def __init__(self, file) -> None:
        cfg = configparser.ConfigParser()
        cfg.read(file)

        self._hooks = hooks = []
        self.g = g = ZoneSet()

        self.zones: dict[str, Zone] = {}
        zones = self.zones

        for sect in cfg.sections():
            hosts = cfg.get(sect, 'host', fallback='').split()
            hosts = tuple(spec.split(':') for spec in hosts)
            src = in_zone(cfg, sect)
            zones[sect] = zone = g.add(sect, hosts, src=src)

            if hook := cfg.get(sect, 'hook', fallback=None):
                hooks.append(load_hook(hook))

        def parse_arc(arc: str) -> tuple[Zone | None, str, int | None]:
            parts = arc.split(':')

            try:
                # via:to:cost
                via, to, cost = parts
                return zones[to], via, int(cost)
            except (ValueError, KeyError):
                try:
                    via, to = parts
                    try:
                        # via/to:cost
                        cost = int(to)
                        spec = via
                    except ValueError:
                        # via:to
                        return zones[to], via, None
                except ValueError:
                    # via/to
                    spec = arc
                    cost = None

                # Direct link to a zone is preferred.
                try:
                    to = zones[spec]
                    via = ''
                except KeyError:
                    # Target zone is resolved from the `via`.
                    to = None
                    via = spec

            return to, via, cost

        for sect, zone in zones.items():
            arcs = cfg.get(sect, 'arc', fallback='').split()
            for arc in arcs:
                to, via, cost = parse_arc(arc)
                if cost is None:
                    g.arc(zone, to, via)
                else:
                    g.arc(zone, to, via, cost)

    def run_hooks(self, name, *args, **kwargs):
        for h in self._hooks:
            if f := getattr(h, name, None):
                f(*args, **kwargs)


ctx = Environment()


def do_sub(cmd):
    if cmd in ctx:
        cmd = ctx[cmd]

    return cmd.strip()


def _generate(file: TextIO, args):
    with open(args.input_file, encoding='utf-8') as fp:
        c = Config(fp)

    cfg = ZoneConfig(args.zone_file)
    g = cfg.g
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

    direct = False
    if host:
        real_host = host.removeprefix('d.')
        if real_host != host:
            # Assert a direct mode
            direct = True
            c.attach(host, real_host)

    if direct:
        dbg('Direct for', host, must=True)
    else:
        g.route()

        for z, dist, way in g.iter_zones():
            if way is not None:
                must = host and g.contains(z, host)
                dbg('[' + ', '.join(way) + ']', '->', z, f'({dist})', must=must)

        try:
            if host and g.trace(host) is None:
                dbg('No route to host', host, must=True)
        except KeyError:
            pass

        g.inject(c)

    if host:
        dbg_query(c, host)

    if not file.isatty():
        flush_dbg(file)

    c.print(file)


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


def generate(file: TextIO, args):
    if args.header:
        print(args.header, file=file)
    _generate(file, args)
    if args.header:
        print(args.header, file=file)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--input-file', default='config')
    parser.add_argument('-z', '--zone-file', default='zone.ini')
    parser.add_argument('-o', '--output-file')
    parser.add_argument('-H', '--header')
    parser.add_argument('host', nargs='?')
    a = parser.parse_args()

    if file := a.output_file:
        with wait_lock(file + '.lock') as waited:
            if waited:
                return preview(file, a)

            # Check if the file is updated too recently.
            # We check this after acquiring the lock, to avoid terminating before
            # the holding process finishes writing.
            try:
                mtime = os.path.getmtime(file)
            except FileNotFoundError:
                pass
            else:
                if (dt := time.time() - mtime) <= 2:
                    dbg(f'{file}: updated {dt * 1000:.3f} ms ago, skipping')
                    return preview(file, a)

            buf = StringIO()
            generate(buf, a)
            buf = buf.getvalue()

            # Only write the file at the last moment to avoid truncating it on error.
            with open(file, 'w', encoding='utf-8') as fp:
                fp.write(buf)
    else:
        generate(sys.stdout, a)


if __name__ == '__main__':
    main()
