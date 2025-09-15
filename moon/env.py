from typing import Callable, Iterable

# We require all passes to be idempotent and commutative; the raised `Abort`
# is only a hint and shouldn't be relied on.
# This allows 'ctx[a] = ctx[b]', though it's unrecommended and avoided now.

Pass = Callable[[str, str], str]


class Abort(RuntimeError):
    def __init__(self, result: str) -> None:
        self.result = result
        super().__init__(result)


def _run_passes(k: str, v: str, passes: Iterable[Pass]):
    for p in passes:
        try:
            v = p(k, v)
        except Abort as e:
            return e.result, False
    return v, True


class Environment:
    def __init__(self, args: dict[str, str] | None = None) -> None:
        self.passes = []
        self.args = {k: (v, 0) for k, v in args.items()} if args else {}

    def run(self, k: str, v: str):
        return _run_passes(k, v, self.passes)[0]

    def _get(self, k, t):
        v, i = t
        if i is not None:
            v, cont = _run_passes(k, v, self.passes[i:])
            self.args[k] = (v, len(self.passes) if cont else None)
        return v

    def __getitem__(self, k):
        return self._get(k, self.args[k])

    def __setitem__(self, k, v):
        self.args[k] = (v, 0)

    def add_pass(self, f: Pass):
        self.passes.append(f)

    def __iter__(self):
        return iter(self.args)

    def items(self):
        for k, t in self.args.items():
            yield k, self._get(k, t)

    def __bool__(self):
        return bool(self.args)
