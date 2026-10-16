"""Pratt (top-down operator precedence) parser producing an AST.

Grammar sketch (semicolons are optional statement separators):

    program   := stmt*
    stmt      := "let" IDENT "=" expr
               | "fn" IDENT "(" params ")" body          # sugar for let + fn
               | "while" expr block
               | "for" IDENT "in" expr block
               | "return" expr? | "break" | "continue"
               | expr
    body      := block | "->" expr
    expr      := pratt expression, see PRECEDENCE below
"""

from . import syntax as ast
from .errors import MiniSyntaxError
from .lexer import tokenize

# Binding power for infix operators (higher binds tighter).
PRECEDENCE = {
    "=": 1,
    "|>": 2,
    "or": 3,
    "and": 4,
    "==": 5, "!=": 5,
    "<": 6, "<=": 6, ">": 6, ">=": 6,
    "..": 7,
    "+": 8, "-": 8,
    "*": 9, "/": 9, "%": 9,
    # unary minus uses 10
    "(": 11, "[": 11, ".": 11,
}
NEG_BP = 10
NOT_BP = 4  # like Python: `not a == b` means `not (a == b)`


class Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.i = 0

    # ---- token helpers ----

    @property
    def cur(self):
        return self.toks[self.i]

    def _is(self, kind, value=None):
        t = self.cur
        return t.kind == kind and (value is None or t.value == value)

    def _is_op(self, value):
        return self._is("OP", value)

    def _is_kw(self, value):
        return self._is("KEYWORD", value)

    def _next(self):
        t = self.cur
        if t.kind != "EOF":
            self.i += 1
        return t

    def _expect(self, kind, value=None, what=None):
        if not self._is(kind, value):
            t = self.cur
            want = what or (repr(value) if value is not None else kind.lower())
            got = "end of input" if t.kind == "EOF" else repr(t.value)
            raise MiniSyntaxError(f"expected {want}, got {got}", t.line, t.col)
        return self._next()

    def _skip_semis(self):
        while self._is_op(";"):
            self._next()

    @staticmethod
    def _pos(tok):
        return {"line": tok.line, "col": tok.col}

    # ---- statements ----

    def parse_program(self):
        stmts = []
        self._skip_semis()
        while not self._is("EOF"):
            stmts.append(self.statement())
            self._skip_semis()
        return stmts

    def statement(self):
        t = self.cur
        if self._is_kw("let"):
            self._next()
            name = self._expect("IDENT", what="variable name").value
            self._expect("OP", "=")
            return ast.Let(name, self.expression(), **self._pos(t))
        if self._is_kw("fn") and self.toks[self.i + 1].kind == "IDENT":
            self._next()
            name = self._next().value
            fn = self._function_rest(t, name)
            return ast.Let(name, fn, **self._pos(t))
        if self._is_kw("while"):
            self._next()
            cond = self.expression()
            return ast.While(cond, self.block(), **self._pos(t))
        if self._is_kw("for"):
            self._next()
            var = self._expect("IDENT", what="loop variable").value
            self._expect("KEYWORD", "in")
            iterable = self.expression()
            return ast.For(var, iterable, self.block(), **self._pos(t))
        if self._is_kw("return"):
            self._next()
            value = None
            if not (self._is_op(";") or self._is_op("}") or self._is("EOF")):
                value = self.expression()
            return ast.Return(value, **self._pos(t))
        if self._is_kw("break"):
            self._next()
            return ast.Break(**self._pos(t))
        if self._is_kw("continue"):
            self._next()
            return ast.Continue(**self._pos(t))
        return ast.ExprStmt(self.expression(), **self._pos(t))

    def block(self):
        self._expect("OP", "{")
        stmts = []
        self._skip_semis()
        while not self._is_op("}"):
            if self._is("EOF"):
                t = self.cur
                raise MiniSyntaxError("unclosed block, expected '}'", t.line, t.col)
            stmts.append(self.statement())
            self._skip_semis()
        self._next()
        return stmts

    # ---- expressions (Pratt loop) ----

    def expression(self, min_bp=0):
        left = self.prefix()
        while True:
            t = self.cur
            op = t.value if t.kind in ("OP", "KEYWORD") else None
            bp = PRECEDENCE.get(op)
            if bp is None or bp <= min_bp:
                break
            # A call or index must start on the same line as what it applies to,
            # otherwise "f()\n[1, 2]" would parse as "f()[1, 2]".
            if op in ("(", "[") and t.line != self.toks[self.i - 1].line:
                break
            left = self.infix(left, t)
        return left

    def prefix(self):
        t = self._next()
        pos = self._pos(t)
        if t.kind in ("NUMBER", "STRING"):
            return ast.Literal(t.value, **pos)
        if t.kind == "IDENT":
            return ast.Name(t.value, **pos)
        if t.kind == "KEYWORD":
            if t.value in ("true", "false"):
                return ast.Literal(t.value == "true", **pos)
            if t.value == "nil":
                return ast.Literal(None, **pos)
            if t.value == "not":
                return ast.Unary("not", self.expression(NOT_BP), **pos)
            if t.value == "fn":
                return self._function_rest(t, None)
            if t.value == "if":
                return self._if_rest(t)
        if t.kind == "OP":
            if t.value == "-":
                return ast.Unary("-", self.expression(NEG_BP), **pos)
            if t.value == "(":
                e = self.expression()
                self._expect("OP", ")")
                return e
            if t.value == "[":
                items = self._comma_list("]")
                return ast.ArrayLit(items, **pos)
            if t.value == "{":
                return self._map_rest(t)
        got = "end of input" if t.kind == "EOF" else repr(t.value)
        raise MiniSyntaxError(f"expected an expression, got {got}", t.line, t.col)

    def infix(self, left, t):
        op = t.value
        pos = self._pos(t)
        self._next()
        if op == "=":
            if not isinstance(left, (ast.Name, ast.Index)):
                raise MiniSyntaxError("invalid assignment target", t.line, t.col)
            # right-associative: parse with bp - 1
            return ast.Assign(left, self.expression(PRECEDENCE["="] - 1), **pos)
        if op == "(":
            return ast.Call(left, self._comma_list(")"), **pos)
        if op == "[":
            idx = self.expression()
            self._expect("OP", "]")
            return ast.Index(left, idx, **pos)
        if op == ".":
            key = self._expect("IDENT", what="property name")
            return ast.Index(left, ast.Literal(key.value, **self._pos(key)), **pos)
        if op == "|>":
            # x |> f(a, b)  ==>  f(x, a, b);   x |> f  ==>  f(x)
            right = self.expression(PRECEDENCE["|>"])
            if isinstance(right, ast.Call):
                return ast.Call(right.callee, [left] + right.args, **pos)
            return ast.Call(right, [left], **pos)
        if op in ("and", "or"):
            return ast.Logical(op, left, self.expression(PRECEDENCE[op]), **pos)
        return ast.Binary(op, left, self.expression(PRECEDENCE[op]), **pos)

    # ---- helpers for compound expressions ----

    def _comma_list(self, closer):
        items = []
        while not self._is_op(closer):
            items.append(self.expression())
            if not self._is_op(closer):
                self._expect("OP", ",", what=f"',' or '{closer}'")
        self._next()
        return items

    def _map_rest(self, open_tok):
        pairs = []
        while not self._is_op("}"):
            if self._is("IDENT"):  # {name: 1} shorthand for {"name": 1}
                k = self._next()
                key = ast.Literal(k.value, **self._pos(k))
            else:
                key = self.expression()
            self._expect("OP", ":")
            pairs.append((key, self.expression()))
            if not self._is_op("}"):
                self._expect("OP", ",", what="',' or '}'")
        self._next()
        return ast.MapLit(pairs, **self._pos(open_tok))

    def _function_rest(self, fn_tok, name):
        self._expect("OP", "(")
        params = []
        while not self._is_op(")"):
            p = self._expect("IDENT", what="parameter name")
            if p.value in params:
                raise MiniSyntaxError(f"duplicate parameter {p.value!r}", p.line, p.col)
            params.append(p.value)
            if not self._is_op(")"):
                self._expect("OP", ",", what="',' or ')'")
        self._next()
        if self._is_op("->"):
            arrow = self._next()
            body = [ast.ExprStmt(self.expression(), **self._pos(arrow))]
        else:
            body = self.block()
        return ast.Function(params, body, name, **self._pos(fn_tok))

    def _if_rest(self, if_tok):
        cond = self.expression()
        then = self.block()
        otherwise = None
        if self._is_kw("else"):
            else_tok = self._next()
            if self._is_kw("if"):
                nested = self._if_rest(self._next())
                otherwise = [ast.ExprStmt(nested, **self._pos(else_tok))]
            else:
                otherwise = self.block()
        return ast.IfExpr(cond, then, otherwise, **self._pos(if_tok))


def parse(source: str):
    return Parser(tokenize(source)).parse_program()
