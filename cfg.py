import functools
import os
import time

from configparser import ConfigParser
from ipaddress import AddressValueError, IPv4Address, IPv4Network
from typing import TYPE_CHECKING, NamedTuple

from moon.intf import Interfaces
from moon.route import ARC_COST, Zone, ZoneSet
from moon.syn import Config
from moon.util import dbg, trace

if TYPE_CHECKING:
    from collections.abc import Container, Iterable, Iterator, Sequence

if not os.environ.get('LUNA_STRICT_SUBNET'):
    try:
        # Use faster gateway lookup by default when `netifaces` is available.
        # This is more permissive, and may not work in Termux.
        from moon.gateways import Gateways as Interfaces
    except ImportError:
        pass

# A zone section before its hosts become nodes: name, hosts with their aliases, and subnets.
type Stub = tuple[str, list[list[str]], tuple[IPv4Network, ...]]


@functools.cache
def get_timezone() -> int:
    return time.localtime().tm_gmtoff


@functools.cache
def get_interfaces() -> Interfaces:
    trace('>Interfaces')
    interfaces = Interfaces()
    trace('Interfaces')
    dbg(interfaces)
    return interfaces


def parse_arc(arc: str, zones: Container[str]) -> tuple[str | None, str, int]:
    # Returns the target zone, if written out, the host to jump through, and the cost.
    match arc.split(':'):
        case [via, to, cost] if cost.isdigit():
            return to, via, int(cost)
        case [spec, cost] if cost.isdigit():
            cost = int(cost)
        case [via, to]:
            return to, via, ARC_COST
        case [spec]:
            cost = ARC_COST
        case _:
            raise ValueError(f'malformed arc {arc!r}')

    # A zone is linked directly, and any other name is a host to jump through.
    return (spec, '', cost) if spec in zones else (None, spec, cost)


class Section(NamedTuple):
    zone: Zone
    timezone: float | None
    subnets: tuple[IPv4Network, ...]

    def applies(self) -> bool:
        # AND for timezone and subnet, so no constraint means always hits.
        if self.timezone is not None and get_timezone() != self.timezone * 3600:
            return False

        if self.subnets:
            interfaces = get_interfaces()

            # OR for all subnets.
            return any(interfaces.check_subnet(s) for s in self.subnets)

        return True


class ZoneConfig:
    def __init__(self, file: str, conf: Config | None = None) -> None:
        cfg = ConfigParser()
        if not cfg.read(file):
            raise FileNotFoundError(file)

        self._g = g = ZoneSet()

        self._sections: dict[str, Section] = {}
        sections = self._sections
        zone_stubs: list[Stub] = []
        smart_stubs: list[Stub] = []
        vis: set[str] = set()

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
            all_hosts: Iterator[str] | None = None
            curr_host: str | None = None
            for host, hostname in sorted(conf.hostnames()):
                if host in vis:
                    continue

                try:
                    ip = IPv4Address(hostname)
                except AddressValueError:
                    continue

                for _zone, hosts, subnets in smart_stubs:
                    for net in subnets:
                        if ip in net:
                            # Find a canonical host, now find all its aliases
                            # with the same prefix.
                            if all_hosts is None:
                                all_hosts = iter(
                                    h for h in sorted(h for h in conf.hosts()) if h not in vis
                                )

                            aliases = [host]

                            while curr_host != host:
                                curr_host = next(all_hosts, None)

                            while (curr_host := next(all_hosts, None)) and curr_host.startswith(
                                host
                            ):
                                vis.add(curr_host)
                                aliases.append(curr_host)

                            hosts.append(aliases)
                            break
                    else:
                        continue
                    break

        for sect, hosts, subnets in zone_stubs:
            tz = cfg.getfloat(sect, 'timezone', fallback=None)
            sections[sect] = Section(g.add(hosts), tz, subnets)

        for sect, section in sections.items():
            for arc in cfg.get(sect, 'arc', fallback='').split():
                to, via, cost = parse_arc(arc, sections)
                g.arc(section.zone, None if to is None else sections[to].zone, via, cost)

    def get_state(self) -> str:
        r: list[str] = []
        if any(s.timezone is not None for s in self._sections.values()):
            r.append('tz:' + str(get_timezone()))
        if any(s.subnets for s in self._sections.values()):
            r.append('if:' + str(get_interfaces()))
        return '|'.join(r)

    def route(self, host: str | None) -> ZoneSet:
        g = self._g
        for s in self._sections.values():
            if s.applies():
                g.set_src(s.zone)

        g.route()

        traced: tuple[str, Sequence[str]] | None = None
        if host:
            try:
                host_way = g.trace(host)
            except KeyError:
                pass
            else:
                if host_way is None:
                    dbg('No route to', host, must=True)
                else:
                    traced = (host, host_way)

        specs: list[tuple[str, str, int, bool]] = []
        zones = sorted(
            ((name, s.zone) for name, s in self._sections.items()),
            key=lambda t: t[1].dist,
            reverse=True,
        )
        for name, zone in zones:
            if (way := zone.path) is not None:
                label = '[' + ', '.join(way) + ']'
                if (must := zone.traced) and traced:
                    host, host_way = traced
                    if (
                        not g.contains(zone, host)
                        and len(way) < len(host_way)
                        and host_way[: len(way)] == way
                    ):
                        label = f'[{', '.join(way)}; {', '.join(host_way[len(way) :])}]'
                        traced = None

                z = f'{{{name}: {', '.join(h.name for h in zone.hosts)}}}'
                specs.append((label, z, zone.dist, must))

        for way, z, dist, must in reversed(specs):
            dbg(way, '->', z, f'({dist})', must=must)

        return g

    def resolve_direct(self, host: str) -> str | None:
        if host not in self._g:
            if (real := host.removeprefix('d.')) != host and real in self._g:
                return real

            # Direct for the unmanaged host.
            return host

    def zones(self) -> Iterable[str]:
        return self._sections.keys()
