"""Recursive-descent parser with Pratt expression parsing.

    program  := (typedecl | fndecl | stmt)*
    typedecl := "type" UPPER ("[" IDENT,* "]")? "=" "|"? ctor ("|" ctor)*
    ctor     := UPPER ("(" type,* ")")?
    fndecl   := "fn" IDENT "(" param,* ")" ("->" type)? ("=" expr | block)
    stmt     := "let" IDENT (":" type)? "=" expr | "var" ... | IDENT "=" expr
              | "while" expr block | fndecl | expr
    expr     := Pratt over PRECEDENCE; prefix forms: literals, names, (expr), [list],
                block, if, match, fn(...) => expr, -e, not e
"""

from . import syntax as ast
from .errors import SyntaxErr
from .lexer import tokenize

PRECEDENCE = {
    "|>": 1, "or": 2, "and": 3,
    "==": 4, "!=": 4, "<": 5, "<=": 5, ">": 5, ">=": 5,
    "::": 6, "++": 7, "+": 8, "-": 8, "*": 9, "/": 9, "%": 9,
    "(": 11,
}
RIGHT_ASSOC = {"::"}
NEG_BP = 10
NOT_BP = 3  # `not a == b` is `not (a == b)`


class Parser:
    def __init__(self, src):
        self.toks = tokenize(src)
        self.i = 0

    # ---- token helpers ----

    @property
    def cur(self):
        return self.toks[self.i]

    def at(self, kind, value=None, offset=0):
        t = self.toks[min(self.i + offset, len(self.toks) - 1)]
        return t.kind == kind and (value is None or t.value == value)

    def at_op(self, value):
        return self.at("OP", value)

    def advance(self):
        t = self.cur
        if t.kind != "EOF":
            self.i += 1
        return t

    def accept_op(self, value):
        if self.at_op(value):
            return self.advance()
        return None

    def expect(self, kind, value=None, what=None):
        if not self.at(kind, value):
            t = self.cur
            want = what or (f"'{value}'" if value is not None else kind.lower())
            got = "end of input" if t.kind == "EOF" else f"'{t.value}'"
            raise SyntaxErr(f"expected {want}, found {got}", t.line, t.col)
        return self.advance()

    @staticmethod
    def pos(t):
        return {"line": t.line, "col": t.col}

    def skip_semis(self):
        while self.accept_op(";"):
            pass

    def comma_list(self, item, close):
        items = []
        while not self.at_op(close):
            items.append(item())
            if not self.accept_op(","):
                break
        self.expect("OP", close, f"',' or '{close}'")
        return items

    # ---- program ----

    def program(self):
        types, fns, stmts = [], [], []
        self.skip_semis()
        while not self.at("EOF"):
            if self.at("KEYWORD", "type"):
                types.append(self.type_decl())
            elif self.at("KEYWORD", "fn") and self.at("IDENT", offset=1):
                fns.append(self.fn_decl())
            else:
                stmts.append(self.statement())
            self.skip_semis()
        return ast.Program(types, fns, stmts, line=1, col=1)

    def type_decl(self):
        t = self.advance()
        name = self.expect("UPPER", what="type name").value
        params = []
        if self.accept_op("["):
            params = [p.value for p in self.comma_list(lambda: self.expect("IDENT", what="type parameter"), "]")]
        self.expect("OP", "=")
        self.accept_op("|")
        ctors = [self.ctor_decl()]
        while self.accept_op("|"):
            ctors.append(self.ctor_decl())
        return ast.TypeDecl(name, params, ctors, **self.pos(t))

    def ctor_decl(self):
        t = self.expect("UPPER", what="constructor name")
        fields = self.comma_list(self.type_expr, ")") if self.accept_op("(") else []
        return ast.CtorDecl(t.value, fields, **self.pos(t))

    def fn_decl(self):
        t = self.advance()
        name = self.advance().value
        return ast.FnDecl(name, self.fn_rest(t, name), **self.pos(t))

    def fn_rest(self, t, name):
        self.expect("OP", "(")
        params = self.comma_list(self.param, ")")
        seen = set()
        for p in params:
            if p.name in seen:
                raise SyntaxErr(f"duplicate parameter '{p.name}'", p.line, p.col)
            seen.add(p.name)
        ret = self.type_expr() if self.accept_op("->") else None
        if self.accept_op("=") or self.accept_op("=>"):
            body = self.expression()
        else:
            body = self.block()
        return ast.Lambda(params, ret, body, name, **self.pos(t))

    def param(self):
        t = self.expect("IDENT", what="parameter name")
        ann = self.type_expr() if self.accept_op(":") else None
        return ast.Param(t.value, ann, **self.pos(t))

    # ---- type expressions ----

    def type_expr(self):
        t = self.cur
        if self.accept_op("("):
            params = self.comma_list(self.type_expr, ")")
            self.expect("OP", "->", "'->' in function type")
            return ast.TFunc(params, self.type_expr(), **self.pos(t))
        if self.at("UPPER"):
            self.advance()
            args = self.comma_list(self.type_expr, "]") if self.accept_op("[") else []
            return ast.TName(t.value, args, **self.pos(t))
        if self.at("IDENT"):
            self.advance()
            return ast.TVarName(t.value, **self.pos(t))
        raise SyntaxErr("expected a type", t.line, t.col)

    # ---- statements ----

    def statement(self):
        t = self.cur
        if self.at("KEYWORD", "let") or self.at("KEYWORD", "var"):
            mutable = self.advance().value == "var"
            name = self.expect("IDENT", what="variable name").value
            ann = self.type_expr() if self.accept_op(":") else None
            self.expect("OP", "=")
            return ast.Let(name, ann, self.expression(), mutable, **self.pos(t))
        if self.at("KEYWORD", "fn") and self.at("IDENT", offset=1):
            return self.fn_decl()
        if self.at("KEYWORD", "while"):
            self.advance()
            cond = self.expression()
            return ast.While(cond, self.block(), **self.pos(t))
        if self.at("IDENT") and self.at("OP", "=", offset=1):
            name = self.advance().value
            self.advance()
            return ast.Assign(name, self.expression(), **self.pos(t))
        return ast.ExprStmt(self.expression(), **self.pos(t))

    def block(self):
        t = self.expect("OP", "{")
        stmts = []
        self.skip_semis()
        while not self.at_op("}"):
            if self.at("EOF"):
                raise SyntaxErr("unclosed '{'", t.line, t.col)
            if self.at("KEYWORD", "type"):
                c = self.cur
                raise SyntaxErr("type declarations are only allowed at the top level", c.line, c.col)
            stmts.append(self.statement())
            self.skip_semis()
        self.advance()
        return ast.Block(stmts, **self.pos(t))

    # ---- expressions ----

    def expression(self, min_bp=0):
        left = self.prefix()
        while True:
            t = self.cur
            op = t.value if t.kind in ("OP", "KEYWORD") else None
            bp = PRECEDENCE.get(op)
            if bp is None or bp <= min_bp:
                break
            # A call must start on the same line: `f()\n(x)` is two statements.
            if op == "(" and t.line != self.toks[self.i - 1].line:
                break
            self.advance()
            pos = self.pos(t)
            if op == "(":
                left = ast.Call(left, self.comma_list(self.expression, ")"), **pos)
            elif op == "|>":
                # x |> f(a)  ==>  f(x, a)      x |> f  ==>  f(x)
                right = self.expression(bp)
                if isinstance(right, ast.Call):
                    left = ast.Call(right.fn, [left] + right.args, **pos)
                else:
                    left = ast.Call(right, [left], **pos)
            else:
                right = self.expression(bp - 1 if op in RIGHT_ASSOC else bp)
                left = ast.BinOp(op, left, right, **pos)
        return left

    def prefix(self):
        t = self.advance()
        pos = self.pos(t)
        k, v = t.kind, t.value
        if k == "INT":
            return ast.Lit(v, **pos)
        if k == "STRING":
            return ast.Lit(v, **pos)
        if k == "IDENT":
            if v == "_":
                raise SyntaxErr("'_' is only allowed in patterns", t.line, t.col)
            return ast.Var(v, **pos)
        if k == "UPPER":
            return ast.Ctor(v, **pos)
        if k == "KEYWORD":
            if v in ("true", "false"):
                return ast.Lit(v == "true", **pos)
            if v == "not":
                return ast.Unary("not", self.expression(NOT_BP), **pos)
            if v == "if":
                return self.if_rest(t)
            if v == "match":
                return self.match_rest(t)
            if v == "fn":
                return self.fn_rest(t, "<lambda>")
        if k == "OP":
            if v == "-":
                return ast.Unary("-", self.expression(NEG_BP), **pos)
            if v == "(":
                if self.accept_op(")"):
                    return ast.Lit(None, **pos)
                e = self.expression()
                self.expect("OP", ")")
                return e
            if v == "[":
                return ast.ListLit(self.comma_list(self.expression, "]"), **pos)
            if v == "{":
                self.i -= 1
                return self.block()
        got = "end of input" if k == "EOF" else f"'{v}'"
        raise SyntaxErr(f"expected an expression, found {got}", t.line, t.col)

    def if_rest(self, t):
        cond = self.expression()
        then = self.block()
        else_ = None
        if self.at("KEYWORD", "else"):
            self.advance()
            if self.at("KEYWORD", "if"):
                else_ = self.if_rest(self.advance())
            else:
                else_ = self.block()
        return ast.If(cond, then, else_, **self.pos(t))

    def match_rest(self, t):
        scrutinee = self.expression()
        open_ = self.expect("OP", "{")
        arms = []
        while True:
            while self.accept_op(",") or self.accept_op(";"):
                pass
            if self.accept_op("}"):
                break
            if self.at("EOF"):
                raise SyntaxErr("unclosed match", open_.line, open_.col)
            p = self.cur
            pat = self.pattern()
            self.expect("OP", "=>")
            arms.append(ast.Arm(pat, self.expression(), **self.pos(p)))
        if not arms:
            raise SyntaxErr("match needs at least one arm", t.line, t.col)
        return ast.Match(scrutinee, arms, **self.pos(t))

    # ---- patterns ----

    def pattern(self):
        head = self.pattern_atom()
        if self.at_op("::"):
            t = self.advance()
            return ast.PCons(head, self.pattern(), **self.pos(t))
        return head

    def pattern_atom(self):
        t = self.advance()
        pos = self.pos(t)
        k, v = t.kind, t.value
        if k == "IDENT":
            return ast.PWild(**pos) if v == "_" else ast.PVar(v, **pos)
        if k in ("INT", "STRING"):
            return ast.PLit(v, **pos)
        if k == "KEYWORD" and v in ("true", "false"):
            return ast.PLit(v == "true", **pos)
        if k == "UPPER":
            args = self.comma_list(self.pattern, ")") if self.accept_op("(") else []
            return ast.PCtor(v, args, **pos)
        if k == "OP":
            if v == "-" and self.at("INT"):
                return ast.PLit(-self.advance().value, **pos)
            if v == "(":
                if self.accept_op(")"):
                    return ast.PLit(None, **pos)
                p = self.pattern()
                self.expect("OP", ")")
                return p
            if v == "[":
                items = self.comma_list(self.pattern, "]")
                result = ast.PNil(**pos)
                for item in reversed(items):
                    result = ast.PCons(item, result, line=item.line, col=item.col)
                return result
        got = "end of input" if k == "EOF" else f"'{v}'"
        raise SyntaxErr(f"expected a pattern, found {got}", t.line, t.col)


def parse(src):
    return Parser(src).program()
