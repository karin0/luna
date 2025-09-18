import os
import datetime
import importlib.util

from configparser import ConfigParser

from moon.intf import Interfaces
from moon.route import Zone, ZoneSet
from moon.util import trace

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


def in_zone(cfg: ConfigParser, zone: str) -> bool:
    # AND for timezone and subnet, so no constraint means always hits.
    if tz := cfg.get(zone, 'timezone', fallback=None):
        if not check_timezone(float(tz)):
            return False

    if subnets := cfg.get(zone, 'subnet', fallback='').split():
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
    def __init__(self, file) -> None:
        self._cfg = cfg = ConfigParser()
        if not cfg.read(file):
            raise FileNotFoundError(file)

        self._hooks = hooks = []
        self._g = g = ZoneSet()

        self.zones: dict[str, Zone] = {}
        zones = self.zones

        for sect in cfg.sections():
            hosts = cfg.get(sect, 'host', fallback='').split()
            hosts = tuple(spec.split(':') for spec in hosts)
            zones[sect] = zone = g.add(sect, hosts)

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

    def route(self):
        g = self._g
        for sect, zone in self.zones.items():
            if in_zone(self._cfg, sect):
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
