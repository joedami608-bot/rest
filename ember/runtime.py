"""Runtime values and native functions.

Value representation (the type checker guarantees these never get mixed up):
    Int -> int    Bool -> bool    String -> str    Unit -> None
    List -> nested tuples: () is [], (head, tail) is head :: tail
    user data types -> Data(tag, name, fields)
    functions -> Closure | Native | CtorFn
"""

import time

from .errors import RuntimeErr


class Code:
    __slots__ = ("name", "arity", "nlocals", "code", "consts", "lines", "nfree", "prelude")

    def __init__(self, name, arity, nlocals, code, consts, lines, nfree, prelude=False):
        self.name = name
        self.arity = arity
        self.nlocals = nlocals
        self.code = code
        self.consts = consts
        self.lines = lines  # (line, col) for every code position
        self.nfree = nfree
        self.prelude = prelude  # True for standard-library code (its lines refer to prelude.em)


class Cell:
    __slots__ = ("value",)

    def __init__(self, value=None):
        self.value = value


class Closure:
    __slots__ = ("code", "cells")

    def __init__(self, code, cells):
        self.code = code
        self.cells = cells


class Native:
    __slots__ = ("name", "fn")

    def __init__(self, name, fn):
        self.name = name
        self.fn = fn


class CtorFn:
    """A constructor used as a first-class function, e.g. `map(xs, Some)`."""
    __slots__ = ("tag", "name", "arity")

    def __init__(self, tag, name, arity):
        self.tag = tag
        self.name = name
        self.arity = arity


class Data:
    __slots__ = ("tag", "name", "fields")

    def __init__(self, tag, name, fields):
        self.tag = tag
        self.name = name
        self.fields = fields


def values_equal(a, b):
    """Structural equality without Python recursion over long lists."""
    stack = [(a, b)]
    while stack:
        a, b = stack.pop()
        if type(a) is tuple:
            while a and b:              # walk list spines iteratively
                stack.append((a[0], b[0]))
                a, b = a[1], b[1]
            if a or b:
                return False
        elif type(a) is Data:
            if a.tag != b.tag:
                return False
            stack.extend(zip(a.fields, b.fields))
        elif type(a) in (Closure, Native, CtorFn):
            if a is not b:
                return False
        elif a != b:
            return False
    return True


def show(v, nested=False):
    t = type(v)
    if v is None:
        return "()"
    if t is bool:
        return "true" if v else "false"
    if t is int:
        return str(v)
    if t is str:
        if not nested:
            return v
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    if t is tuple:
        items = []
        while v:
            items.append(show(v[0], True))
            v = v[1]
        return "[" + ", ".join(items) + "]"
    if t is Data:
        if not v.fields:
            return v.name
        return f"{v.name}({', '.join(show(f, True) for f in v.fields)})"
    if t is Closure:
        return f"<fn {v.code.name}>"
    if t is Native:
        return f"<native {v.name}>"
    if t is CtorFn:
        return f"<constructor {v.name}>"
    return repr(v)


def to_list(py_items):
    out = ()
    for x in reversed(py_items):
        out = (x, out)
    return out


def iterate(xs):
    while xs:
        yield xs[0]
        xs = xs[1]


def _reverse(xs):
    out = ()
    while xs:
        out = (xs[0], out)
        xs = xs[1]
    return out


def _length(xs):
    n = 0
    while xs:
        n += 1
        xs = xs[1]
    return n


def _substring(s, start, end):
    if not 0 <= start <= end <= len(s):
        raise RuntimeErr(f"substring({start}, {end}) out of range for a string of length {len(s)}")
    return s[start:end]


def _panic(msg):
    raise RuntimeErr(f"panic: {msg}")


def make_natives(output):
    def _print(v):
        output(show(v))
    return {
        "print": _print,
        "to_string": show,
        "panic": _panic,
        "str_len": len,
        "substring": _substring,
        "chars": lambda s: to_list(list(s)),
        "clock_ms": lambda: int(time.perf_counter() * 1000),
        "reverse": _reverse,
        "length": _length,
        "append": lambda xs, ys: to_list(list(iterate(xs)) + list(iterate(ys))),
        "sum": lambda xs: sum(iterate(xs)),
        "range": lambda lo, hi: to_list(list(range(lo, hi))),
        "join": lambda xs, sep: sep.join(iterate(xs)),
    }


# Names (and global slot order) of natives; must match types.builtin_schemes().
NATIVES = list(make_natives(print).keys())
