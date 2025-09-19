import heapq
from typing import Iterable, Sequence, NamedTuple
from enum import Enum
from .syn import Config

INF = 0x3F3F3F3F


class Arc(NamedTuple):
    to: 'Node'
    cost: int
    alias: bool


class Node:
    def __init__(self, name: str, is_host: bool) -> None:
        self.name = name
        self.is_host = is_host
        self.adj: list[Arc] = []
        self.dist = INF
        self.prev: tuple[Node, Arc] | None = None
        self.vis = False
        self._path = None

    def arc(self, to: 'Node', cost: int, *, alias: bool = False) -> None:
        self.adj.append(Arc(to, cost, alias))

    def _find(self) -> Sequence[str] | None:
        if prev := self.prev:
            prev, e = prev
            r = prev.find()

            if self.is_host and not e.alias:
                # `prev` is not an alias of `self`.
                return (*r, self.name)

            return r

        return (self.name,) if self.is_host else ()

    def find(self) -> Sequence[str] | None:
        if self.dist >= INF:
            return None

        if self._path is None:
            self._path = self._find()

        return self._path

    def __str__(self) -> str:
        return '<' + self.kind.name[0] + ':' + self.name + '>'

    __repr__ = __str__


class Zone:
    def __init__(self, root: Node, hosts: Sequence[Node]) -> None:
        self.root = root
        self.hosts = frozenset(hosts)
        self.priv = None

    def __str__(self) -> str:
        return f'{{{self.root.name}: {', '.join(h.name for h in self.hosts)}}}'

    __repr__ = __str__


class Dijkstra(NamedTuple):
    dist: int
    u: 'Node'

    def __lt__(self, v: 'Dijkstra') -> bool:
        return self.dist < v.dist


class ZoneSet:
    def __init__(self) -> None:
        self._zones: list[Zone] = []
        self._nodes: dict[str, Node] = {}
        self._canonical: dict[str, Node] = {}
        self._q: list[Dijkstra] = []

    def _add(self, name: str, is_host: bool = True) -> Node:
        assert name not in self._nodes
        self._nodes[name] = u = Node(name, is_host)
        return u

    def add(self, name: str, hosts: Sequence[Sequence[str]]) -> Zone:
        nodes: list[Node] = []
        for aliases in hosts:
            canonical = self._add(aliases[0])
            nodes.append(canonical)
            for alias in aliases[1:]:
                # We take the `alias` as a shortcut to `canonical` from another
                # zone, which means it could be inaccessible even from the
                # canonical host itself or its own zone.
                #
                # The creation of `alias` nodes are deferred until `arc()`.
                self._canonical[alias] = canonical

        root = self._add(name, False)
        for u in nodes:
            root.arc(u, 10)
            u.arc(root, 0)

        zone = Zone(root, nodes)
        self._zones.append(zone)

        return zone

    def set_src(self, zone: Zone) -> None:
        if (u := zone.root).dist != 0:
            u.dist = 0
            heapq.heappush(self._q, Dijkstra(0, u))

    def arc(self, frm: Zone, to: Zone | None, via: str = '', cost: int = 20) -> None:
        if via:
            try:
                # A host?
                u = self._nodes[via]
            except KeyError:
                try:
                    # An alias?
                    host = self._canonical[via]
                    u = self._add(via)
                    u.arc(host, 0, alias=True)
                except KeyError:
                    # An arbitrary hostname.
                    if not to:
                        raise ValueError(f'unknown {via=} without target zone')
                    host = to.root
                    u = self._add(via)
                    u.arc(host, 0)
            else:
                if not u.is_host:
                    raise ValueError(f'{via=} is a zone')

            frm.root.arc(u, cost)
        else:
            frm.root.arc(to.root, cost)

    def route(self):
        q = self._q
        while q:
            u = heapq.heappop(q).u
            if not u.vis:
                u.vis = True
                for e in u.adj:
                    v = e.to
                    t = u.dist + e.cost
                    if v.dist > t:
                        v.dist = t
                        v.prev = (u, e)
                        heapq.heappush(q, Dijkstra(t, v))

    def trace(self, name: str) -> Sequence[str] | None:
        return self._nodes[name].find()

    # ssh <name> -> ssh <final_hop> -J <jumps>
    # <final_hop> might be an alias of <name> if <name> is a canonical host.
    # Only used in wrapper mode, where we can modify the connected destination.
    def resolve(self, name: str) -> tuple[str, str] | None:
        if way := self._nodes[name].find():
            return way[-1], ','.join(way[:-1])

    # In generator mode, we inject ProxyJump options to every hop and "attach"
    # all connecting options of the final hop to the destination host.
    def inject(self, conf: Config):
        for u in self._nodes.values():
            if u.is_host and (way := u.find()):
                target = u.name
                final_hop = way[-1]

                # The final hop does not need ProxyJump to itself, we connect
                # to it as if connecting to the target.
                conf.attach(target, final_hop)

                try:
                    last_jump = way[-2]
                except IndexError:
                    pass
                else:
                    # TODO: respect the existing ProxyJump options for dest
                    conf.add_host((target,), (f'# {way}', f'ProxyJump {last_jump}'))

    def iter_zones(self) -> Iterable[tuple[Zone, int, Sequence[str] | None]]:
        for zone in sorted(self._zones, key=lambda z: z.root.dist):
            yield zone, zone.root.dist, zone.root.find()

    def contains(self, zone: Zone, name: str) -> bool:
        name = self._canonical.get(name, name)
        try:
            u = self._nodes[name]
        except KeyError:
            return False

        return u in zone.hosts

    def __contains__(self, name: str) -> bool:
        return name in self._nodes
