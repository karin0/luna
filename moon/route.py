import heapq
from typing import Iterable, Sequence, NamedTuple
from enum import Enum
from .syn import Config

INF = 0x3F3F3F3F


class NodeKind(Enum):
    # Virtual root node representing a zone.
    ZONE = 1

    # Smart routed host in a zone.
    # This is necessary to distinguish from different paths to the same zone.
    HOST = 2

    # Intermediate jump host, not a canonical host in any zone.
    # Could be an alias of some host, or an arbitrary hostname.
    # This is necessary to inject options also for aliases.
    PROXY = 3


class Arc(NamedTuple):
    to: 'Node'
    cost: int


class Node:
    def __init__(self, name: str, kind: NodeKind) -> None:
        self.name = name
        self.kind = kind
        self.adj: list[Arc] = []
        self.dist = INF
        self.prev: Node | None = None
        self.vis = False
        self._path = None

    def arc(self, to: 'Node', cost: int) -> None:
        self.adj.append(Arc(to, cost))

    def find(self) -> Sequence[str] | None:
        if self.dist >= INF:
            return None

        if self._path is not None:
            return self._path

        if prev := self.prev:
            r = prev.find()
            if self.kind != NodeKind.ZONE and prev.kind != NodeKind.PROXY:
                # `prev` is not an alias of `self`.
                r += (self.name,)
        else:
            r = ()

        self._path = r
        return r

    def __str__(self) -> str:
        return '<' + self.kind.name[0] + ':' + self.name + '>'

    __repr__ = __str__


class Zone:
    def __init__(self, root: Node, hosts: tuple[Node]) -> None:
        self.root = root
        self.hosts = frozenset(hosts)

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
        self._src = src = self._add('_src', NodeKind.ZONE)
        src.dist = 0

    def _add(self, name: str, kind: NodeKind) -> Node:
        assert name not in self._nodes
        self._nodes[name] = u = Node(name, kind)
        return u

    def add(self, name: str, hosts: Sequence[Sequence[str]]) -> Zone:
        nodes: list[Node] = []
        for aliases in hosts:
            host = self._add(aliases[0], NodeKind.HOST)
            nodes.append(host)
            for alias in aliases[1:]:
                self._canonical[alias] = host

        root = self._add(name, NodeKind.ZONE)
        for u in nodes:
            root.arc(u, 10)
            u.arc(root, 0)

        zone = Zone(root, tuple(nodes))
        self._zones.append(zone)

        return zone

    def set_src(self, zone: Zone) -> None:
        self._src.arc(zone.root, 0)

    def arc(self, frm: Zone, to: Zone | None, via: str = '', cost: int = 20) -> None:
        if via:
            try:
                # via is an existing HOST or PROXY?
                u = self._nodes[via]
            except KeyError:
                # Create a new PROXY node for an alias or an arbitrary hostname.
                try:
                    host = self._canonical[via]
                except KeyError:
                    if not to:
                        raise ValueError(f'unknown {via=} without target zone')
                    host = to.root

                u = self._add(via, NodeKind.PROXY)
                u.arc(host, 0)
            else:
                if u.kind == NodeKind.ZONE:
                    raise ValueError(f'{via=} is a zone')

            frm.root.arc(u, cost)
        else:
            frm.root.arc(to.root, cost)

    def route(self):
        q = [Dijkstra(0, self._src)]
        while q:
            u = heapq.heappop(q).u
            if not u.vis:
                u.vis = True
                for e in u.adj:
                    v = e.to
                    t = u.dist + e.cost
                    if v.dist > t:
                        v.dist = t
                        v.prev = u
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
            if u.kind != NodeKind.ZONE and (way := u.find()):
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
