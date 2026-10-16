"""Pattern-match exhaustiveness and redundancy checking.

Implements the "usefulness" algorithm from Luc Maranget, *Warnings for pattern
matching* (JFP 2007). Patterns are normalised to two shapes:

    WILD                                  matches anything
    ("c", key, [sub-patterns], family)    a constructor application

`family` tells us the full set of constructors for the scrutinee's type:
    "bool", "unit", "list", ("adt", ctor_list) or "lit" (infinitely many, e.g. Int).
"""

WILD = ("_",)


def con(key, args, family):
    return ("c", key, list(args), family)


def all_ctors(family):
    """Every (key, arity) of a family, or None when the family is infinite."""
    if family == "bool":
        return [(True, 0), (False, 0)]
    if family == "unit":
        return [(None, 0)]
    if family == "list":
        return [("[]", 0), ("::", 2)]
    if isinstance(family, tuple) and family[0] == "adt":
        return list(family[1])
    return None


def _specialize(rows, key, arity):
    out = []
    for row in rows:
        head = row[0]
        if head is WILD:
            out.append([WILD] * arity + row[1:])
        elif head[1] == key:
            out.append(list(head[2]) + row[1:])
    return out


def _default(rows):
    return [row[1:] for row in rows if row[0] is WILD]


def _column_heads(rows):
    heads, family = {}, None
    for row in rows:
        head = row[0]
        if head is not WILD:
            heads[head[1]] = len(head[2])
            family = head[3]
    return heads, family


def useful(rows, vec):
    """Is there a value matched by `vec` that no row in `rows` matches?"""
    if not vec:
        return not rows
    head = vec[0]
    if head is not WILD:
        return useful(_specialize(rows, head[1], len(head[2])), list(head[2]) + vec[1:])
    heads, family = _column_heads(rows)
    complete = all_ctors(family) if family is not None else None
    if complete is not None and all(k in heads for k, _ in complete):
        return any(useful(_specialize(rows, k, a), [WILD] * a + vec[1:]) for k, a in complete)
    return useful(_default(rows), vec[1:])


def witness(rows, n):
    """Return n patterns describing a value no row matches, or None if rows are exhaustive."""
    if n == 0:
        return None if rows else []
    heads, family = _column_heads(rows)
    complete = all_ctors(family) if family is not None else None
    if complete is not None and all(k in heads for k, _ in complete):
        for key, arity in complete:
            w = witness(_specialize(rows, key, arity), arity + n - 1)
            if w is not None:
                return [con(key, w[:arity], family)] + w[arity:]
        return None
    rest = witness(_default(rows), n - 1)
    if rest is None:
        return None
    if complete is None or not heads:
        return [WILD] + rest
    for key, arity in complete:
        if key not in heads:
            return [con(key, [WILD] * arity, family)] + rest


def show(p, nested=False):
    if p is WILD:
        return "_"
    _, key, args, family = p
    if family == "list":
        if key == "[]":
            return "[]"
        text = f"{show(args[0], True)} :: {show(args[1])}"
        return f"({text})" if nested else text
    if family == "bool":
        return "true" if key else "false"
    if family == "unit":
        return "()"
    if family == "lit":
        return repr(key[1]).replace("'", '"')
    return key + (f"({', '.join(show(a) for a in args)})" if args else "")
