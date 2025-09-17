import re
import sys
from fnmatch import fnmatch
from collections import defaultdict
from typing import Iterable, Sequence, TextIO, Callable

from .util import get_stem

SUB_REG = re.compile(r'\{\{(.+?)\}\}')

blk_no = 0


class Block:
    def __init__(self, header: str = '', hosts: Sequence[str] = (), ext: bool = False):
        global blk_no
        self.header = header
        self.hosts = hosts
        self.lines = []
        self.ext = ext
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
    def trimmed(self) -> Iterable['Line']:
        for line in self.lines:
            if isinstance(line, Line):
                yield line
            elif l := get_stem(line):
                yield Line(l, self)

    def __bool__(self):
        return bool(self.lines)

    def __str__(self) -> str:
        hosts = ' '.join(self.hosts)
        lines = ' '.join(s.strip() for s in self.lines)
        flag = '-' if self.ext else ''
        return f'Block({flag}{self.no}: {hosts} | {lines})'

    __repr__ = __str__


class Line(str):
    blk: Block

    def __new__(cls, value: str, blk: Block):
        obj = str.__new__(cls, value)
        obj.blk = blk
        return obj


class Config:
    def __init__(self, fp: TextIO) -> None:
        self._host_map: defaultdict[str, list[Block]] = defaultdict(list)
        self._wildcards: list[Block] = []
        self._blks: list[Block] = []
        self._ext_blks: list[Block] = []
        self._query_opts = set()
        blk = Block()

        def flush(new_blk):
            nonlocal blk
            self._push_blk(blk)
            blk = new_blk

        for line in fp:
            line = line.rstrip()
            stem = line.lstrip()
            lower = stem.lower()
            if lower.startswith('host '):
                flush(Block(line, line[5:].split()))
            elif lower.startswith('match '):
                flush(Block(line))
            elif stem:
                blk.push(line)
        flush(None)

    def _push_blk(self, blk: Block, ext: bool = False) -> None:
        blks = self._ext_blks if ext else self._blks
        blks.append(blk)
        for host in blk.hosts:
            has_wildcards = False
            if host[0] != '!':
                if '*' in host:
                    if not has_wildcards:
                        self._wildcards.append(blk)
                        has_wildcards = True
                else:
                    self._host_map[host].append(blk)

    def print(self, file: TextIO = sys.stdout) -> None:
        for blks in (self._ext_blks, self._blks):
            for blk in blks:
                print(blk.header, file=file)
                for line in blk.lines:
                    if blk.ext:
                        file.write('  ')
                    if isinstance(line, Line) and (header := line.blk.header.strip()):
                        print(line + '  # ' + header, file=file)
                    else:
                        print(line, file=file)
                print(file=file)

    def sub(self, repl: Callable[[str], str]) -> dict[str, str]:
        res = {}
        keys = []

        def _repl(m: re.Match) -> str:
            key = m[1].strip()
            keys.append(key)
            val = repl(key)
            res[key] = get_stem(val)
            return val

        def _trans(line: str) -> str:
            r = SUB_REG.sub(_repl, line)
            if keys:
                r += ' # ' + '; '.join(keys)
                keys.clear()
            return r

        for blk in self._blks:
            blk.lines = [_trans(line) for line in blk.lines]

        return res

    # Attach `name` as an alias of `host`.
    def attach(self, name: str, host: str) -> None:
        if name != host:
            lines = [f'# Attached to {host}', *self._query(host)]
            if 'hostname' not in self._query_opts:
                lines.append(f'Hostname {host}')
            self.add_host((name,), lines)

    def add_host(self, hosts: Sequence[str], lines: Sequence[str]) -> Block:
        blk = Block('Host ' + ' '.join(hosts), hosts, ext=True)
        for line in lines:
            blk.push(line)
        self._push_blk(blk, ext=True)
        return blk

    def _query(self, host: str) -> Iterable[Line]:
        # We assume there is never 'Host foo !f*o'.
        blks = set(self._host_map.get(host, ()))

        for blk in self._wildcards:
            if blk not in blks and blk.test(host):
                blks.add(blk)

        # Sort and unique. Extended blocks prioritized.
        blks = sorted(blks, key=lambda blk: (not blk.ext, blk.no))

        vis = self._query_opts
        vis.clear()
        for blk in blks:
            for line in blk.trimmed():
                # SSH takes the first occurrence of an option.
                opt = line.split(maxsplit=1)[0].rstrip('=').lower()
                if opt not in vis:
                    vis.add(opt)
                    yield line

    def query(self, host: str) -> tuple[Line, ...]:
        # Original blocks prioritized eventually.
        return tuple(
            sorted(self._query(host), key=lambda line: (line.blk.ext, line.blk.no))
        )

    def hosts(self) -> Iterable[str]:
        return self._host_map.keys()
