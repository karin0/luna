import heapq
import functools
from typing import Iterable, Sequence, NamedTuple
from .syn import Config

INF = 0x3F3F3F3F


class Arc(NamedTuple):
    to: 'Node'
    cost: int
    alias: bool


class Node:
    def __init__(self, name: str, zone: 'Zone | None') -> None:
        self.name = name
        self.zone = zone
        self.adj: list[Arc] = []
        self.dist = INF
        self.prev: tuple[Node, Arc] | None = None
        self.vis = False
        self.traced = False

    def arc(self, to: 'Node', cost: int, *, alias: bool = False) -> None:
        self.adj.append(Arc(to, cost, alias))

    @functools.cache
    def _find(self) -> Sequence[str] | None:
        if prev := self.prev:
            prev, e = prev
            r = prev._find()

            if self.name and not e.alias:
                # `prev` is not an alias of `self`.
                return (*r, self.name)

            return r

        return (self.name,) if self.name else ()

    def find(self) -> Sequence[str] | None:
        return self._find() if self.dist < INF else None

    def __str__(self) -> str:
        return '<' + self.name + '>'

    __repr__ = __str__


class Zone:
    def __init__(self, root: Node, hosts: Sequence[Node]) -> None:
        self.root = root
        self.hosts = hosts

    @property
    def dist(self) -> int:
        return self.root.dist

    @property
    def path(self) -> Sequence[str] | None:
        return self.root.find()

    @property
    def traced(self) -> bool:
        return self.root.traced


class Dijkstra(NamedTuple):
    dist: int
    u: 'Node'

    def __lt__(self, v: 'Dijkstra') -> bool:
        return self.dist < v.dist


class ZoneSet:
    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._canonical: dict[str, Node] = {}
        self._q: list[Dijkstra] = []

    def _add(self, name: str, zone: Zone) -> Node:
        u = Node(name, zone)
        if name:
            assert name not in self._nodes
            self._nodes[name] = u

        return u

    def add(self, hosts: Sequence[Sequence[str]]) -> Zone:
        root = self._add('', None)
        nodes: list[Node] = []
        zone = Zone(root, nodes)
        for aliases in hosts:
            canonical = self._add(aliases[0], zone)
            nodes.append(canonical)
            for alias in aliases[1:]:
                # We take the `alias` as a shortcut to `canonical` from another
                # zone, which means it could be inaccessible even from the
                # canonical host itself or its own zone.
                #
                # The creation of `alias` nodes are deferred until `arc()`.
                self._canonical[alias] = canonical

        # Zone roots are invisible on the paths.
        for u in nodes:
            root.arc(u, 10)
            u.arc(root, 0, alias=True)

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
                    u = self._add(via, host.zone)
                    u.arc(host, 0, alias=True)
                except KeyError:
                    # An arbitrary hostname.
                    if not to:
                        raise ValueError(f'unknown {via=} without target zone')
                    host = to.root
                    u = self._add(via, None)
                    u.arc(host, 0)

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
        u = self._nodes[name]
        if (path := u.find()) is None:
            return None

        u.traced = True
        while t := u.prev:
            u, _ = t
            u.traced = True

        return path

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
            if (target := u.name) and (way := u.find()):
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
                    way = '[' + ', '.join(way[:-1]) + ']'
                    conf.add_host((target,), (f'ProxyJump {last_jump}',), comment=way)

    def contains(self, zone: Zone, name: str) -> bool:
        name = self._canonical.get(name, name)
        try:
            u = self._nodes[name]
        except KeyError:
            return False
        return u.zone is zone

    def __contains__(self, name: str) -> bool:
        return name in self._nodes

    def names(self) -> Iterable[str]:
        yield from self._nodes.keys()
        yield from (k for k in self._canonical.keys() if k not in self._nodes)

    def hosts(self) -> Iterable[str]:
        return (u.name for u in self._nodes.values() if u.name not in self._canonical)
