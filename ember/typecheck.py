"""Hindley-Milner type inference (Algorithm W with union-find and level-based generalisation).

Highlights:
  * let-polymorphism with the value restriction (`var`s are never generalised)
  * top-level functions are split into strongly connected components (Tarjan) so
    that mutually recursive groups are inferred together and everything else
    stays maximally polymorphic
  * optional annotations unify with the inferred type
  * algebraic data types, pattern matching, exhaustiveness and redundancy checks
"""

import itertools

from . import syntax as ast
from . import exhaustive as ex
from .errors import TypeErr, Warn

# ---------------------------------------------------------------- type representation

_ids = itertools.count()


class TVar:
    # `eq` marks an equality type variable (as in Standard ML): it was compared
    # with `==`, so it may never be instantiated to a function type.
    __slots__ = ("id", "ref", "level", "eq")

    def __init__(self, level, eq=False):
        self.id = next(_ids)
        self.ref = None
        self.level = level
        self.eq = eq


class TCon:
    __slots__ = ("name", "args")

    def __init__(self, name, args=()):
        self.name = name
        self.args = list(args)


class TFun:
    __slots__ = ("params", "ret")

    def __init__(self, params, ret):
        self.params = list(params)
        self.ret = ret


class Scheme:
    """∀ quantified. ty"""
    __slots__ = ("quantified", "ty")

    def __init__(self, quantified, ty):
        self.quantified = quantified
        self.ty = ty


INT, BOOL, STRING, UNIT = TCon("Int"), TCon("Bool"), TCon("String"), TCon("Unit")


def list_of(t):
    return TCon("List", [t])


def prune(t):
    """Follow substitution links, compressing the path as we go."""
    if isinstance(t, TVar) and t.ref is not None:
        t.ref = prune(t.ref)
        return t.ref
    return t


def show_type(t, names=None):
    names = {} if names is None else names

    def go(t):
        t = prune(t)
        if isinstance(t, TVar):
            if t.id not in names:
                i = len(names)
                names[t.id] = chr(ord("a") + i % 26) + (str(i // 26) if i >= 26 else "")
            return names[t.id]
        if isinstance(t, TFun):
            params = ", ".join(go(p) for p in t.params)  # name params' variables first
            ret = go(t.ret)
            if isinstance(prune(t.ret), TFun):
                ret = f"({ret})"  # () -> (() -> Int) rather than () -> () -> Int
            return f"({params}) -> {ret}"
        if t.args:
            return f"{t.name}[{', '.join(go(a) for a in t.args)}]"
        return t.name

    return go(t)


def show_scheme(s):
    return show_type(s.ty)


# ---------------------------------------------------------------- unification

class _Mismatch(Exception):
    pass


def _occurs_adjust(v, t):
    """Occurs check, and lower levels inside t so generalisation stays sound."""
    t = prune(t)
    if isinstance(t, TVar):
        if t is v:
            raise _Mismatch("infinite")
        t.level = min(t.level, v.level)
    elif isinstance(t, TFun):
        for p in t.params:
            _occurs_adjust(v, p)
        _occurs_adjust(v, t.ret)
    else:
        for a in t.args:
            _occurs_adjust(v, a)


def _require_eq(t):
    t = prune(t)
    if isinstance(t, TVar):
        t.eq = True
    elif isinstance(t, TFun):
        raise _Mismatch("eq")
    else:
        for a in t.args:
            _require_eq(a)


def _unify(a, b):
    a, b = prune(a), prune(b)
    if a is b:
        return
    if isinstance(a, TVar):
        _occurs_adjust(a, b)
        if a.eq:
            _require_eq(b)
        a.ref = b
    elif isinstance(b, TVar):
        _unify(b, a)
    elif isinstance(a, TFun) and isinstance(b, TFun):
        if len(a.params) != len(b.params):
            raise _Mismatch("arity")
        for x, y in zip(a.params, b.params):
            _unify(x, y)
        _unify(a.ret, b.ret)
    elif isinstance(a, TCon) and isinstance(b, TCon) and a.name == b.name and len(a.args) == len(b.args):
        for x, y in zip(a.args, b.args):
            _unify(x, y)
    else:
        raise _Mismatch("shape")


def unify(expected, actual, node, context=""):
    try:
        _unify(expected, actual)
    except _Mismatch as m:
        names = {}
        e, a = show_type(expected, names), show_type(actual, names)
        if str(m) == "infinite":
            msg = f"infinite type: {e} = {a} (a type cannot contain itself)"
        elif str(m) == "eq":
            msg = f"this value has function type {a}, but it ends up compared with == (functions cannot be compared)"
        else:
            msg = f"expected {e}, found {a}"
        raise TypeErr(f"{context}{': ' if context else ''}{msg}", node.line, node.col)


# ---------------------------------------------------------------- environments

class Binding:
    __slots__ = ("scheme", "mutable")

    def __init__(self, scheme, mutable=False):
        self.scheme = scheme
        self.mutable = mutable


class TEnv:
    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent

    def lookup(self, name):
        env = self
        while env is not None:
            if name in env.vars:
                return env.vars[name]
            env = env.parent
        return None

    def bind(self, name, scheme, mutable=False):
        self.vars[name] = Binding(scheme, mutable)


class CtorInfo:
    def __init__(self, name, type_name, tag, arity, scheme, siblings):
        self.name = name
        self.type_name = type_name
        self.tag = tag
        self.arity = arity
        self.scheme = scheme
        self.siblings = siblings  # [(name, arity)] for every ctor of the type


def builtin_schemes():
    def poly(make):
        v = TVar(1)
        return Scheme([v], make(v))
    return {
        "print": poly(lambda a: TFun([a], UNIT)),
        "to_string": poly(lambda a: TFun([a], STRING)),
        "panic": poly(lambda a: TFun([STRING], a)),
        "str_len": Scheme([], TFun([STRING], INT)),
        "substring": Scheme([], TFun([STRING, INT, INT], STRING)),
        "chars": Scheme([], TFun([STRING], list_of(STRING))),
        "clock_ms": Scheme([], TFun([], INT)),
        "reverse": poly(lambda a: TFun([list_of(a)], list_of(a))),
        "length": poly(lambda a: TFun([list_of(a)], INT)),
        "append": poly(lambda a: TFun([list_of(a), list_of(a)], list_of(a))),
        "sum": Scheme([], TFun([list_of(INT)], INT)),
        "range": Scheme([], TFun([INT, INT], list_of(INT))),
        "join": Scheme([], TFun([list_of(STRING), STRING], STRING)),
    }


# ---------------------------------------------------------------- the checker

class Checker:
    def __init__(self):
        self.type_arity = {"Int": 0, "Bool": 0, "String": 0, "Unit": 0, "List": 1}
        self.ctors = {}
        self.warnings = []
        self.toplevel_values = set()
        self.fn_schemes = {}  # top-level fn name -> Scheme (for --types)

    # ---- helpers ----

    def instantiate(self, scheme, level):
        if not scheme.quantified:
            return scheme.ty
        mapping = {v.id: TVar(level, v.eq) for v in scheme.quantified}

        def copy(t):
            t = prune(t)
            if isinstance(t, TVar):
                return mapping.get(t.id, t)
            if isinstance(t, TFun):
                return TFun([copy(p) for p in t.params], copy(t.ret))
            return TCon(t.name, [copy(a) for a in t.args]) if t.args else t

        return copy(scheme.ty)

    @staticmethod
    def generalize(t, level):
        seen, quantified = set(), []

        def walk(t):
            t = prune(t)
            if isinstance(t, TVar):
                if t.level > level and t.id not in seen:
                    seen.add(t.id)
                    quantified.append(t)
            elif isinstance(t, TFun):
                for p in t.params:
                    walk(p)
                walk(t.ret)
            else:
                for a in t.args:
                    walk(a)

        walk(t)
        return Scheme(quantified, t)

    def type_from_syntax(self, node, tvars, level, allow_new_vars=True):
        if isinstance(node, ast.TVarName):
            if node.name not in tvars:
                if not allow_new_vars:
                    raise TypeErr(f"unknown type variable '{node.name}'", node.line, node.col)
                tvars[node.name] = TVar(level)
            return tvars[node.name]
        if isinstance(node, ast.TFunc):
            return TFun([self.type_from_syntax(p, tvars, level, allow_new_vars) for p in node.params],
                        self.type_from_syntax(node.ret, tvars, level, allow_new_vars))
        arity = self.type_arity.get(node.name)
        if arity is None:
            raise TypeErr(f"unknown type '{node.name}'", node.line, node.col)
        if arity != len(node.args):
            raise TypeErr(f"type '{node.name}' takes {arity} parameter(s), got {len(node.args)}",
                          node.line, node.col)
        return TCon(node.name, [self.type_from_syntax(a, tvars, level, allow_new_vars) for a in node.args])

    # ---- program ----

    def check_program(self, prog):
        for td in prog.types:
            if td.name in self.type_arity:
                raise TypeErr(f"type '{td.name}' is already defined", td.line, td.col)
            self.type_arity[td.name] = len(td.params)
        for td in prog.types:
            self.declare_ctors(td)

        env = TEnv()
        for name, scheme in builtin_schemes().items():
            env.bind(name, scheme)
        self.toplevel_values = {s.name for s in prog.stmts if isinstance(s, ast.Let)}

        fn_env = TEnv(env)
        names = {}
        for f in prog.fns:
            if f.name in names:
                where = ("in the standard library (prelude)"
                         if getattr(names[f.name].fn, "from_prelude", False) else "twice")
                raise TypeErr(f"function '{f.name}' is defined {where}", f.line, f.col,
                              ["choose a different name"] if where != "twice" else [])
            names[f.name] = f
        for group in self.strongly_connected(prog.fns):
            self.infer_fn_group(group, fn_env, 0)
        for f in prog.fns:
            self.fn_schemes[f.name] = fn_env.lookup(f.name).scheme

        self.toplevel_values = set()
        top_env = TEnv(fn_env)
        self.infer_stmts(prog.stmts, top_env, 0)
        return top_env

    def declare_ctors(self, td):
        params = [TVar(1) for _ in td.params]
        tvars = dict(zip(td.params, params))
        if len(tvars) != len(td.params):
            raise TypeErr(f"duplicate type parameter in '{td.name}'", td.line, td.col)
        result = TCon(td.name, params)
        siblings = [(c.name, len(c.fields)) for c in td.ctors]
        for tag, c in enumerate(td.ctors):
            if c.name in self.ctors:
                raise TypeErr(f"constructor '{c.name}' is already defined", c.line, c.col)
            fields = [self.type_from_syntax(f, tvars, 1, allow_new_vars=False) for f in c.fields]
            ty = TFun(fields, result) if fields else result
            self.ctors[c.name] = CtorInfo(c.name, td.name, tag, len(fields), Scheme(params, ty), siblings)

    @staticmethod
    def strongly_connected(fns):
        """Tarjan's algorithm; yields groups with dependencies before dependents."""
        by_name = {f.name: f for f in fns}
        deps = {f.name: sorted(_free_names(f.fn) & by_name.keys()) for f in fns}
        index, low, on_stack, stack, out = {}, {}, set(), [], []
        counter = itertools.count()

        def visit(v):
            index[v] = low[v] = next(counter)
            stack.append(v)
            on_stack.add(v)
            for w in deps[v]:
                if w not in index:
                    visit(w)
                    low[v] = min(low[v], low[w])
                elif w in on_stack:
                    low[v] = min(low[v], index[w])
            if low[v] == index[v]:
                group = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    group.append(by_name[w])
                    if w == v:
                        break
                out.append(group)

        for f in fns:
            if f.name not in index:
                visit(f.name)
        return out

    def infer_fn_group(self, group, env, level):
        # Bind every member monomorphically, infer bodies, then generalise together.
        placeholders = {}
        for f in group:
            placeholders[f.name] = TVar(level + 1)
            env.bind(f.name, Scheme([], placeholders[f.name]))
        for f in group:
            t = self.infer_lambda(f.fn, env, level + 1)
            unify(placeholders[f.name], t, f)
        for f in group:
            env.bind(f.name, self.generalize(placeholders[f.name], level))

    # ---- statements ----

    def infer_stmts(self, stmts, env, level):
        result = UNIT
        for i, s in enumerate(stmts):
            result = UNIT
            if isinstance(s, ast.Let):
                t = self.infer(s.value, env, level + 1)
                if s.ann is not None:
                    unify(self.type_from_syntax(s.ann, {}, level + 1), t, s.value, f"in '{s.name}'")
                if not s.mutable and _is_syntactic_value(s.value):
                    scheme = self.generalize(t, level)
                else:
                    self._lower_levels(t, level)
                    scheme = Scheme([], t)
                env.bind(s.name, scheme, s.mutable)
                s.scheme = scheme
            elif isinstance(s, ast.Assign):
                b = env.lookup(s.name)
                if b is None:
                    raise TypeErr(f"undefined variable '{s.name}'", s.line, s.col)
                if not b.mutable:
                    raise TypeErr(f"cannot assign to '{s.name}': it was declared with 'let' (use 'var')",
                                  s.line, s.col)
                unify(b.scheme.ty, self.infer(s.value, env, level), s.value, f"assigning to '{s.name}'")
            elif isinstance(s, ast.While):
                unify(BOOL, self.infer(s.cond, env, level), s.cond, "while condition")
                self.infer(s.body, env, level)
            elif isinstance(s, ast.FnDecl):
                self.infer_fn_group([s], env, level)
                s.scheme = env.lookup(s.name).scheme
            else:
                result = self.infer(s.expr, env, level)
        return result

    @staticmethod
    def _lower_levels(t, level):
        t = prune(t)
        if isinstance(t, TVar):
            t.level = min(t.level, level)
        elif isinstance(t, TFun):
            for p in t.params:
                Checker._lower_levels(p, level)
            Checker._lower_levels(t.ret, level)
        else:
            for a in t.args:
                Checker._lower_levels(a, level)

    # ---- expressions ----

    def infer(self, e, env, level):
        t = getattr(self, "infer_" + type(e).__name__)(e, env, level)
        e.ty = t
        return t

    def infer_Lit(self, e, env, level):
        v = e.value
        if v is None:
            return UNIT
        if isinstance(v, bool):
            return BOOL
        if isinstance(v, int):
            return INT
        return STRING

    def infer_Var(self, e, env, level):
        b = env.lookup(e.name)
        if b is None:
            notes = []
            if e.name in self.toplevel_values:
                notes.append("top-level functions are hoisted and can't see top-level 'let' "
                             "values; pass it as an argument or make it a function")
            raise TypeErr(f"undefined variable '{e.name}'", e.line, e.col, notes)
        return self.instantiate(b.scheme, level)

    def infer_Ctor(self, e, env, level):
        info = self.ctors.get(e.name)
        if info is None:
            raise TypeErr(f"unknown constructor '{e.name}'", e.line, e.col)
        e.info = info
        return self.instantiate(info.scheme, level)

    def infer_ListLit(self, e, env, level):
        elem = TVar(level)
        for i, item in enumerate(e.items):
            unify(elem, self.infer(item, env, level), item, f"list element {i}")
        return list_of(elem)

    def infer_Lambda(self, e, env, level):
        return self.infer_lambda(e, env, level)

    def infer_lambda(self, e, env, level):
        tvars = {}
        inner = TEnv(env)
        params = []
        for p in e.params:
            t = self.type_from_syntax(p.ann, tvars, level) if p.ann else TVar(level)
            inner.bind(p.name, Scheme([], t))
            params.append(t)
        body = self.infer(e.body, inner, level)
        if e.ret_ann is not None:
            unify(self.type_from_syntax(e.ret_ann, tvars, level), body, e.body,
                  f"return type of '{e.name}'")
        return TFun(params, body)

    def infer_Call(self, e, env, level):
        ft = prune(self.infer(e.fn, env, level))
        args = [self.infer(a, env, level) for a in e.args]
        if isinstance(ft, TVar):
            ret = TVar(level)
            unify(ft, TFun(args, ret), e)
            return ret
        if not isinstance(ft, TFun):
            raise TypeErr(f"this is not a function, it has type {show_type(ft)}", e.fn.line, e.fn.col)
        name = _callee_name(e.fn)
        if len(ft.params) != len(args):
            raise TypeErr(f"{name} takes {len(ft.params)} argument(s) but {len(args)} were given",
                          e.line, e.col, [f"{name} has type {show_type(ft)}"])
        for i, (p, a, node) in enumerate(zip(ft.params, args, e.args)):
            unify(p, a, node, f"argument {i + 1} of {name}")
        return ft.ret

    def infer_BinOp(self, e, env, level):
        op = e.op
        lt = self.infer(e.left, env, level)
        rt = self.infer(e.right, env, level)
        ctx = f"operand of '{op}'"
        if op in ("+", "-", "*", "/", "%"):
            unify(INT, lt, e.left, ctx)
            unify(INT, rt, e.right, ctx)
            return INT
        if op in ("<", "<=", ">", ">="):
            unify(INT, lt, e.left, ctx)
            unify(INT, rt, e.right, ctx)
            return BOOL
        if op in ("==", "!="):
            unify(lt, rt, e.right, "both sides of a comparison must have the same type")
            try:
                _require_eq(lt)
            except _Mismatch:
                raise TypeErr(f"functions cannot be compared with ==: {show_type(lt)}", e.line, e.col)
            return BOOL
        if op in ("and", "or"):
            unify(BOOL, lt, e.left, ctx)
            unify(BOOL, rt, e.right, ctx)
            return BOOL
        if op == "++":
            unify(STRING, lt, e.left, ctx)
            unify(STRING, rt, e.right, ctx)
            return STRING
        if op == "::":
            unify(list_of(lt), rt, e.right, "right side of '::'")
            return rt
        raise TypeErr(f"unknown operator {op}", e.line, e.col)

    def infer_Unary(self, e, env, level):
        t = self.infer(e.operand, env, level)
        want = BOOL if e.op == "not" else INT
        unify(want, t, e.operand, f"operand of '{e.op}'")
        return want

    def infer_If(self, e, env, level):
        unify(BOOL, self.infer(e.cond, env, level), e.cond, "if condition")
        then = self.infer(e.then, env, level)
        if e.else_ is None:
            unify(UNIT, then, e.then, "an 'if' without 'else' must produce ()")
            return UNIT
        unify(then, self.infer(e.else_, env, level), e.else_, "'else' branch must match the 'if' branch")
        return then

    def infer_Block(self, e, env, level):
        return self.infer_stmts(e.stmts, TEnv(env), level)

    def infer_Match(self, e, env, level):
        st = self.infer(e.scrutinee, env, level)
        result = TVar(level)
        for arm in e.arms:
            bindings = {}
            self.check_pattern(arm.pat, st, bindings, level)
            inner = TEnv(env)
            for name, t in bindings.items():
                inner.bind(name, Scheme([], t))
            unify(result, self.infer(arm.body, inner, level), arm.body, "match arms must have the same type")
        self.check_exhaustive(e)
        return result

    # ---- patterns ----

    def check_pattern(self, p, ty, bindings, level):
        if isinstance(p, ast.PWild):
            return
        if isinstance(p, ast.PVar):
            if p.name in bindings:
                raise TypeErr(f"'{p.name}' is bound twice in this pattern", p.line, p.col)
            bindings[p.name] = ty
        elif isinstance(p, ast.PLit):
            unify(ty, self.infer_Lit(p, None, level), p, "pattern type")
        elif isinstance(p, ast.PNil):
            unify(ty, list_of(TVar(level)), p, "pattern type")
        elif isinstance(p, ast.PCons):
            elem = TVar(level)
            unify(ty, list_of(elem), p, "pattern type")
            self.check_pattern(p.head, elem, bindings, level)
            self.check_pattern(p.tail, list_of(elem), bindings, level)
        elif isinstance(p, ast.PCtor):
            info = self.ctors.get(p.name)
            if info is None:
                raise TypeErr(f"unknown constructor '{p.name}'", p.line, p.col)
            if info.arity != len(p.args):
                raise TypeErr(f"constructor '{p.name}' has {info.arity} field(s), pattern gives {len(p.args)}",
                              p.line, p.col)
            p.info = info
            t = self.instantiate(info.scheme, level)
            if isinstance(t, TFun):
                unify(ty, t.ret, p, "pattern type")
                for sub, ft in zip(p.args, t.params):
                    self.check_pattern(sub, ft, bindings, level)
            else:
                unify(ty, t, p, "pattern type")

    def check_exhaustive(self, m):
        rows = []
        for i, arm in enumerate(m.arms):
            row = [self._normalize(arm.pat)]
            if not ex.useful(rows, row):
                self.warnings.append(Warn("unreachable match arm (earlier arms already cover it)",
                                             arm.line, arm.col))
            rows.append(row)
        missing = ex.witness(rows, 1)
        if missing is not None:
            raise TypeErr("match is not exhaustive", m.line, m.col,
                          [f"for example, this value is not handled: {ex.show(missing[0])}"])

    def _normalize(self, p):
        if isinstance(p, (ast.PWild, ast.PVar)):
            return ex.WILD
        if isinstance(p, ast.PLit):
            v = p.value
            if v is None:
                return ex.con(None, [], "unit")
            if isinstance(v, bool):
                return ex.con(v, [], "bool")
            return ex.con(("lit", v), [], "lit")
        if isinstance(p, ast.PNil):
            return ex.con("[]", [], "list")
        if isinstance(p, ast.PCons):
            return ex.con("::", [self._normalize(p.head), self._normalize(p.tail)], "list")
        info = self.ctors[p.name]
        return ex.con(p.name, [self._normalize(a) for a in p.args], ("adt", tuple(info.siblings)))


# ---------------------------------------------------------------- syntactic helpers

def _is_syntactic_value(e):
    if isinstance(e, (ast.Lambda, ast.Lit, ast.Var, ast.Ctor)):
        return True
    if isinstance(e, ast.ListLit):
        return all(_is_syntactic_value(x) for x in e.items)
    return False


def _callee_name(fn):
    if isinstance(fn, (ast.Var, ast.Ctor)):
        return f"'{fn.name}'"
    return "this function"


def _free_names(node):
    """All variable names referenced anywhere under node (an over-approximation is fine here)."""
    out = set()
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, ast.Var):
            out.add(n.name)
        elif isinstance(n, ast.Node):
            for v in vars(n).values():
                if isinstance(v, ast.Node):
                    stack.append(v)
                elif isinstance(v, list):
                    stack.extend(x for x in v if isinstance(x, ast.Node))
    return out


def check(prog):
    checker = Checker()
    checker.check_program(prog)
    return checker
