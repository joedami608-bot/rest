"""Ember: a statically typed, type-inferred scripting language compiled to bytecode.

Pipeline:  source -> lexer -> parser -> AST -> type inference -> bytecode compiler -> VM
"""

import os

from . import syntax as ast
from .compiler import compile_program
from .errors import EmberError, RuntimeErr, SyntaxErr, TypeErr
from .parser import parse
from .typecheck import Checker
from .vm import VM

__all__ = ["compile_source", "run", "EmberError", "SyntaxErr", "TypeErr", "RuntimeErr"]

_PRELUDE_PATH = os.path.join(os.path.dirname(__file__), "prelude.em")
with open(_PRELUDE_PATH, encoding="utf-8") as _f:
    PRELUDE_SOURCE = _f.read()


def _mark_prelude(node):
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, ast.Lambda):
            n.from_prelude = True
        for v in vars(n).values():
            if isinstance(v, ast.Node):
                stack.append(v)
            elif isinstance(v, list):
                stack.extend(x for x in v if isinstance(x, ast.Node))


class Compiled:
    def __init__(self, main, global_names, checker, program):
        self.main = main
        self.global_names = global_names
        self.checker = checker
        self.program = program

    @property
    def warnings(self):
        return self.checker.warnings


def compile_source(source, use_prelude=True):
    """Parse, type-check and compile. Raises SyntaxErr / TypeErr."""
    prog = parse(source)
    if use_prelude:
        prelude = parse(PRELUDE_SOURCE)
        for f in prelude.fns:
            _mark_prelude(f)
        prog = ast.Program(prelude.types + prog.types, prelude.fns + prog.fns, prog.stmts)
    checker = Checker()
    checker.check_program(prog)
    main, global_names = compile_program(prog)
    return Compiled(main, global_names, checker, prog)


def run(source, output=print, use_prelude=True):
    """Compile and execute; returns the value of the last top-level expression."""
    compiled = compile_source(source, use_prelude)
    return VM(compiled.global_names, output).run(compiled.main)
