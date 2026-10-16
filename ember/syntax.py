"""Syntax tree. Later phases attach extra attributes (e.g. `.ty`, `.var`) to nodes."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass(eq=False)
class Node:
    line: int = field(default=0, kw_only=True)
    col: int = field(default=0, kw_only=True)


# ---------------------------------------------------------------- type syntax

@dataclass(eq=False)
class TName(Node):      # Int, List[a], Option[Int]
    name: str
    args: list


@dataclass(eq=False)
class TVarName(Node):   # a, b, elem
    name: str


@dataclass(eq=False)
class TFunc(Node):      # (Int, a) -> Bool
    params: list
    ret: Node


# ---------------------------------------------------------------- patterns

@dataclass(eq=False)
class PWild(Node):
    pass


@dataclass(eq=False)
class PVar(Node):
    name: str


@dataclass(eq=False)
class PLit(Node):       # int, string, bool or unit (value None)
    value: object


@dataclass(eq=False)
class PNil(Node):
    pass


@dataclass(eq=False)
class PCons(Node):
    head: Node
    tail: Node


@dataclass(eq=False)
class PCtor(Node):
    name: str
    args: list


# ---------------------------------------------------------------- expressions

@dataclass(eq=False)
class Lit(Node):        # Int, String, Bool, Unit (None)
    value: object


@dataclass(eq=False)
class Var(Node):
    name: str


@dataclass(eq=False)
class Ctor(Node):
    name: str


@dataclass(eq=False)
class ListLit(Node):
    items: list


@dataclass(eq=False)
class Param(Node):
    name: str
    ann: Optional[Node]


@dataclass(eq=False)
class Lambda(Node):
    params: list        # [Param]
    ret_ann: Optional[Node]
    body: Node
    name: str = "<lambda>"


@dataclass(eq=False)
class Call(Node):
    fn: Node
    args: list


@dataclass(eq=False)
class BinOp(Node):
    op: str
    left: Node
    right: Node


@dataclass(eq=False)
class Unary(Node):
    op: str
    operand: Node


@dataclass(eq=False)
class If(Node):
    cond: Node
    then: Node
    else_: Optional[Node]


@dataclass(eq=False)
class Arm(Node):
    pat: Node
    body: Node


@dataclass(eq=False)
class Match(Node):
    scrutinee: Node
    arms: list


@dataclass(eq=False)
class Block(Node):
    stmts: list         # value is the last statement if it's an ExprStmt, else Unit


# ---------------------------------------------------------------- statements / declarations

@dataclass(eq=False)
class Let(Node):
    name: str
    ann: Optional[Node]
    value: Node
    mutable: bool


@dataclass(eq=False)
class Assign(Node):
    name: str
    value: Node


@dataclass(eq=False)
class While(Node):
    cond: Node
    body: Block


@dataclass(eq=False)
class ExprStmt(Node):
    expr: Node


@dataclass(eq=False)
class FnDecl(Node):
    name: str
    fn: Lambda


@dataclass(eq=False)
class CtorDecl(Node):
    name: str
    fields: list        # type syntax nodes


@dataclass(eq=False)
class TypeDecl(Node):
    name: str
    params: list        # type variable names
    ctors: list         # [CtorDecl]


@dataclass(eq=False)
class Program(Node):
    types: list         # [TypeDecl]
    fns: list           # [FnDecl] — hoisted, may be mutually recursive
    stmts: list         # top-level statements, run in order
