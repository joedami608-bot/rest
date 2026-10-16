"""Command line: `python -m mini file.mini` runs a script, `python -m mini` starts a REPL."""

import sys

from . import Interpreter, MiniError, run, show


def repl():
    interp = Interpreter()
    print("Mini REPL — Ctrl-D to exit")
    buffer = []
    while True:
        try:
            line = input("... " if buffer else ">>> ")
        except EOFError:
            print()
            return
        buffer.append(line)
        source = "\n".join(buffer)
        # Keep reading while brackets are unbalanced (multi-line input).
        if sum(source.count(o) - source.count(c) for o, c in ("{}", "()", "[]")) > 0:
            continue
        buffer = []
        try:
            value = run(source, interpreter=interp)
            if value is not None:
                print(show(value, nested=True))
        except MiniError as e:
            print(e.render(source))


def main(argv):
    if len(argv) < 2:
        repl()
        return 0
    path = argv[1]
    with open(path, encoding="utf-8") as f:
        source = f.read()
    try:
        run(source)
    except BrokenPipeError:  # e.g. piped into `head`
        sys.stderr.close()
        return 0
    except MiniError as e:
        print(f"{path}: {e.render(source)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
