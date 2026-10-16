"""Tree-walking interpreter with lexical scoping and first-class closures."""

from . import ast
from .errors import MiniRuntimeError


# ---------------------------------------------------------------- runtime values

class Env:
    """A lexical scope. Lookups walk outward through `parent`."""

    __slots__ = ("vars", "parent")

    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent

    def define(self, name, value):
        self.vars[name] = value

    def find(self, name):
        env = self
        while env is not None:
            if name in env.vars:
                return env
            env = env.parent
        return None


class Closure:
    __slots__ = ("fn", "env", "name")

    def __init__(self, fn: ast.Function, env: Env):
        self.fn = fn
        self.env = env
        self.name = fn.name or "<anonymous>"

    @property
    def arity(self):
        return len(self.fn.params)


class Builtin:
    __slots__ = ("name", "impl", "min_args", "max_args")

    def __init__(self, name, impl, min_args, max_args=None):
        self.name = name
        self.impl = impl
        self.min_args = min_args
        self.max_args = min_args if max_args is None else max_args


# Non-local control flow is modelled with exceptions.
class _Return(Exception):
    def __init__(self, value):
        self.value = value


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


# ---------------------------------------------------------------- helpers

def type_name(v):
    if v is None:
        return "nil"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "map"
    if isinstance(v, range):
        return "range"
    if isinstance(v, (Closure, Builtin)):
        return "function"
    return type(v).__name__


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def truthy(v):
    # Only `false` and `nil` are falsy (0 and "" are truthy), like Ruby/Lua.
    return not (v is None or v is False)


def equal(a, b):
    # Keep bools distinct from numbers (Python says True == 1).
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
    if is_number(a) and is_number(b):
        return a == b
    if type(a) is not type(b):
        return False
    return a == b


def show(v, nested=False):
    """Human-readable representation of a runtime value."""
    if v is None:
        return "nil"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float):
        return repr(int(v)) + ".0" if v.is_integer() else repr(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"' if nested else v
    if isinstance(v, list):
        return "[" + ", ".join(show(x, True) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{show(k, True)}: {show(x, True)}" for k, x in v.items()) + "}"
    if isinstance(v, range):
        return f"{v.start}..{v.stop}"
    if isinstance(v, Closure):
        return f"<fn {v.name}>"
    if isinstance(v, Builtin):
        return f"<builtin {v.name}>"
    return repr(v)


# ---------------------------------------------------------------- interpreter

class Interpreter:
    MAX_DEPTH = 2000

    def __init__(self, output=print):
        from .builtins import install  # local import avoids a cycle
        self.globals = Env()
        self.output = output
        self.depth = 0
        install(self)

    # ---- entry points ----

    def run(self, program):
        """Execute a list of statements; return the value of the last one."""
        try:
            return self.exec_block(program, self.globals)
        except _Return as r:
            return r.value
        except (_Break, _Continue):
            raise MiniRuntimeError("break/continue outside of a loop")

    # ---- statements ----

    def exec_block(self, stmts, env):
        result = None
        for stmt in stmts:
            result = self.exec(stmt, env)
        return result

    def exec(self, node, env):
        method = getattr(self, "exec_" + type(node).__name__, None)
        if method is not None:
            return method(node, env)
        if isinstance(node, ast.ExprStmt):
            return self.eval(node.expr, env)
        raise MiniRuntimeError(f"cannot execute {type(node).__name__}", node.line, node.col)

    def exec_Let(self, node, env):
        value = self.eval(node.value, env)
        if isinstance(value, Closure) and value.fn.name is None and value.name == "<anonymous>":
            value.name = node.name  # name anonymous fns for error traces
        env.define(node.name, value)
        return None

    def exec_While(self, node, env):
        while truthy(self.eval(node.cond, env)):
            try:
                self.exec_block(node.body, Env(env))
            except _Break:
                break
            except _Continue:
                continue
        return None

    def exec_For(self, node, env):
        iterable = self.eval(node.iterable, env)
        if isinstance(iterable, dict):
            items = list(iterable.keys())
        elif isinstance(iterable, (list, range, str)):
            items = list(iterable) if isinstance(iterable, list) else iterable
        else:
            raise MiniRuntimeError(f"cannot iterate over {type_name(iterable)}", node.line, node.col)
        for item in items:
            scope = Env(env)
            scope.define(node.var, item)
            try:
                self.exec_block(node.body, scope)
            except _Break:
                break
            except _Continue:
                continue
        return None

    def exec_Return(self, node, env):
        raise _Return(None if node.value is None else self.eval(node.value, env))

    def exec_Break(self, node, env):
        raise _Break()

    def exec_Continue(self, node, env):
        raise _Continue()

    # ---- expressions ----

    def eval(self, node, env):
        return getattr(self, "eval_" + type(node).__name__)(node, env)

    def eval_Literal(self, node, env):
        return node.value

    def eval_Name(self, node, env):
        scope = env.find(node.name)
        if scope is None:
            raise MiniRuntimeError(f"undefined variable {node.name!r}", node.line, node.col)
        return scope.vars[node.name]

    def eval_ArrayLit(self, node, env):
        return [self.eval(x, env) for x in node.items]

    def eval_MapLit(self, node, env):
        out = {}
        for k, v in node.pairs:
            key = self.eval(k, env)
            self._check_key(key, k)
            out[key] = self.eval(v, env)
        return out

    def eval_Function(self, node, env):
        return Closure(node, env)

    def eval_IfExpr(self, node, env):
        if truthy(self.eval(node.cond, env)):
            return self.exec_block(node.then, Env(env))
        if node.otherwise is not None:
            return self.exec_block(node.otherwise, Env(env))
        return None

    def eval_Unary(self, node, env):
        v = self.eval(node.operand, env)
        if node.op == "not":
            return not truthy(v)
        if not is_number(v):
            raise MiniRuntimeError(f"cannot negate {type_name(v)}", node.line, node.col)
        return -v

    def eval_Logical(self, node, env):
        left = self.eval(node.left, env)
        if node.op == "and":
            return self.eval(node.right, env) if truthy(left) else left
        return left if truthy(left) else self.eval(node.right, env)

    def eval_Binary(self, node, env):
        a = self.eval(node.left, env)
        b = self.eval(node.right, env)
        op = node.op
        if op == "==":
            return equal(a, b)
        if op == "!=":
            return not equal(a, b)

        def fail():
            raise MiniRuntimeError(
                f"unsupported operands for {op}: {type_name(a)} and {type_name(b)}",
                node.line, node.col)

        if op == "+":
            if is_number(a) and is_number(b):
                return a + b
            if isinstance(a, str) and isinstance(b, str):
                return a + b
            if isinstance(a, list) and isinstance(b, list):
                return a + b
            fail()
        if op == "*" and isinstance(a, (str, list)) and isinstance(b, int) and not isinstance(b, bool):
            return a * b
        if op in ("<", "<=", ">", ">="):
            if not ((is_number(a) and is_number(b)) or (isinstance(a, str) and isinstance(b, str))):
                fail()
            return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
        if op == "..":
            if not (isinstance(a, int) and isinstance(b, int)) or isinstance(a, bool) or isinstance(b, bool):
                fail()
            return range(a, b)
        if not (is_number(a) and is_number(b)):
            fail()
        if op in ("/", "%") and b == 0:
            raise MiniRuntimeError("division by zero", node.line, node.col)
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            # Integer division stays integral when exact: 6 / 3 == 2, 7 / 2 == 3.5
            if isinstance(a, int) and isinstance(b, int) and a % b == 0:
                return a // b
            return a / b
        if op == "%":
            return a % b
        fail()

    def eval_Assign(self, node, env):
        value = self.eval(node.value, env)
        target = node.target
        if isinstance(target, ast.Name):
            scope = env.find(target.name)
            if scope is None:
                raise MiniRuntimeError(
                    f"assignment to undeclared variable {target.name!r} (use 'let')",
                    target.line, target.col)
            scope.vars[target.name] = value
            return value
        obj = self.eval(target.obj, env)
        key = self.eval(target.index, env)
        if isinstance(obj, list):
            obj[self._array_index(obj, key, target)] = value
        elif isinstance(obj, dict):
            self._check_key(key, target)
            obj[key] = value
        else:
            raise MiniRuntimeError(f"cannot assign into {type_name(obj)}", target.line, target.col)
        return value

    def eval_Index(self, node, env):
        obj = self.eval(node.obj, env)
        key = self.eval(node.index, env)
        if isinstance(obj, (list, str, range)):
            return obj[self._array_index(obj, key, node)]
        if isinstance(obj, dict):
            return obj.get(key) if isinstance(key, (str, int, float, bool)) or key is None else None
        raise MiniRuntimeError(f"cannot index into {type_name(obj)}", node.line, node.col)

    def eval_Call(self, node, env):
        callee = self.eval(node.callee, env)
        args = [self.eval(a, env) for a in node.args]
        return self.call(callee, args, node)

    # ---- calling ----

    def call(self, callee, args, node):
        if isinstance(callee, Builtin):
            n = len(args)
            if n < callee.min_args or (callee.max_args >= 0 and n > callee.max_args):
                want = (str(callee.min_args) if callee.min_args == callee.max_args
                        else f"{callee.min_args}+" if callee.max_args < 0
                        else f"{callee.min_args}-{callee.max_args}")
                raise MiniRuntimeError(
                    f"{callee.name}() takes {want} argument(s), got {n}", node.line, node.col)
            try:
                return callee.impl(self, args, node)
            except MiniRuntimeError as e:
                if e.line is None:
                    e.line, e.col = node.line, node.col
                raise
        if not isinstance(callee, Closure):
            raise MiniRuntimeError(f"{type_name(callee)} is not callable", node.line, node.col)
        if len(args) != callee.arity:
            raise MiniRuntimeError(
                f"{callee.name}() takes {callee.arity} argument(s), got {len(args)}",
                node.line, node.col)
        if self.depth >= self.MAX_DEPTH:
            raise MiniRuntimeError(f"stack overflow (max depth {self.MAX_DEPTH})", node.line, node.col)

        scope = Env(callee.env)
        for p, a in zip(callee.fn.params, args):
            scope.define(p, a)
        self.depth += 1
        try:
            return self.exec_block(callee.fn.body, scope)  # implicit return of last expr
        except _Return as r:
            return r.value
        except (_Break, _Continue):
            raise MiniRuntimeError("break/continue outside of a loop", node.line, node.col)
        except MiniRuntimeError as e:
            e.trace.append(f"in {callee.name}() called at {node.line}:{node.col}")
            raise
        finally:
            self.depth -= 1

    # ---- misc ----

    @staticmethod
    def _array_index(seq, key, node):
        if not isinstance(key, int) or isinstance(key, bool):
            raise MiniRuntimeError(f"index must be an integer, got {type_name(key)}", node.line, node.col)
        i = key + len(seq) if key < 0 else key
        if not 0 <= i < len(seq):
            raise MiniRuntimeError(f"index {key} out of bounds (length {len(seq)})", node.line, node.col)
        return i

    @staticmethod
    def _check_key(key, node):
        if not (isinstance(key, (str, int, float, bool)) or key is None):
            raise MiniRuntimeError(f"{type_name(key)} cannot be a map key", node.line, node.col)
