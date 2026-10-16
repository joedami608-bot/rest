"""Bytecode compiler.

Two passes over the type-checked AST:

1. `Resolver` works out, for every variable, which function owns it and whether an
   inner function captures it. Captured variables live in heap `Cell`s (like
   CPython's cellvars); everything else lives in a stack slot.
2. `FnCompiler` emits flat bytecode, using tail calls for calls in tail position
   and a few superinstructions for hot patterns such as `n - 1`.
"""

from . import syntax as ast
from . import opcodes as op
from .runtime import Code, CtorFn, NATIVES


# ---------------------------------------------------------------- pass 1: scopes and captures

class VarInfo:
    __slots__ = ("name", "func", "captured", "is_global", "gindex")

    def __init__(self, name, func, is_global=False, gindex=None):
        self.name = name
        self.func = func          # owning FuncScope (None for globals)
        self.captured = False
        self.is_global = is_global
        self.gindex = gindex


class FuncScope:
    def __init__(self, parent):
        self.parent = parent
        self.freevars = []        # VarInfos captured from enclosing functions, in index order
        self.free_index = {}


class Scope:
    def __init__(self, parent, func):
        self.parent = parent
        self.func = func
        self.names = {}

    def lookup(self, name):
        s = self
        while s is not None:
            if name in s.names:
                return s.names[name]
            s = s.parent
        return None


class Resolver:
    def __init__(self):
        self.globals = []         # global slot -> name (for debugging)

    def new_global(self, name):
        self.globals.append(name)
        return VarInfo(name, None, is_global=True, gindex=len(self.globals) - 1)

    def program(self, prog):
        root = Scope(None, None)
        for name in NATIVES:
            root.names[name] = self.new_global(name)
        for f in prog.fns:
            info = self.new_global(f.name)
            root.names[f.name] = info
            f.var = info
        for f in prog.fns:
            self.lambda_(f.fn, root, None)
        main = FuncScope(None)
        prog.scope = main
        top = Scope(root, main)
        for s in prog.stmts:
            self.stmt(s, top, toplevel=True)

    def declare(self, name, scope, toplevel=False):
        info = self.new_global(name) if toplevel else VarInfo(name, scope.func)
        scope.names[name] = info
        return info

    def reference(self, name, scope):
        info = scope.lookup(name)
        assert info is not None, f"unresolved {name} (type checker should have caught this)"
        if not info.is_global and info.func is not scope.func:
            info.captured = True
            f = scope.func
            while f is not info.func:
                if id(info) not in f.free_index:
                    f.free_index[id(info)] = len(f.freevars)
                    f.freevars.append(info)
                f = f.parent
        return info

    def lambda_(self, lam, scope, parent_func):
        func = FuncScope(parent_func)
        lam.scope = func
        inner = Scope(scope, func)
        for p in lam.params:
            p.var = self.declare(p.name, inner)
        self.expr(lam.body, inner)

    def stmt(self, s, scope, toplevel=False):
        if isinstance(s, ast.Let):
            self.expr(s.value, scope)
            s.var = self.declare(s.name, scope, toplevel)
        elif isinstance(s, ast.Assign):
            self.expr(s.value, scope)
            s.var = self.reference(s.name, scope)
        elif isinstance(s, ast.While):
            self.expr(s.cond, scope)
            self.expr(s.body, scope)
        elif isinstance(s, ast.FnDecl):
            s.var = self.declare(s.name, scope, toplevel)  # visible in its own body
            self.lambda_(s.fn, scope, scope.func)
        else:
            self.expr(s.expr, scope)

    def expr(self, e, scope):
        if isinstance(e, ast.Var):
            e.var = self.reference(e.name, scope)
        elif isinstance(e, ast.Lambda):
            self.lambda_(e, scope, scope.func)
        elif isinstance(e, ast.Block):
            inner = Scope(scope, scope.func)
            for s in e.stmts:
                self.stmt(s, inner)
        elif isinstance(e, ast.Match):
            self.expr(e.scrutinee, scope)
            for arm in e.arms:
                inner = Scope(scope, scope.func)
                self.pattern(arm.pat, inner)
                self.expr(arm.body, inner)
        elif isinstance(e, ast.ListLit):
            for x in e.items:
                self.expr(x, scope)
        elif isinstance(e, ast.Call):
            self.expr(e.fn, scope)
            for a in e.args:
                self.expr(a, scope)
        elif isinstance(e, ast.BinOp):
            self.expr(e.left, scope)
            self.expr(e.right, scope)
        elif isinstance(e, ast.Unary):
            self.expr(e.operand, scope)
        elif isinstance(e, ast.If):
            self.expr(e.cond, scope)
            self.expr(e.then, scope)
            if e.else_ is not None:
                self.expr(e.else_, scope)

    def pattern(self, p, scope):
        if isinstance(p, ast.PVar):
            p.var = self.declare(p.name, scope)
        elif isinstance(p, ast.PCons):
            self.pattern(p.head, scope)
            self.pattern(p.tail, scope)
        elif isinstance(p, ast.PCtor):
            for a in p.args:
                self.pattern(a, scope)


# ---------------------------------------------------------------- pass 2: code generation

ARITH = {"+": op.ADD, "-": op.SUB, "*": op.MUL, "/": op.DIV, "%": op.MOD, "++": op.CONCAT,
         "==": op.EQ, "!=": op.NE, "<": op.LT, "<=": op.LE, ">": op.GT, ">=": op.GE, "::": op.CONS}
FUSED = {"+": op.LOAD_LOCAL_CONST_ADD, "-": op.LOAD_LOCAL_CONST_SUB, "<": op.LOAD_LOCAL_CONST_LT}


class FnCompiler:
    def __init__(self, name, scope, arity):
        self.name = name
        self.scope = scope
        self.arity = arity
        self.code = []
        self.lines = []
        self.consts = []
        self.const_index = {}
        self.slots = {}
        self.nlocals = 0
        self.pos = (0, 0)

    # ---- emission helpers ----

    def emit(self, opcode, *args):
        self.code.append(opcode)
        self.code.extend(args)
        self.lines.extend([self.pos] * (1 + len(args)))
        return len(self.code) - len(args)  # position of the first operand (for patching)

    def at(self, node):
        if getattr(node, "line", 0):
            self.pos = (node.line, node.col)

    def const(self, value):
        key = (type(value), value) if isinstance(value, (int, str, bool)) or value is None else id(value)
        if key not in self.const_index:
            self.const_index[key] = len(self.consts)
            self.consts.append(value)
        return self.const_index[key]

    def new_slot(self):
        self.nlocals += 1
        return self.nlocals - 1

    def label(self):
        return len(self.code)

    def patch(self, operand_pos, target=None):
        self.code[operand_pos] = len(self.code) if target is None else target

    def finish(self):
        return Code(self.name, self.arity, self.nlocals, self.code, self.consts, self.lines,
                    len(self.scope.freevars))

    # ---- variables ----

    def bind(self, info):
        """Store the value on top of the stack into a freshly declared variable."""
        if info.is_global:
            self.emit(op.STORE_GLOBAL, info.gindex)
            return
        slot = self.slots[id(info)] = self.new_slot()
        self.emit(op.STORE_NEW_CELL if info.captured else op.STORE_LOCAL, slot)

    def load(self, info):
        if info.is_global:
            self.emit(op.LOAD_GLOBAL, info.gindex)
        elif info.func is self.scope:
            slot = self.slots[id(info)]
            self.emit(op.LOAD_CELL if info.captured else op.LOAD_LOCAL, slot)
        else:
            self.emit(op.LOAD_FREE, self.scope.free_index[id(info)])

    def store(self, info):
        if info.is_global:
            self.emit(op.STORE_GLOBAL, info.gindex)
        elif info.func is self.scope:
            slot = self.slots[id(info)]
            self.emit(op.STORE_CELL if info.captured else op.STORE_LOCAL, slot)
        else:
            self.emit(op.STORE_FREE, self.scope.free_index[id(info)])

    def plain_local(self, e):
        """Slot of e if it is a non-captured local of this function, else None."""
        if isinstance(e, ast.Var) and not e.var.is_global and not e.var.captured \
                and e.var.func is self.scope:
            return self.slots[id(e.var)]
        return None

    # ---- functions ----

    def lambda_(self, lam):
        child = FnCompiler(lam.name, lam.scope, len(lam.params))
        child.at(lam)
        for p in lam.params:
            slot = child.slots[id(p.var)] = child.new_slot()
            if p.var.captured:
                child.emit(op.MAKE_CELL, slot)
        child.expr(lam.body, tail=True)
        child.emit(op.RETURN)
        code = child.finish()
        code.prelude = getattr(lam, "from_prelude", False)
        captures = []
        for info in lam.scope.freevars:
            if info.func is self.scope:
                captures += [0, self.slots[id(info)]]           # our own cell
            else:
                captures += [1, self.scope.free_index[id(info)]]  # passed down from our parent
        self.emit(op.CLOSURE, self.const(code), len(lam.scope.freevars), *captures)

    # ---- statements ----

    def stmt(self, s):
        self.at(s)
        if isinstance(s, ast.Let):
            self.expr(s.value)
            self.bind(s.var)
        elif isinstance(s, ast.Assign):
            self.expr(s.value)
            self.store(s.var)
        elif isinstance(s, ast.While):
            top = self.label()
            self.expr(s.cond)
            exit_ = self.emit(op.JUMP_IF_FALSE, 0)
            for body_stmt in s.body.stmts:  # body value is discarded, so don't produce one
                self.stmt(body_stmt)
            self.emit(op.JUMP, top)
            self.patch(exit_)
        elif isinstance(s, ast.FnDecl):
            info = s.var
            if info.is_global:
                self.lambda_(s.fn)
                self.emit(op.STORE_GLOBAL, info.gindex)
            elif info.captured:  # recursive or captured: the cell must exist before the closure
                slot = self.slots[id(info)] = self.new_slot()
                self.emit(op.NEW_CELL, slot)
                self.lambda_(s.fn)
                self.emit(op.STORE_CELL, slot)
            else:
                self.lambda_(s.fn)
                self.bind(info)
        else:
            self.expr(s.expr)
            self.emit(op.POP)

    def block(self, stmts, tail):
        if not stmts:
            self.emit(op.UNIT)
            return
        for s in stmts[:-1]:
            self.stmt(s)
        last = stmts[-1]
        if isinstance(last, ast.ExprStmt):
            self.at(last)
            self.expr(last.expr, tail)
        else:
            self.stmt(last)
            self.emit(op.UNIT)

    # ---- expressions ----

    def expr(self, e, tail=False):
        self.at(e)
        getattr(self, "expr_" + type(e).__name__)(e, tail)

    def expr_Lit(self, e, tail):
        if e.value is None:
            self.emit(op.UNIT)
        else:
            self.emit(op.CONST, self.const(e.value))

    def expr_Var(self, e, tail):
        self.load(e.var)

    def expr_Ctor(self, e, tail):
        info = e.info
        if info.arity == 0:
            self.emit(op.MAKE_DATA, self.const((info.tag, info.name)), 0)
        else:
            self.emit(op.CONST, self.const(CtorFn(info.tag, info.name, info.arity)))

    def expr_ListLit(self, e, tail):
        for x in e.items:
            self.expr(x)
        self.emit(op.LIST, len(e.items))

    def expr_Lambda(self, e, tail):
        self.lambda_(e)

    def expr_Block(self, e, tail):
        self.block(e.stmts, tail)

    def expr_Call(self, e, tail):
        if isinstance(e.fn, ast.Ctor):
            info = e.fn.info
            if info.arity == len(e.args) > 0:
                for a in e.args:
                    self.expr(a)
                self.at(e)
                self.emit(op.MAKE_DATA, self.const((info.tag, info.name)), info.arity)
                return
        self.expr(e.fn)
        for a in e.args:
            self.expr(a)
        self.at(e)
        self.emit(op.TAIL_CALL if tail else op.CALL, len(e.args))

    def expr_Unary(self, e, tail):
        self.expr(e.operand)
        self.emit(op.NOT if e.op == "not" else op.NEG)

    def expr_BinOp(self, e, tail):
        if e.op in ("and", "or"):
            self.expr(e.left)
            j = self.emit(op.JUMP_IF_FALSE_OR_POP if e.op == "and" else op.JUMP_IF_TRUE_OR_POP, 0)
            self.expr(e.right, tail)  # the right operand's value is the result: a tail position
            self.patch(j)
            return
        slot = self.plain_local(e.left)
        if slot is not None and e.op in FUSED and isinstance(e.right, ast.Lit) \
                and type(e.right.value) is int:
            self.emit(FUSED[e.op], slot, self.const(e.right.value))
            return
        right_slot = self.plain_local(e.right)
        if slot is not None and right_slot is not None:
            self.emit(op.LOAD_LOCAL2, slot, right_slot)
        else:
            self.expr(e.left)
            self.expr(e.right)
        self.at(e)
        self.emit(ARITH[e.op])

    def expr_If(self, e, tail):
        self.expr(e.cond)
        to_else = self.emit(op.JUMP_IF_FALSE, 0)
        self.expr(e.then, tail)
        to_end = self.emit(op.JUMP, 0)
        self.patch(to_else)
        if e.else_ is None:
            self.emit(op.UNIT)
        else:
            self.expr(e.else_, tail)
        self.patch(to_end)

    def expr_Match(self, e, tail):
        self.expr(e.scrutinee)
        subject = self.new_slot()
        self.emit(op.STORE_LOCAL, subject)
        ends = []
        for arm in e.arms:
            fails = []
            self.at(arm)
            self.pattern(arm.pat, subject, fails)
            self.expr(arm.body, tail)
            ends.append(self.emit(op.JUMP, 0))
            for f in fails:
                self.patch(f)
        self.at(e)
        self.emit(op.MATCH_FAIL)
        for j in ends:
            self.patch(j)

    # ---- pattern tests ----

    def pattern(self, p, src, fails):
        """Test the value in slot `src` against p; jumps recorded in `fails` go to the next arm."""
        if isinstance(p, ast.PWild):
            return
        if isinstance(p, ast.PVar):
            self.emit(op.LOAD_LOCAL, src)
            self.bind(p.var)
        elif isinstance(p, ast.PLit):
            if p.value is None:   # () is the only value of type Unit
                return
            self.emit(op.LOAD_LOCAL, src)
            self.emit(op.CONST, self.const(p.value))
            self.emit(op.EQ)
            fails.append(self.emit(op.JUMP_IF_FALSE, 0))
        elif isinstance(p, ast.PNil):
            self.emit(op.LOAD_LOCAL, src)
            self.emit(op.IS_NIL)
            fails.append(self.emit(op.JUMP_IF_FALSE, 0))
        elif isinstance(p, ast.PCons):
            self.emit(op.LOAD_LOCAL, src)
            self.emit(op.IS_NIL)
            fails.append(self.emit(op.JUMP_IF_TRUE, 0))
            self.sub_pattern(p.head, src, (op.HEAD,), fails)
            self.sub_pattern(p.tail, src, (op.TAIL,), fails)
        elif isinstance(p, ast.PCtor):
            info = p.info
            if len(info.siblings) > 1:
                self.emit(op.LOAD_LOCAL, src)
                self.emit(op.TAG_EQ, info.tag)
                fails.append(self.emit(op.JUMP_IF_FALSE, 0))
            for i, sub in enumerate(p.args):
                self.sub_pattern(sub, src, (op.FIELD, i), fails)

    def sub_pattern(self, p, src, extract, fails):
        if isinstance(p, ast.PWild):
            return
        self.emit(op.LOAD_LOCAL, src)
        self.emit(*extract)
        if isinstance(p, ast.PVar):
            self.bind(p.var)
            return
        tmp = self.new_slot()
        self.emit(op.STORE_LOCAL, tmp)
        self.pattern(p, tmp, fails)


def compile_program(prog):
    """Returns (main Code, number of globals, global names)."""
    resolver = Resolver()
    resolver.program(prog)
    main = FnCompiler("<main>", prog.scope, 0)
    for f in prog.fns:              # hoisted: define every top-level fn first
        main.at(f)
        main.lambda_(f.fn)
        main.emit(op.STORE_GLOBAL, f.var.gindex)
    main.block(prog.stmts, tail=False)
    main.emit(op.RETURN)
    return main.finish(), resolver.globals
