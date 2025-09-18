import os
import datetime
import configparser
import importlib.util

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


def in_zone(cfg, zone):
    if tz := cfg.get(zone, 'timezone', fallback=None):
        if not check_timezone(float(tz)):
            return False

    if subnets := cfg.get(zone, 'subnet', fallback='').split():
        global interfaces
        if not interfaces:
            trace('>Interfaces')
            interfaces = Interfaces()
            trace('Interfaces')

        for s in subnets:
            if not interfaces.check_subnet(s):
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
        if not cfg.read(file):
            raise FileNotFoundError(file)

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
