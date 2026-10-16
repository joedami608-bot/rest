"""Mini: a small dynamically-typed scripting language implemented in pure Python."""

import sys
import threading

from .errors import MiniError, MiniRuntimeError, MiniSyntaxError
from .interpreter import Interpreter, show
from .parser import parse

__all__ = ["run", "parse", "Interpreter", "MiniError", "MiniSyntaxError", "MiniRuntimeError", "show"]


def with_big_stack(fn, *args):
    """Run fn on a thread with a large C stack so deep Mini recursion doesn't crash CPython."""
    result, error = [], []

    def target():
        try:
            result.append(fn(*args))
        except BaseException as e:  # re-raised on the calling thread
            error.append(e)

    old_limit = sys.getrecursionlimit()
    old_size = threading.stack_size(256 * 1024 * 1024)
    sys.setrecursionlimit(max(old_limit, 100_000))
    try:
        t = threading.Thread(target=target)
        t.start()
        t.join()
    finally:
        threading.stack_size(old_size)
        sys.setrecursionlimit(old_limit)
    if error:
        raise error[0]
    return result[0]


def run(source, output=print, interpreter=None):
    """Parse and execute `source`; return the value of the last statement."""
    interp = interpreter or Interpreter(output=output)
    return with_big_stack(interp.run, parse(source))
