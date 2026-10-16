"""Stack-based virtual machine.

All Ember calls use an explicit frame stack, so recursion depth is not limited
by the Python stack, and tail calls reuse the current frame.

Stack layout of a frame:   ... callee | local 0 .. local n-1 | temporaries
                                       ^ base

Dispatch: Python has no computed goto, and a 50-way if/elif chain costs ~20
comparisons for the ops near the end. Instead, each opcode's handler is written
below as a small source snippet, and `_build_dispatch` generates (at import time)
a loop whose dispatch is a balanced binary tree of `if o < N` tests, so every
opcode is reached in ~6 comparisons.
"""

import textwrap

from . import opcodes as op
from .errors import RuntimeErr
from .runtime import Cell, Closure, CtorFn, Data, Native, make_natives, values_equal

MAX_FRAMES = 200_000

_CALL = """
argc = code[ip + 1]
callee = stack[-argc - 1]
if type(callee) is Closure:
    callee_code = callee.code
    if o == TAIL_CALL and frames:
        # Reuse this frame: slide callee + args down over the current one.
        stack[base - 1:base + argc] = stack[len(stack) - argc - 1:]
        del stack[base + argc:]
    else:
        if len(frames) >= MAX_FRAMES:
            raise RuntimeErr(f"stack overflow ({MAX_FRAMES} nested calls)")
        frames.append((fn_code, ip + 2, base, cells))
        base = len(stack) - argc
    extra = callee_code.nlocals - argc
    if extra:
        stack.extend([None] * extra)
    fn_code = callee_code
    code, consts, cells = callee_code.code, callee_code.consts, callee.cells
    ip = 0
else:
    args = stack[len(stack) - argc:]
    del stack[len(stack) - argc - 1:]
    if type(callee) is Native:
        result = callee.fn(*args)
    else:  # CtorFn
        result = Data(callee.tag, callee.name, args)
    push(result)
    if o == TAIL_CALL and frames:  # behave like CALL followed by RETURN
        result = pop()
        del stack[base - 1:]
        push(result)
        fn_code, ip, base, cells = frames.pop()
        code, consts = fn_code.code, fn_code.consts
    else:
        ip += 2
"""

_HANDLERS = {
    "CONST": "push(consts[code[ip + 1]]); ip += 2",
    "UNIT": "push(None); ip += 1",
    "NIL": "push(()); ip += 1",
    "LOAD_LOCAL": "push(stack[base + code[ip + 1]]); ip += 2",
    "STORE_LOCAL": "stack[base + code[ip + 1]] = pop(); ip += 2",
    "LOAD_CELL": "push(stack[base + code[ip + 1]].value); ip += 2",
    "STORE_CELL": "stack[base + code[ip + 1]].value = pop(); ip += 2",
    "MAKE_CELL": "slot = base + code[ip + 1]; stack[slot] = Cell(stack[slot]); ip += 2",
    "NEW_CELL": "stack[base + code[ip + 1]] = Cell(); ip += 2",
    "STORE_NEW_CELL": "stack[base + code[ip + 1]] = Cell(pop()); ip += 2",
    "LOAD_FREE": "push(cells[code[ip + 1]].value); ip += 2",
    "STORE_FREE": "cells[code[ip + 1]].value = pop(); ip += 2",
    "LOAD_GLOBAL": "push(g[code[ip + 1]]); ip += 2",
    "STORE_GLOBAL": "g[code[ip + 1]] = pop(); ip += 2",
    "ADD": "b = pop(); stack[-1] += b; ip += 1",
    "SUB": "b = pop(); stack[-1] -= b; ip += 1",
    "MUL": "b = pop(); stack[-1] *= b; ip += 1",
    "DIV": """
        b = pop()
        if b == 0:
            raise RuntimeErr("division by zero")
        stack[-1] //= b; ip += 1
    """,
    "MOD": """
        b = pop()
        if b == 0:
            raise RuntimeErr("division by zero")
        stack[-1] %= b; ip += 1
    """,
    "NEG": "stack[-1] = -stack[-1]; ip += 1",
    "NOT": "stack[-1] = not stack[-1]; ip += 1",
    "CONCAT": "b = pop(); stack[-1] += b; ip += 1",
    "EQ": """
        b = pop(); a = stack[-1]
        stack[-1] = a == b if type(a) is int or type(a) is str else values_equal(a, b)
        ip += 1
    """,
    "NE": """
        b = pop(); a = stack[-1]
        stack[-1] = a != b if type(a) is int or type(a) is str else not values_equal(a, b)
        ip += 1
    """,
    "LT": "b = pop(); stack[-1] = stack[-1] < b; ip += 1",
    "LE": "b = pop(); stack[-1] = stack[-1] <= b; ip += 1",
    "GT": "b = pop(); stack[-1] = stack[-1] > b; ip += 1",
    "GE": "b = pop(); stack[-1] = stack[-1] >= b; ip += 1",
    "CONS": "b = pop(); stack[-1] = (stack[-1], b); ip += 1",
    "LIST": """
        out = ()
        for _ in range(code[ip + 1]):
            out = (pop(), out)
        push(out); ip += 2
    """,
    "IS_NIL": "stack[-1] = not stack[-1]; ip += 1",
    "HEAD": "stack[-1] = stack[-1][0]; ip += 1",
    "TAIL": "stack[-1] = stack[-1][1]; ip += 1",
    "MAKE_DATA": """
        tag, name = consts[code[ip + 1]]
        n = code[ip + 2]
        if n:
            fields = stack[-n:]
            del stack[-n:]
        else:
            fields = []
        push(Data(tag, name, fields)); ip += 3
    """,
    "TAG_EQ": "stack[-1] = stack[-1].tag == code[ip + 1]; ip += 2",
    "FIELD": "stack[-1] = stack[-1].fields[code[ip + 1]]; ip += 2",
    "JUMP": "ip = code[ip + 1]",
    "JUMP_IF_FALSE": "ip = ip + 2 if pop() else code[ip + 1]",
    "JUMP_IF_TRUE": "ip = code[ip + 1] if pop() else ip + 2",
    "JUMP_IF_FALSE_OR_POP": """
        if stack[-1]:
            pop(); ip += 2
        else:
            ip = code[ip + 1]
    """,
    "JUMP_IF_TRUE_OR_POP": """
        if stack[-1]:
            ip = code[ip + 1]
        else:
            pop(); ip += 2
    """,
    "CLOSURE": """
        n = code[ip + 2]
        p = ip + 3
        captured = []
        for _ in range(n):
            idx = code[p + 1]
            captured.append(stack[base + idx] if code[p] == 0 else cells[idx])
            p += 2
        push(Closure(consts[code[ip + 1]], captured)); ip = p
    """,
    "CALL": _CALL,
    "TAIL_CALL": _CALL,
    "RETURN": """
        result = pop()
        if not frames:
            return result
        del stack[base - 1:]
        push(result)
        fn_code, ip, base, cells = frames.pop()
        code, consts = fn_code.code, fn_code.consts
    """,
    "POP": "pop(); ip += 1",
    "MATCH_FAIL": 'raise RuntimeErr("no match arm matched")',
    "LOAD_LOCAL_CONST_ADD": "push(stack[base + code[ip + 1]] + consts[code[ip + 2]]); ip += 3",
    "LOAD_LOCAL_CONST_SUB": "push(stack[base + code[ip + 1]] - consts[code[ip + 2]]); ip += 3",
    "LOAD_LOCAL_CONST_LT": "push(stack[base + code[ip + 1]] < consts[code[ip + 2]]); ip += 3",
    "LOAD_LOCAL2": "push(stack[base + code[ip + 1]]); push(stack[base + code[ip + 2]]); ip += 3",
}

assert set(_HANDLERS) == set(op.NAMES), set(op.NAMES) ^ set(_HANDLERS)


def _dispatch_tree(lo, hi, indent):
    """Source for a binary search over opcodes lo..hi-1."""
    pad = " " * indent
    if hi - lo == 1:
        body = textwrap.dedent(_HANDLERS[op.NAMES[lo]]).strip()
        return textwrap.indent(body, pad) + "\n"
    mid = (lo + hi) // 2
    return (f"{pad}if o < {mid}:\n" + _dispatch_tree(lo, mid, indent + 4)
            + f"{pad}else:\n" + _dispatch_tree(mid, hi, indent + 4))


def _build_dispatch():
    tree = _dispatch_tree(0, len(op.NAMES), 16)
    src = f'''
def execute(vm, main):
    g = vm.globals
    stack = [None] * main.nlocals
    push = stack.append
    pop = stack.pop
    frames = []
    fn_code = main
    code, consts, cells = main.code, main.consts, ()
    ip, base = 0, 0
    TAIL_CALL = {op.TAIL_CALL}
    try:
        while True:
            o = code[ip]
            if True:
{tree}
    except RuntimeErr as e:
        vm.locate(e, fn_code, ip, frames)
        raise
'''
    namespace = {"Cell": Cell, "Closure": Closure, "CtorFn": CtorFn, "Data": Data, "Native": Native,
                 "RuntimeErr": RuntimeErr, "values_equal": values_equal, "MAX_FRAMES": MAX_FRAMES}
    exec(compile(src, "<ember-vm-dispatch>", "exec"), namespace)
    return namespace["execute"], src


_execute, DISPATCH_SOURCE = _build_dispatch()


class VM:
    def __init__(self, global_names, output=print):
        natives = make_natives(output)
        self.globals = [Native(n, natives[n]) if n in natives else None for n in global_names]

    def run(self, main):
        try:
            return _execute(self, main)
        except RecursionError:
            raise RuntimeErr("value too deeply nested")

    @staticmethod
    def locate(err, fn_code, ip, frames):
        """Attach the source line (of the innermost user code) and an Ember-level stack trace."""
        chain = [(fn_code, ip)] + [(c, ret_ip - 2) for c, ret_ip, _, _ in reversed(frames)]
        if err.line is None:
            for c, at in chain:
                if not c.prelude:
                    err.line, err.col = c.lines[min(at, len(c.lines) - 1)]
                    break
        trace = []
        for c, at in chain[:12]:
            where = "prelude" if c.prelude else "line"
            trace.append(f"in {c.name} ({where} {c.lines[min(at, len(c.lines) - 1)][0]})")
        if len(chain) > 12:
            trace.append(f"... {len(chain) - 12} more frames")
        err.notes.extend(trace)
