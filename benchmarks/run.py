"""Compare Mini (tree-walking interpreter) with Ember (bytecode VM) on the same programs.

    python3 benchmarks/run.py
"""

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROGRAMS = {
    "fib(25), recursive calls": (
        "fn fib(n) { if n < 2 { n } else { fib(n - 1) + fib(n - 2) } }\nprint(fib(25))",
        "fn fib(n) = if n < 2 { n } else { fib(n - 1) + fib(n - 2) }\nprint(fib(25))",
    ),
    "while loop, 1M iterations": (
        "fn run() { let i = 0; let s = 0; while i < 1000000 { s = s + i * 2; i = i + 1 }; s }\nprint(run())",
        "fn run() { var i = 0; var s = 0; while i < 1000000 { s = s + i * 2; i = i + 1 }; s }\nprint(run())",
    ),
    "build + sum a 200k list": (
        "print(reduce(map(range(0, 200000), fn(x) -> x * 2), fn(a, b) -> a + b, 0))",
        "print(range(0, 200000) |> map(fn(x) => x * 2) |> sum)",
    ),
}


def timed(lang, code):
    best, output = None, None
    for _ in range(3):
        start = time.perf_counter()
        r = subprocess.run([sys.executable, "-m", lang, "-e" if lang == "ember" else "/dev/stdin"]
                           + ([code] if lang == "ember" else []),
                           input=None if lang == "ember" else code,
                           cwd=ROOT, capture_output=True, text=True, check=True)
        elapsed = time.perf_counter() - start
        best = elapsed if best is None else min(best, elapsed)
        output = r.stdout.strip()
    return best, output


def main():
    print(f"{'benchmark':<28}{'Mini':>9}{'Ember':>9}{'speedup':>9}")
    for name, (mini_src, ember_src) in PROGRAMS.items():
        tm, om = timed("mini", mini_src)
        te, oe = timed("ember", ember_src)
        assert om == oe, (name, om, oe)
        print(f"{name:<28}{tm:>8.2f}s{te:>8.2f}s{tm / te:>8.1f}x")
    print("(best of 3 runs, including interpreter start-up)")


if __name__ == "__main__":
    main()
