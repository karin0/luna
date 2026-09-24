import functools
import re
import shlex
import sys

from collections import defaultdict
from fnmatch import fnmatch
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

# ssh_config(5): a keyword is separated from its values by whitespace, or by
# optional whitespace around exactly one '='.
SEP_REG = re.compile(r'^(\s*[^\s=]+)\s*=\s*')


class Directive:
    def __init__(self, line: str):
        parts = shlex.split(SEP_REG.sub(r'\1 ', line, count=1), comments=True)
        self._opt = parts[0] if parts else ''
        self.values = tuple(parts[1:])

    @classmethod
    @functools.cache
    def parse(cls, line: str) -> Directive:
        return cls(line)

    @property
    def opt(self) -> str:
        return self._opt.lower()

    def __str__(self) -> str:
        # Remove comments, leading and trailing spaces, and unnecessary
        # quotes.
        return self._opt + ' ' + shlex.join(self.values)

    def __bool__(self) -> bool:
        return bool(self.opt)

    def __hash__(self) -> int:
        return hash((self.opt, self.values))

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Directive) and self.opt == other.opt and self.values == other.values
        )


blk_no = 0


class Block:
    def __init__(
        self, header: str = '', hosts: Sequence[str] = (), ext: bool = False, comment: str = ''
    ):
        global blk_no
        self.header = header
        self.hosts = list(hosts)
        self.lines: list[str] = []
        self.ext = ext
        self.comment = comment
        self.no = blk_no
        blk_no += 1

    def push(self, line: str):
        self.lines.append(line)

    def test(self, host: str) -> bool:
        hit = False
        for pattern in self.hosts:
            if pattern[0] == '!':
                if fnmatch(host, pattern[1:]):
                    return False
            elif fnmatch(host, pattern):
                hit = True

        return hit

    # Source input block for the lines are tracked.
    def trimmed(self) -> Iterable[Line]:
        for line in self.lines:
            if isinstance(line, Line):
                yield line
            elif d := Directive.parse(line):
                yield Line(str(d), self, d)

    def __bool__(self) -> bool:
        return bool(self.lines)

    def __str__(self) -> str:
        hosts = ' '.join(self.hosts)
        lines = ' '.join(s.strip() for s in self.lines)
        flag = '-' if self.ext else ''
        return f'Block({flag}{self.no}: {hosts} | {lines})'

    __repr__ = __str__

    def print(self, file: TextIO, *, annotate: bool = True) -> None:
        if annotate and (comment := ' '.join(self.comment.split())):
            file.write(self.header)
            file.write('  # ')
            print(comment, file=file)
        else:
            print(self.header, file=file)
        last_ref: Block | None = None
        for line in self.lines:
            if self.ext:
                file.write('  ')
            if isinstance(line, Line):
                if annotate and last_ref is not line.blk:
                    last_ref = line.blk
                    if header := line.blk.header.strip():
                        line += '  # ' + header
            else:
                last_ref = None
            print(line, file=file)
        print(file=file)


class Line(str):
    __slots__ = ('blk', 'dir')

    blk: Block
    dir: Directive

    def __new__(cls, value: str, blk: Block, dir: Directive):
        obj = str.__new__(cls, value)
        obj.blk = blk
        obj.dir = dir
        return obj


# This aims to parse most `Host` blocks, but dynamic options applied by `Match`
# and `Include` will not affect the generated (attached) options.
#
# Parsing and evaluating them like `ssh -G` could be costly with side effects.
#
# For complex configurations, please consider using the wrapper mode.
class Config:
    def __init__(self, fp: TextIO | None = None) -> None:
        self._host_map: defaultdict[str, list[Block]] = defaultdict(list)
        self._wildcards: list[Block] = []
        self._blks: list[Block] = []
        self._ext_blks: list[Block] = []
        self._ext_cache: dict[tuple[str, ...], Block] = {}

        if fp:
            self.load(fp)

    def load(self, fp: TextIO) -> None:
        default_blk = blk = Block(hosts=('*',))

        def flush(new_blk: Block) -> None:
            nonlocal blk
            self._push_blk(blk)
            blk = new_blk

        for line in fp:
            line = line.rstrip()
            d = Directive.parse(line)
            if d.opt == 'host':
                flush(Block(line, d.values))
            elif d.opt == 'match':
                flush(Block(line))
            elif line.lstrip():
                blk.push(line)
        self._push_blk(blk)

        if default_blk:
            default_blk.header = 'Host *  # Default'

    def _push_blk(self, blk: Block, ext: bool = False) -> None:
        blks = self._ext_blks if ext else self._blks
        blks.append(blk)
        has_wildcards = False
        for host in blk.hosts:
            if host[0] != '!':
                # ssh_config(5) PATTERNS: wildcards are '*' and '?'.
                if '*' in host or '?' in host:
                    if not has_wildcards:
                        self._wildcards.append(blk)
                        has_wildcards = True
                else:
                    self._host_map[host].append(blk)

    def print(
        self, file: TextIO = sys.stdout, separator: str | None = None, *, annotate: bool = True
    ) -> None:
        for blk in self._ext_blks:
            blk.print(file, annotate=annotate)

        if separator is not None and self._ext_blks and self._blks:
            print(separator, file=file)

        for blk in self._blks:
            blk.print(file, annotate=annotate)

    # Attach `name` as an alias of `host`.
    def attach(self, name: str, host: str) -> None:
        if name != host:
            old = {l.dir for l in self._query(name)}
            src = tuple(self._query(host))
            lines: list[str] = [l for l in src if l.dir not in old]
            if all(l.dir.opt != 'hostname' for l in src):
                lines.append(f'Hostname {host}')
            self.add_host((name,), lines, comment=f'inherits from {host}')

    # For the cache semantics, `hosts` should not contain wildcards.
    def add_host(self, hosts: Sequence[str], lines: Sequence[str], comment: str = '') -> Block:
        key = tuple(lines)
        if blk := self._ext_cache.get(key):
            if comment:
                if blk.comment and blk.comment != comment:
                    blk.comment += '; ' + comment
                else:
                    blk.comment = comment

            old_hosts = set(blk.hosts)
            if hosts := tuple(h for h in hosts if h not in old_hosts):
                blk.header += ' ' + ' '.join(hosts)
                blk.hosts.extend(hosts)
                for host in hosts:
                    if old := self._host_map.get(host):
                        old.append(blk)
                    else:
                        self._host_map[host] = [blk]
        else:
            header = 'Host ' + ' '.join(hosts)
            blk = Block(header, hosts, ext=True, comment=comment)
            for line in lines:
                blk.push(line)
            self._push_blk(blk, ext=True)
            self._ext_cache[key] = blk

        return blk

    def _query(self, host: str) -> Iterable[Line]:
        # We assume there is never 'Host foo !f*o'.
        blks = set(self._host_map.get(host, ()))

        for blk in self._wildcards:
            if blk not in blks and blk.test(host):
                blks.add(blk)

        vis: set[str] = set()

        # Sort and unique. Extended blocks prioritized.
        for blk in sorted(blks, key=lambda blk: (not blk.ext, blk.no)):
            for line in blk.trimmed():
                # SSH takes the first occurrence of an option.
                if (opt := line.dir.opt) in ('identityfile', 'certificatefile'):
                    # ssh_config(5): Multiple IdentityFile directives will add
                    # to the list of identities tried (this behaviour differs
                    # from that of other configuration directives).
                    yield line
                elif opt not in vis:
                    vis.add(opt)
                    yield line

    def query(self, host: str) -> tuple[Line, ...]:
        # Original blocks prioritized eventually.
        return tuple(sorted(self._query(host), key=lambda line: (line.blk.ext, line.blk.no)))

    def hosts(self) -> Iterable[str]:
        return self._host_map.keys()

    def hostnames(self) -> Iterable[tuple[str, str]]:
        for host, blks in self._host_map.items():
            for blk in blks:
                for line in blk.trimmed():
                    d = line.dir
                    if d.opt == 'hostname' and d.values:
                        yield host, d.values[0]
                        break
                else:
                    continue
                break

    # `unlisted` hosts get `Match originalhost` blocks, which ssh matches like
    # `Host` but which are no connection targets for clients that list them.
    def select(self, hosts: Iterable[str], unlisted: Iterable[str] = ()) -> Config:
        cfg = Config(None)
        for host in hosts:
            cfg.add_host((host,), self.query(host))
        for host in unlisted:
            blk = Block(f'Match originalhost {host}', ext=True)
            for line in self.query(host):
                blk.push(line)
            cfg._push_blk(blk, ext=True)
        return cfg
