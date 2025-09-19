import os
import datetime
import importlib.util

from configparser import ConfigParser
from ipaddress import AddressValueError, IPv4Address, IPv4Network

from moon.intf import Interfaces
from moon.route import Zone, ZoneSet
from moon.util import trace
from moon.syn import Config

if not os.environ.get('LUNA_STRICT_SUBNET'):
    try:
        # Use faster gateway lookup by default when `netifaces` is available.
        # This is more permissive, and may not work in Termux.
        from moon.intf import Gateways as Interfaces
    except ImportError:
        pass

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


def in_zone(cfg: ConfigParser, sect: str, zone: Zone) -> bool:
    # AND for timezone and subnet, so no constraint means always hits.
    if tz := cfg.get(sect, 'timezone', fallback=None):
        if not check_timezone(float(tz)):
            return False

    if subnets := zone.priv:
        global interfaces
        if not interfaces:
            trace('>Interfaces')
            interfaces = Interfaces()
            trace('Interfaces')

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

        self.zones: dict[str, Zone] = {}
        zones = self.zones
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
            zones[sect] = zone = g.add(sect, hosts)
            zone.priv = subnets

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

    def route(self):
        g = self._g
        for sect, zone in self.zones.items():
            if in_zone(self._cfg, sect, zone):
                g.set_src(zone)

        g.route()
        return g

    def run_hooks(self, name, *args, **kwargs):
        for h in self._hooks:
            if f := getattr(h, name, None):
                f(*args, **kwargs)

    def _has_host(self, name: str) -> bool:
        return name in self._g and name not in self.zones

    def resolve_direct_mode(self, host: str) -> str | None:
        if not self._has_host(host):
            if (real := host.removeprefix('d.')) != host and self._has_host(real):
                return real

            # Direct for the unmanaged host.
            return host
