"""Command line.

    python -m ember FILE.em            compile and run
    python -m ember --types FILE.em    print the inferred type of every top-level definition
    python -m ember --dis FILE.em      print the bytecode
    python -m ember -e 'CODE'          run a snippet
"""

import argparse
import sys

from . import EmberError, compile_source
from .disasm import disassemble
from .typecheck import show_scheme
from .vm import VM


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ember", description="Run Ember programs.")
    ap.add_argument("file", nargs="?", help="source file (.em)")
    ap.add_argument("-e", dest="code", help="run this code instead of a file")
    ap.add_argument("--types", action="store_true", help="show inferred types and exit")
    ap.add_argument("--dis", action="store_true", help="show bytecode and exit")
    args = ap.parse_args(argv)

    if args.code is not None:
        name, source = "<-e>", args.code
    elif args.file:
        name = args.file
        with open(args.file, encoding="utf-8") as f:
            source = f.read()
    else:
        ap.print_usage(sys.stderr)
        return 2

    try:
        compiled = compile_source(source)
        for w in compiled.warnings:
            print(f"{name}: {w.render(source)}", file=sys.stderr)
        if args.types:
            user_fns = [f for f in compiled.program.fns if not getattr(f.fn, "from_prelude", False)]
            for f in user_fns:
                print(f"fn {f.name} : {show_scheme(compiled.checker.fn_schemes[f.name])}")
            for s in compiled.program.stmts:
                if hasattr(s, "scheme"):
                    kw = "var" if getattr(s, "mutable", False) else "let"
                    print(f"{kw} {s.name} : {show_scheme(s.scheme)}")
            return 0
        if args.dis:
            print("\n".join(disassemble(compiled.main, compiled.global_names)))
            return 0
        VM(compiled.global_names).run(compiled.main)
    except EmberError as e:
        print(f"{name}: {e.render(source)}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        sys.stderr.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
