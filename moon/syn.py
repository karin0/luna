import re
import sys
import shlex
from fnmatch import fnmatch
from collections import defaultdict
from typing import Iterable, Sequence, TextIO, Callable

SUB_REG = r'\{\{(.+?)\}\}'


class Directive:
    def __init__(self, line: str):
        self.parts = p = shlex.split(line, comments=True)
        self.opt = p[0].lower().split('=', maxsplit=1)[0] if p else ''

    def __str__(self) -> str:
        # Remove comments, leading and trailing spaces, and unnecessary
        # quotes.
        return shlex.join(self.parts)

    def __bool__(self) -> bool:
        return bool(self.parts)


blk_no = 0


class Block:
    def __init__(self, header: str = '', hosts: Sequence[str] = (), ext: bool = False):
        global blk_no
        self.header = header
        self.hosts = hosts
        self.lines: list[str] = []
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
            elif d := Directive(line):
                yield Line(str(d), self, d)

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
    def __init__(self, fp: TextIO) -> None:
        self._host_map: defaultdict[str, list[Block]] = defaultdict(list)
        self._wildcards: list[Block] = []
        self._blks: list[Block] = []
        self._ext_blks: list[Block] = []
        self._query_opts = set()
        default_blk = blk = Block(hosts=('*',))

        def flush(new_blk):
            nonlocal blk
            self._push_blk(blk)
            blk = new_blk

        for line in fp:
            line = line.rstrip()
            d = Directive(line)
            if d.opt == 'host':
                flush(Block(line, d.parts[1:]))
            elif d.opt == 'match':
                flush(Block(line))
            elif line.lstrip():
                blk.push(line)
        flush(None)

        if default_blk:
            default_blk.header = 'Host *  # Default'

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

    def _print(self, blks: Iterable[Block], file: TextIO) -> None:
        for blk in blks:
            print(blk.header, file=file)
            for line in blk.lines:
                if blk.ext:
                    file.write('  ')
                if isinstance(line, Line) and (header := line.blk.header.strip()):
                    line += '  # ' + header
                print(line, file=file)
            print(file=file)

    def print(self, file: TextIO = sys.stdout, separator=None) -> None:
        self._print(self._ext_blks, file)
        if separator:
            print(separator, file=file)
        self._print(self._blks, file)

    def sub(self, repl: Callable[[str], str]) -> dict[str, str]:
        res = {}
        keys = []

        def _repl(m: re.Match) -> str:
            key = m[1].strip()
            keys.append(key)
            val = repl(key)
            res[key] = val.split('#', maxsplit=1)[0].strip()
            return val

        def _trans(line: str) -> str:
            r = re.sub(SUB_REG, _repl, line)
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
        return tuple(
            sorted(self._query(host), key=lambda line: (line.blk.ext, line.blk.no))
        )

    def hosts(self) -> Iterable[str]:
        return self._host_map.keys()

    def hostnames(self) -> Iterable[tuple[str, str]]:
        for host, blks in self._host_map.items():
            for blk in blks:
                for line in blk.trimmed():
                    d = line.dir
                    if d.opt == 'hostname' and len(d.parts) > 1:
                        yield host, d.parts[1]
                        break
                else:
                    continue
                break
