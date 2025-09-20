import os
import datetime
import functools
import importlib.util

from typing import Iterable, Sequence
from configparser import ConfigParser
from ipaddress import AddressValueError, IPv4Address, IPv4Network

from moon.intf import Interfaces
from moon.route import Zone, ZoneSet
from moon.util import dbg, trace
from moon.syn import Config

if not os.environ.get('LUNA_STRICT_SUBNET'):
    try:
        # Use faster gateway lookup by default when `netifaces` is available.
        # This is more permissive, and may not work in Termux.
        from moon.intf import Gateways as Interfaces
    except ImportError:
        pass

interfaces = None


@functools.cache
def get_timezone() -> int:
    return int(
        datetime.datetime.now(datetime.timezone.utc)
        .astimezone()
        .utcoffset()
        .total_seconds()
    )


@functools.cache
def get_interfaces() -> Interfaces:
    trace('>Interfaces')
    interfaces = Interfaces()
    trace('Interfaces')
    dbg(interfaces)
    return interfaces


def in_zone(tz: float | None, subnets: Sequence[IPv4Network]) -> bool:
    # AND for timezone and subnet, so no constraint means always hits.
    if tz is not None and get_timezone() != tz * 3600:
        return False

    if subnets:
        interfaces = get_interfaces()

        # OR for all subnets.
        return any(interfaces.check_subnet(s) for s in subnets)

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
    def __init__(self, file, conf: Config | None = None) -> None:
        self._cfg = cfg = ConfigParser()
        if not cfg.read(file):
            raise FileNotFoundError(file)

        self._hooks = hooks = []
        self._g = g = ZoneSet()

        self._zones: dict[str, Zone] = {}
        self._conds: list[tuple[float, tuple[IPv4Network, ...]]] = []

        zones = self._zones
        zone_stubs = []
        vis = set()

        if conf:
            smart_stubs = []

        for sect in cfg.sections():
            hosts = cfg.get(sect, 'host', fallback='').split()
            hosts = [spec.split(':') for spec in hosts]

            for aliases in hosts:
                for alias in aliases:
                    if alias in vis:
                        raise ValueError(f'Duplicate name {alias} in zone {sect}')
                    vis.add(alias)

            subnets = tuple(
                IPv4Network(cidr, strict=False)
                for cidr in cfg.get(sect, 'subnet', fallback='').split()
            )

            stub = (sect, hosts, subnets)
            zone_stubs.append(stub)

            if conf and not cfg.getboolean(sect, 'strict-host', fallback=False):
                smart_stubs.append(stub)

        if conf and smart_stubs:
            # Find SSH hosts in the given subnets smartly.
            all_hosts = curr_host = None
            for host, hostname in sorted(conf.hostnames()):
                if host in vis:
                    continue

                try:
                    ip = IPv4Address(hostname)
                except AddressValueError:
                    continue

                for zone, hosts, subnets in smart_stubs:
                    for net in subnets:
                        if ip in net:
                            # Find a canonical host, now find all its aliases
                            # with the same prefix.
                            if all_hosts is None:
                                all_hosts = iter(
                                    h
                                    for h in sorted(h for h in conf.hosts())
                                    if h not in vis
                                )

                            aliases = [host]

                            while curr_host != host:
                                curr_host = next(all_hosts, None)

                            while (
                                curr_host := next(all_hosts, None)
                            ) and curr_host.startswith(host):
                                vis.add(curr_host)
                                aliases.append(curr_host)

                            hosts.append(aliases)
                            break
                    else:
                        continue
                    break

        for sect, hosts, subnets in zone_stubs:
            zones[sect] = zone = g.add(hosts)
            self._conds.append((cfg.getfloat(sect, 'timezone', fallback=None), subnets))

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
                        # via|to:cost
                        cost = int(to)
                        spec = via
                    except ValueError:
                        # via:to
                        return zones[to], via, None
                except ValueError:
                    # via|to
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

    def get_state(self) -> str:
        r = []
        if any(tz is not None for tz, _ in self._conds):
            r.append('tz:' + str(get_timezone()))
        if any(subnets for _, subnets in self._conds):
            r.append('if:' + str(get_interfaces()))
        return '|'.join(r)

    def route(self, host: str | None) -> ZoneSet:
        g = self._g
        for zone, (tz, subnets) in zip(self._zones.values(), self._conds):
            if in_zone(tz, subnets):
                g.set_src(zone)

        g.route()

        host_way = None
        if host:
            try:
                host_way = g.trace(host)
            except KeyError:
                pass
            else:
                if host_way is None:
                    dbg('No route to', host, must=True)

        specs = []
        for name, zone in sorted(
            self._zones.items(), key=lambda t: t[1].dist, reverse=True
        ):
            if (way := zone.path) is not None:
                if must := zone.traced:
                    if (
                        host_way is not None
                        and not g.contains(zone, host)
                        and len(way) < len(host_way)
                        and host_way[: len(way)] == way
                    ):
                        way = (
                            '['
                            + ', '.join(way)
                            + '; '
                            + ', '.join(host_way[len(way) :])
                            + ']'
                        )
                        host_way = None
                    else:
                        way = '[' + ', '.join(way) + ']'
                else:
                    way = '[' + ', '.join(way) + ']'

                z = f'{{{name}: {', '.join(h.name for h in zone.hosts)}}}'
                specs.append((way, z, zone.dist, must))

        for way, z, dist, must in reversed(specs):
            dbg(way, '->', z, f'({dist})', must=must)

        return g

    def run_hooks(self, name, *args, **kwargs):
        for h in self._hooks:
            if f := getattr(h, name, None):
                f(*args, **kwargs)

    def resolve_direct(self, host: str) -> str | None:
        if host not in self._g:
            if (real := host.removeprefix('d.')) != host and real in self._g:
                return real

            # Direct for the unmanaged host.
            return host

    def zones(self) -> Iterable[str]:
        return self._zones.keys()
