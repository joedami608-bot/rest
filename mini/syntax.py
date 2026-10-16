"""AST node definitions. Every node remembers where it came from."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Node:
    line: int = field(default=0, kw_only=True, compare=False)
    col: int = field(default=0, kw_only=True, compare=False)


# ---- expressions ----

@dataclass
class Literal(Node):
    value: object


@dataclass
class Name(Node):
    name: str


@dataclass
class ArrayLit(Node):
    items: list


@dataclass
class MapLit(Node):
    pairs: list  # list of (key_expr, value_expr)


@dataclass
class Unary(Node):
    op: str
    operand: Node


@dataclass
class Binary(Node):
    op: str
    left: Node
    right: Node


@dataclass
class Logical(Node):
    op: str  # "and" / "or" — short-circuiting
    left: Node
    right: Node


@dataclass
class Assign(Node):
    target: Node  # Name or Index
    value: Node


@dataclass
class Call(Node):
    callee: Node
    args: list


@dataclass
class Index(Node):
    obj: Node
    index: Node


@dataclass
class Function(Node):
    params: list
    body: list
    name: Optional[str] = None


@dataclass
class IfExpr(Node):
    cond: Node
    then: list
    otherwise: Optional[list]


# ---- statements ----

@dataclass
class Let(Node):
    name: str
    value: Node


@dataclass
class ExprStmt(Node):
    expr: Node


@dataclass
class While(Node):
    cond: Node
    body: list


@dataclass
class For(Node):
    var: str
    iterable: Node
    body: list


@dataclass
class Return(Node):
    value: Optional[Node]


@dataclass
class Break(Node):
    pass


@dataclass
class Continue(Node):
    pass
