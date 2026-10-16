"""Human-readable bytecode listing (`python -m ember --dis file.em`)."""

from . import opcodes as op
from .runtime import Code, show


def disassemble(code, global_names, out=None, seen=None):
    out = [] if out is None else out
    seen = set() if seen is None else seen
    if id(code) in seen:
        return out
    seen.add(id(code))
    out.append(f"== {code.name}  (arity {code.arity}, {code.nlocals} locals, {code.nfree} free) ==")
    nested = []
    ip, last_line = 0, None
    while ip < len(code.code):
        o = code.code[ip]
        args = code.code[ip + 1: ip + 1 + op.OPERANDS[o]]
        line = code.lines[ip][0]
        line_col = f"{line:>4}" if line != last_line else "    "
        last_line = line
        note = ""
        if o in (op.CONST,):
            c = code.consts[args[0]]
            if isinstance(c, Code):
                nested.append(c)
                note = f"<code {c.name}>"
            else:
                note = show(c, True)
        elif o in (op.LOAD_GLOBAL, op.STORE_GLOBAL):
            note = global_names[args[0]]
        elif o == op.MAKE_DATA:
            note = code.consts[args[0]][1]
        elif o in (op.LOAD_LOCAL_CONST_ADD, op.LOAD_LOCAL_CONST_SUB, op.LOAD_LOCAL_CONST_LT):
            note = f"local {args[0]}, {show(code.consts[args[1]], True)}"
        elif o == op.CLOSURE:
            child = code.consts[args[0]]
            nested.append(child)
            pairs = code.code[ip + 3: ip + 3 + 2 * args[1]]
            caps = [("cell" if pairs[i] == 0 else "free") + f" {pairs[i + 1]}" for i in range(0, len(pairs), 2)]
            note = f"<code {child.name}>" + (f" capturing [{', '.join(caps)}]" if caps else "")
        elif o in op.JUMPS:
            note = f"-> {args[0]}"
        operands = " ".join(str(a) for a in args)
        out.append(f"{line_col} {ip:>5}  {op.NAMES[o]:<22}{operands:<8}{('; ' + note) if note else ''}")
        ip += op.instr_len(code.code, ip)
    out.append("")
    for child in nested:
        disassemble(child, global_names, out, seen)
    return out
