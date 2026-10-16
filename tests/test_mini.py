import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mini import MiniRuntimeError, MiniSyntaxError, parse, run  # noqa: E402
from mini.lexer import tokenize  # noqa: E402


def ev(src):
    return run(src, output=lambda _: None)


def captured(src):
    lines = []
    run(src, output=lines.append)
    return lines


class LexerTests(unittest.TestCase):
    def test_range_is_not_a_float(self):
        kinds = [(t.kind, t.value) for t in tokenize("1..5 2.5")][:-1]
        self.assertEqual(kinds, [("NUMBER", 1), ("OP", ".."), ("NUMBER", 5), ("NUMBER", 2.5)])

    def test_positions_and_comments(self):
        toks = tokenize("# comment\n  let x")
        self.assertEqual((toks[0].line, toks[0].col), (2, 3))
        self.assertEqual((toks[1].line, toks[1].col), (2, 7))

    def test_string_escapes(self):
        self.assertEqual(tokenize(r'"a\n\"b\""')[0].value, 'a\n"b"')

    def test_unterminated_string(self):
        with self.assertRaises(MiniSyntaxError):
            tokenize('"oops')


class ParserTests(unittest.TestCase):
    def test_precedence(self):
        self.assertEqual(ev("1 + 2 * 3 - 4 / 2"), 5)
        self.assertEqual(ev("(1 + 2) * 3"), 9)
        self.assertEqual(ev("-2 * 3"), -6)
        self.assertIs(ev("1 < 2 and 3 > 4 or true"), True)
        self.assertIs(ev("not 1 == 2"), True)

    def test_left_associative_subtraction(self):
        self.assertEqual(ev("10 - 3 - 2"), 5)

    def test_right_associative_assignment(self):
        self.assertEqual(ev("let a = 0; let b = 0; a = b = 7; a + b"), 14)

    def test_pipe_inserts_first_argument(self):
        self.assertEqual(ev("[3, 1, 2] |> sort |> map(fn(x) -> x * 10)"), [10, 20, 30])

    def test_syntax_errors_have_positions(self):
        with self.assertRaises(MiniSyntaxError) as cm:
            parse("let x = (1 + 2\nprint(x)")
        self.assertEqual(cm.exception.line, 2)
        with self.assertRaises(MiniSyntaxError):
            parse("1 + = 2")
        with self.assertRaises(MiniSyntaxError):
            parse("fn f(a, a) -> a")
        with self.assertRaises(MiniSyntaxError):
            parse("1 = 2")


class SemanticsTests(unittest.TestCase):
    def test_closures_capture_by_reference(self):
        src = """
        fn counter() { let n = 0; fn() { n = n + 1 } }
        let a = counter(); let b = counter()
        a(); a(); b()
        [a(), b()]
        """
        self.assertEqual(ev(src), [3, 2])

    def test_block_scoping_and_shadowing(self):
        self.assertEqual(ev("let x = 1; if true { let x = 2 }; x"), 1)
        self.assertEqual(ev("let x = 1; if true { x = 2 }; x"), 2)

    def test_if_is_an_expression(self):
        self.assertEqual(ev('let n = 5; if n > 3 { "big" } else if n > 1 { "mid" } else { "small" }'), "big")
        self.assertIsNone(ev("if false { 1 }"))

    def test_truthiness(self):
        self.assertEqual(ev('[if 0 { 1 } else { 2 }, if "" { 1 } else { 2 }, if nil { 1 } else { 2 }]'), [1, 1, 2])

    def test_short_circuit(self):
        self.assertEqual(ev("let hit = false; fn boom() { hit = true }; false and boom(); hit"), False)
        self.assertEqual(ev("nil or 42"), 42)

    def test_loops_break_continue(self):
        src = """
        let out = []
        for i in 0..10 {
          if i % 2 == 0 { continue }
          if i > 7 { break }
          push(out, i)
        }
        out
        """
        self.assertEqual(ev(src), [1, 3, 5, 7])

    def test_early_return(self):
        self.assertEqual(ev("fn f(x) { if x { return 1 }; 2 }; [f(true), f(false)]"), [1, 2])

    def test_division(self):
        self.assertEqual(ev("6 / 3"), 2)
        self.assertIsInstance(ev("6 / 3"), int)
        self.assertEqual(ev("7 / 2"), 3.5)

    def test_equality_is_structural_and_type_aware(self):
        self.assertIs(ev("[1, [2, 3]] == [1, [2, 3]]"), True)
        self.assertIs(ev('{a: 1} == {a: 1}'), True)
        self.assertIs(ev("true == 1"), False)
        self.assertIs(ev('"1" == 1'), False)

    def test_maps_and_arrays(self):
        self.assertEqual(ev('let m = {a: 1}; m.b = 2; m["c"] = m.a + m.b; m'), {"a": 1, "b": 2, "c": 3})
        self.assertEqual(ev("let xs = [1, 2, 3]; xs[-1] = 9; xs"), [1, 2, 9])
        self.assertIsNone(ev("{}.missing"))

    def test_deep_recursion(self):
        self.assertEqual(ev("fn sum(n) { if n == 0 { 0 } else { n + sum(n - 1) } }; sum(1500)"), 1125750)

    def test_mutual_recursion(self):
        src = """
        fn is_even(n) { if n == 0 { true } else { is_odd(n - 1) } }
        fn is_odd(n) { if n == 0 { false } else { is_even(n - 1) } }
        [is_even(10), is_odd(7)]
        """
        self.assertEqual(ev(src), [True, True])

    def test_closure_names_are_per_instance(self):
        src = """
        fn make() { fn() { nil } }
        let first = make()
        let second = make()
        [str(first), str(second)]
        """
        self.assertEqual(ev(src), ["<fn first>", "<fn second>"])


class BuiltinTests(unittest.TestCase):
    def test_print_formatting(self):
        self.assertEqual(captured('print("x", [1, "a", nil, true, 2.0], {k: "v"})'),
                         ['x [1, "a", nil, true, 2.0] {"k": "v"}'])

    def test_sort_is_stable_with_key(self):
        src = 'sort([{n: "b", k: 1}, {n: "a", k: 0}, {n: "c", k: 1}], fn(p) -> p.k) |> map(fn(p) -> p.n)'
        self.assertEqual(ev(src), ["a", "b", "c"])

    def test_reduce_filter_join_split(self):
        self.assertEqual(ev("reduce(1..5, fn(a, b) -> a * b, 1)"), 24)
        self.assertEqual(ev('split("a,b,c", ",") |> join("-")'), "a-b-c")

    def test_min_max(self):
        self.assertEqual(ev("[min(3, 1, 2), max([4, 9, 2])]"), [1, 9])


class RuntimeErrorTests(unittest.TestCase):
    def assertRuntimeError(self, src, fragment, line=None):
        with self.assertRaises(MiniRuntimeError) as cm:
            ev(src)
        self.assertIn(fragment, cm.exception.message)
        if line is not None:
            self.assertEqual(cm.exception.line, line)
        return cm.exception

    def test_messages(self):
        self.assertRuntimeError("y", "undefined variable 'y'")
        self.assertRuntimeError("z = 1", "undeclared variable 'z'")
        self.assertRuntimeError("1 / 0", "division by zero")
        self.assertRuntimeError('1 + "a"', "unsupported operands for +: number and string")
        self.assertRuntimeError("[1][5]", "out of bounds")
        self.assertRuntimeError("fn f(a) -> a; f()", "takes 1 argument(s), got 0")
        self.assertRuntimeError("len(1, 2)", "takes 1 argument(s), got 2")
        self.assertRuntimeError("5()", "not callable")
        self.assertRuntimeError("break", "outside of a loop")

    def test_stack_overflow_is_caught(self):
        self.assertRuntimeError("fn f(n) -> f(n + 1); f(0)", "stack overflow")

    def test_trace_and_rendering(self):
        src = "fn inner() {\n  1 / 0\n}\nfn outer() -> inner()\nouter()"
        err = self.assertRuntimeError(src, "division by zero", line=2)
        rendered = err.render(src)
        self.assertIn("   2 |   1 / 0", rendered)
        self.assertIn("in inner() called at 4:20", rendered)
        self.assertIn("in outer() called at 5:6", rendered)

    def test_builtin_errors_get_call_site(self):
        self.assertRuntimeError("\n\npop([])", "empty array", line=3)


class ExampleTests(unittest.TestCase):
    def test_showcase_runs(self):
        out = subprocess.run(
            [sys.executable, "-m", "mini", os.path.join("examples", "showcase.mini")],
            cwd=ROOT, capture_output=True, text=True, check=True).stdout
        self.assertIn("quicksort: [3, 3, 9, 10, 27, 38, 43, 82]", out)
        self.assertIn("primes < 50: [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47]", out)
        self.assertIn("4660046610375530309", out)


if __name__ == "__main__":
    unittest.main()
