"""Standard library. Each builtin is `impl(interp, args, call_node)`."""

import time

from .errors import MiniRuntimeError
from .interpreter import Builtin, equal, is_number, show, truthy, type_name


def _need(cond, msg):
    if not cond:
        raise MiniRuntimeError(msg)


def _seq(v, fname):
    _need(isinstance(v, (list, range, str, dict)), f"{fname}() expects a collection, got {type_name(v)}")
    return list(v.keys()) if isinstance(v, dict) else v


def _print(it, args, node):
    it.output(" ".join(show(a) for a in args))


def _len(it, args, node):
    (v,) = args
    _need(isinstance(v, (list, str, dict, range)), f"len() of {type_name(v)}")
    return len(v)


def _push(it, args, node):
    arr, value = args
    _need(isinstance(arr, list), f"push() expects an array, got {type_name(arr)}")
    arr.append(value)
    return arr


def _pop(it, args, node):
    (arr,) = args
    _need(isinstance(arr, list), f"pop() expects an array, got {type_name(arr)}")
    _need(len(arr) > 0, "pop() from empty array")
    return arr.pop()


def _str(it, args, node):
    return show(args[0])


def _int(it, args, node):
    (v,) = args
    try:
        return int(v)
    except (TypeError, ValueError):
        raise MiniRuntimeError(f"cannot convert {show(v, True)} to int")


def _map(it, args, node):
    xs, f = args
    return [it.call(f, [x], node) for x in _seq(xs, "map")]


def _filter(it, args, node):
    xs, f = args
    return [x for x in _seq(xs, "filter") if truthy(it.call(f, [x], node))]


def _reduce(it, args, node):
    xs, f, acc = args
    for x in _seq(xs, "reduce"):
        acc = it.call(f, [acc, x], node)
    return acc


def _sort(it, args, node):
    """sort(xs) or sort(xs, key_fn). Stable merge sort so key fns run through the interpreter."""
    xs = list(_seq(args[0], "sort"))
    key = (lambda x: it.call(args[1], [x], node)) if len(args) > 1 else (lambda x: x)
    keyed = [(key(x), x) for x in xs]

    def less(a, b):
        if is_number(a) and is_number(b) or isinstance(a, str) and isinstance(b, str):
            return a < b
        raise MiniRuntimeError(f"cannot compare {type_name(a)} and {type_name(b)} in sort()")

    def merge_sort(items):
        if len(items) <= 1:
            return items
        mid = len(items) // 2
        left, right = merge_sort(items[:mid]), merge_sort(items[mid:])
        out, i, j = [], 0, 0
        while i < len(left) and j < len(right):
            if less(right[j][0], left[i][0]):
                out.append(right[j]); j += 1
            else:
                out.append(left[i]); i += 1
        return out + left[i:] + right[j:]

    return [x for _, x in merge_sort(keyed)]


def _keys(it, args, node):
    (m,) = args
    _need(isinstance(m, dict), f"keys() expects a map, got {type_name(m)}")
    return list(m.keys())


def _has(it, args, node):
    coll, key = args
    if isinstance(coll, dict):
        return key in coll
    if isinstance(coll, str):
        _need(isinstance(key, str), "has() on a string needs a string")
        return key in coll
    _need(isinstance(coll, (list, range)), f"has() on {type_name(coll)}")
    return any(equal(x, key) for x in coll)


def _join(it, args, node):
    xs, sep = args
    _need(isinstance(sep, str), "join() separator must be a string")
    return sep.join(show(x) for x in _seq(xs, "join"))


def _split(it, args, node):
    s, sep = args
    _need(isinstance(s, str) and isinstance(sep, str), "split() expects two strings")
    return s.split(sep) if sep else list(s)


def _range(it, args, node):
    _need(all(isinstance(a, int) and not isinstance(a, bool) for a in args), "range() expects integers")
    return list(range(*args))


def _assert(it, args, node):
    if not truthy(args[0]):
        raise MiniRuntimeError("assertion failed" + (f": {show(args[1])}" if len(args) > 1 else ""))
    return None


def _minmax(pick):
    def impl(it, args, node):
        xs = _seq(args[0], pick.__name__) if len(args) == 1 else args
        _need(len(xs) > 0, f"{pick.__name__}() of empty collection")
        _need(all(is_number(x) for x in xs), f"{pick.__name__}() expects numbers")
        return pick(xs)
    return impl


def _abs(it, args, node):
    _need(is_number(args[0]), "abs() expects a number")
    return abs(args[0])


def _clock(it, args, node):
    return time.perf_counter()


def _type(it, args, node):
    return type_name(args[0])


BUILTINS = [
    # name, impl, min_args, max_args (-1 = variadic)
    ("print", _print, 0, -1),
    ("len", _len, 1),
    ("push", _push, 2),
    ("pop", _pop, 1),
    ("str", _str, 1),
    ("int", _int, 1),
    ("type", _type, 1),
    ("map", _map, 2),
    ("filter", _filter, 2),
    ("reduce", _reduce, 3),
    ("sort", _sort, 1, 2),
    ("keys", _keys, 1),
    ("has", _has, 2),
    ("join", _join, 2),
    ("split", _split, 2),
    ("range", _range, 1, 3),
    ("assert", _assert, 1, 2),
    ("min", _minmax(min), 1, -1),
    ("max", _minmax(max), 1, -1),
    ("abs", _abs, 1),
    ("clock", _clock, 0),
]


def install(interp):
    for name, impl, *arity in BUILTINS:
        interp.globals.define(name, Builtin(name, impl, *arity))
