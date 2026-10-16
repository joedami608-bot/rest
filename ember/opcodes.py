"""Instruction set. Code is a flat list of ints: opcode followed by its operands."""

# (name, operand count) — the index in this list is the opcode number.
_SPEC = [
    ("CONST", 1), ("UNIT", 0), ("NIL", 0),
    ("LOAD_LOCAL", 1), ("STORE_LOCAL", 1),
    ("LOAD_CELL", 1), ("STORE_CELL", 1), ("MAKE_CELL", 1), ("NEW_CELL", 1), ("STORE_NEW_CELL", 1),
    ("LOAD_FREE", 1), ("STORE_FREE", 1),
    ("LOAD_GLOBAL", 1), ("STORE_GLOBAL", 1),
    ("ADD", 0), ("SUB", 0), ("MUL", 0), ("DIV", 0), ("MOD", 0), ("NEG", 0), ("NOT", 0),
    ("CONCAT", 0), ("EQ", 0), ("NE", 0), ("LT", 0), ("LE", 0), ("GT", 0), ("GE", 0),
    ("CONS", 0), ("LIST", 1), ("IS_NIL", 0), ("HEAD", 0), ("TAIL", 0),
    ("MAKE_DATA", 2), ("TAG_EQ", 1), ("FIELD", 1),
    ("JUMP", 1), ("JUMP_IF_FALSE", 1), ("JUMP_IF_TRUE", 1),
    ("JUMP_IF_FALSE_OR_POP", 1), ("JUMP_IF_TRUE_OR_POP", 1),
    ("CLOSURE", 2),  # const index, n captures; followed by n (kind, index) pairs
    ("CALL", 1), ("TAIL_CALL", 1), ("RETURN", 0), ("POP", 0), ("MATCH_FAIL", 0),
    # superinstructions emitted by the peephole pass
    ("LOAD_LOCAL_CONST_ADD", 2), ("LOAD_LOCAL_CONST_SUB", 2), ("LOAD_LOCAL_CONST_LT", 2),
    ("LOAD_LOCAL2", 2),
]

NAMES = [name for name, _ in _SPEC]
OPERANDS = [n for _, n in _SPEC]
for _i, (_name, _) in enumerate(_SPEC):
    globals()[_name] = _i

JUMPS = {JUMP, JUMP_IF_FALSE, JUMP_IF_TRUE, JUMP_IF_FALSE_OR_POP, JUMP_IF_TRUE_OR_POP}  # noqa: F821


def instr_len(code, ip):
    op = code[ip]
    n = 1 + OPERANDS[op]
    if op == CLOSURE:  # noqa: F821
        n += 2 * code[ip + 2]
    return n
