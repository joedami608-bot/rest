import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ember import RuntimeErr, SyntaxErr, TypeErr, compile_source, run  # noqa: E402
from ember import exhaustive as ex  # noqa: E402
from ember.disasm import disassemble  # noqa: E402
from ember.lexer import tokenize  # noqa: E402
from ember.runtime import show  # noqa: E402
from ember.typecheck import show_scheme  # noqa: E402


def ev(src):
    return run(src, output=lambda _: None)


def out(src):
    lines = []
    run(src, output=lines.append)
    return lines


def types_of(src):
    """Inferred type of each user-defined top-level fn and let."""
    c = compile_source(src)
    result = {f.name: show_scheme(c.checker.fn_schemes[f.name])
              for f in c.program.fns if not getattr(f.fn, "from_prelude", False)}
    for s in c.program.stmts:
        if hasattr(s, "scheme"):
            result[s.name] = show_scheme(s.scheme)
    return result


class LexerParserTests(unittest.TestCase):
    def test_token_kinds(self):
        kinds = [(t.kind, t.value) for t in tokenize('fn Foo x :: 1_000 "s"')][:-1]
        self.assertEqual(kinds, [("KEYWORD", "fn"), ("UPPER", "Foo"), ("IDENT", "x"),
                                 ("OP", "::"), ("INT", 1000), ("STRING", "s")])

    def test_precedence_and_associativity(self):
        self.assertEqual(ev("1 + 2 * 3 - 4 / 2"), 5)
        self.assertEqual(ev("10 - 3 - 2"), 5)
        self.assertEqual(show(ev("1 :: 2 :: []")), "[1, 2]")       # :: is right-associative
        self.assertIs(ev("not 1 == 2"), True)
        self.assertIs(ev("1 < 2 and 2 < 3 or false"), True)

    def test_pipe(self):
        self.assertEqual(ev("[3, 1, 2] |> map(fn(x) => x * 10) |> sum"), 60)

    def test_call_must_be_on_same_line(self):
        # `f()` then `(1)` on the next line are two statements, not f()(1).
        self.assertEqual(ev("fn f() = 7\nf()\n(1)"), 1)

    def test_syntax_errors(self):
        for src, fragment in [
            ("let = 1", "expected variable name"),
            ("fn f(a, a) = a", "duplicate parameter"),
            ("let x = (1 + 2", "expected ')'"),
            ('let s = "abc', "unterminated string"),
            ("let x = _", "only allowed in patterns"),
            ("fn f() { type T = A }", "only allowed at the top level"),
        ]:
            with self.subTest(src=src):
                with self.assertRaises(SyntaxErr) as cm:
                    compile_source(src)
                self.assertIn(fragment, cm.exception.message)


class InferenceTests(unittest.TestCase):
    def test_principal_types(self):
        t = types_of("""
            fn id(x) = x
            fn compose(f, g) = fn(x) => f(g(x))
            fn twice(f, x) = f(f(x))
            fn const_(a, b) = a
            fn len2(xs) = match xs { [] => 0, _ :: t => 1 + len2(t) }
        """)
        self.assertEqual(t["id"], "(a) -> a")
        self.assertEqual(t["compose"], "((a) -> b, (c) -> a) -> ((c) -> b)")
        self.assertEqual(t["twice"], "((a) -> a, a) -> a")
        self.assertEqual(t["const_"], "(a, b) -> a")
        self.assertEqual(t["len2"], "(List[a]) -> Int")

    def test_prelude_types(self):
        c = compile_source("")
        schemes = c.checker.fn_schemes
        self.assertEqual(show_scheme(schemes["map"]), "(List[a], (a) -> b) -> List[b]")
        self.assertEqual(show_scheme(schemes["fold"]), "(List[a], b, (b, a) -> b) -> b")
        self.assertEqual(show_scheme(schemes["zip"]), "(List[a], List[b]) -> List[Pair[a, b]]")

    def test_let_polymorphism(self):
        self.assertEqual(show(ev('let id = fn(x) => x\nPair(id(1), id("a"))')), 'Pair(1, "a")')
        self.assertEqual(show(ev('fn f() { let id = fn(x) => x; Pair(id(1), id(true)) }\nf()')),
                         "Pair(1, true)")

    def test_lambda_parameters_are_monomorphic(self):
        with self.assertRaises(TypeErr):
            compile_source('fn g(h) = Pair(h(1), h("a"))')

    def test_var_is_not_generalised(self):
        with self.assertRaises(TypeErr):
            compile_source('var f = fn(x) => x\nf(1)\nf("a")')

    def test_value_restriction_on_applications(self):
        # `map([], ...)` is an application, so its type stays monomorphic.
        with self.assertRaises(TypeErr):
            compile_source('let e = map([], fn(x) => x)\n1 :: e\n"a" :: e')

    def test_levels_keep_captured_variables_monomorphic(self):
        t = types_of('fn f(x) { let g = fn(z) => x; Pair(g(1), g("a")) }')
        self.assertEqual(t["f"], "(a) -> Pair[a, a]")

    def test_mutual_recursion_is_one_group_but_others_stay_polymorphic(self):
        t = types_of("""
            fn ev_(n) = if n == 0 { true } else { od(n - 1) }
            fn od(n) = if n == 0 { false } else { ev_(n - 1) }
            fn ident(x) = x
            fn use_both() = Pair(ident(1), ident("s"))
        """)
        self.assertEqual(t["ev_"], "(Int) -> Bool")
        self.assertEqual(t["use_both"], "() -> Pair[Int, String]")

    def test_annotations(self):
        t = types_of("fn first(xs: List[a]) -> Option[a] = match xs { [] => None, x :: _ => Some(x) }")
        self.assertEqual(t["first"], "(List[a]) -> Option[a]")
        with self.assertRaises(TypeErr):
            compile_source('fn bad(x: Int) -> String = x')

    def test_type_errors(self):
        cases = [
            ('1 + "a"', "expected Int, found String"),
            ("fn f(a) = a + 1\nf(true)", "argument 1 of 'f': expected Int, found Bool"),
            ("fn f(a) = a\nf(1, 2)", "takes 1 argument(s) but 2 were given"),
            ("let x = 5\nx(1)", "not a function"),
            ("let n = 1\nn = 2", "declared with 'let'"),
            ("fn f(x) = x(x)", "infinite type"),
            ("y", "undefined variable 'y'"),
            ("if 1 { 2 } else { 3 }", "if condition: expected Bool, found Int"),
            ("if true { 1 }", "without 'else'"),
            ("[1, true]", "list element 1"),
            ("(fn() => 1) == (fn() => 1)", "functions cannot be compared"),
            ("fn f(x) = x == x\nf(fn() => 1)", "functions cannot be compared"),
            ("fn f(x) = [x] == [x]\nf(fn() => 1)", "functions cannot be compared"),
            ("Some(1, 2)", "takes 1 argument(s)"),
            ("type T = A(Unknown)", "unknown type 'Unknown'"),
            ("type T = A(List)", "takes 1 parameter(s)"),
            ("type T = A(b)", "unknown type variable 'b'"),
            ("match 1 { Some(x) => x, _ => 0 }", "pattern type"),
        ]
        for src, fragment in cases:
            with self.subTest(src=src):
                with self.assertRaises(TypeErr) as cm:
                    compile_source(src)
                self.assertIn(fragment, cm.exception.message)

    def test_hint_for_toplevel_let_used_in_fn(self):
        with self.assertRaises(TypeErr) as cm:
            compile_source("let limit = 3\nfn f(x) = x < limit")
        self.assertIn("hoisted", cm.exception.notes[0])


class ExhaustivenessTests(unittest.TestCase):
    def missing(self, src):
        with self.assertRaises(TypeErr) as cm:
            compile_source(src)
        self.assertIn("not exhaustive", cm.exception.message)
        return cm.exception.notes[0].split(": ", 1)[1]

    def test_witnesses(self):
        self.assertEqual(self.missing("fn f(x) = match x { [] => 0 }"), "_ :: _")
        self.assertEqual(self.missing("fn f(x) = match x { _ :: _ => 0 }"), "[]")
        self.assertEqual(self.missing("fn f(x) = match x { true => 0 }"), "false")
        self.assertEqual(self.missing("fn f(x) = match x { Some(Some(_)) => 0, None => 1 }"), "Some(None)")
        self.assertEqual(self.missing("fn f(x) = match x { 0 => 0, 1 => 1 }"), "_")
        self.assertEqual(self.missing("fn f(x) = match x { [_] => 0, [] => 1 }"), "_ :: _ :: _")
        self.assertEqual(
            self.missing("fn f(p) = match p { Pair(true, _) => 0, Pair(_, false) => 1 }"),
            "Pair(false, true)")

    def test_exhaustive_matches_compile(self):
        compile_source("""
            type T = A | B(Int) | C(T, T)
            fn f(t) = match t { A => 0, B(_) => 1, C(A, _) => 2, C(_, _) => 3 }
            fn g(xs) = match xs { [] => 0, [_] => 1, _ :: _ :: _ => 2 }
            fn h(u) = match u { () => 0 }
        """)

    def test_redundant_arm_warning(self):
        c = compile_source("fn f(x) = match x { _ => 1, 0 => 2 }")
        self.assertEqual(len(c.warnings), 1)
        self.assertIn("unreachable", c.warnings[0].message)
        c = compile_source("fn f(x) = match x { None => 1, Some(_) => 2 }")
        self.assertEqual(c.warnings, [])

    def test_usefulness_directly(self):
        nil = ex.con("[]", [], "list")
        cons = lambda h, t: ex.con("::", [h, t], "list")  # noqa: E731
        rows = [[nil], [cons(ex.WILD, nil)]]
        self.assertTrue(ex.useful(rows, [cons(ex.WILD, cons(ex.WILD, ex.WILD))]))
        self.assertFalse(ex.useful(rows + [[cons(ex.WILD, cons(ex.WILD, ex.WILD))]], [ex.WILD]))


class RuntimeTests(unittest.TestCase):
    def test_closures_share_mutable_cells(self):
        src = """
        fn make() {
          var n = 0
          let inc = fn() => { n = n + 1; n }
          let get = fn() => n
          Pair(inc, get)
        }
        match make() {
          Pair(inc, get) => { inc(); inc(); get() }
        }
        """
        self.assertEqual(ev(src), 2)

    def test_each_loop_iteration_gets_fresh_binding(self):
        src = """
        var fs = []
        var i = 0
        while i < 3 { let j = i; fs = (fn() => j) :: fs; i = i + 1 }
        map(fs, fn(f) => f())
        """
        self.assertEqual(show(ev(src)), "[2, 1, 0]")

    def test_nested_capture_through_two_levels(self):
        self.assertEqual(ev("fn f(x) = fn(y) => fn(z) => x + y + z\nf(1)(2)(3)"), 6)

    def test_local_recursive_function(self):
        self.assertEqual(ev("fn outer(n) { fn go(i, acc) = if i == 0 { acc } else { go(i - 1, acc * i) }; go(n, 1) }\nouter(10)"),
                         3628800)

    def test_tail_calls_run_in_constant_stack(self):
        self.assertEqual(ev("fn loop(i, acc) = if i == 0 { acc } else { loop(i - 1, acc + 1) }\nloop(300000, 0)"),
                         300000)

    def test_and_or_right_operand_is_a_tail_position(self):
        self.assertIs(ev("any(range(0, 300000), fn(x) => x < 0)"), False)
        self.assertIs(ev("all(range(0, 300000), fn(x) => x >= 0)"), True)

    def test_deep_non_tail_recursion_beyond_python_limit(self):
        # 50k nested Ember calls; CPython's own recursion limit is ~1000.
        self.assertEqual(ev("fn down(n) = if n == 0 { 0 } else { 1 + down(n - 1) }\ndown(50000)"), 50000)

    def test_stack_overflow_is_reported(self):
        with self.assertRaises(RuntimeErr) as cm:
            ev("fn f(n) = 1 + f(n + 1)\nf(0)")
        self.assertIn("stack overflow", cm.exception.message)

    def test_structural_equality_on_long_lists(self):
        self.assertIs(ev("range(0, 100000) == range(0, 100000)"), True)
        self.assertIs(ev("range(0, 100000) == range(1, 100001)"), False)
        self.assertIs(ev("Some([1, 2]) == Some([1, 2])"), True)
        self.assertIs(ev("[Some(1)] != [None]"), True)

    def test_constructors_as_functions(self):
        self.assertEqual(show(ev("map([1, 2], Some)")), "[Some(1), Some(2)]")

    def test_integer_division_and_modulo(self):
        self.assertEqual(ev("7 / 2"), 3)
        self.assertEqual(ev("-7 / 2"), -4)  # floors, like Python
        self.assertEqual(ev("7 % 3"), 1)

    def test_prelude(self):
        self.assertEqual(show(ev("sort([5, 3, 9, 1, 3], fn(a, b) => a < b)")), "[1, 3, 3, 5, 9]")
        self.assertEqual(show(ev("take(range(0, 10), 3)")), "[0, 1, 2]")
        self.assertEqual(show(ev("drop(range(0, 5), 3)")), "[3, 4]")
        self.assertEqual(show(ev("nth([7, 8, 9], 1)")), "Some(8)")
        self.assertEqual(show(ev("zip([1, 2, 3], [\"a\", \"b\"])")), '[Pair(1, "a"), Pair(2, "b")]')
        self.assertEqual(ev('join(["x", "y", "z"], "-")'), "x-y-z")
        self.assertEqual(ev("length(range(0, 100000))"), 100000)  # tail-recursive fold
        self.assertIs(ev("any([1, 2, 3], fn(x) => x > 2)"), True)
        self.assertEqual(show(ev('chars("hey")')), '["h", "e", "y"]')

    def test_output_formatting(self):
        self.assertEqual(out('print("raw")\nprint(["q"])\nprint(())\nprint(None)'),
                         ["raw", '["q"]', "()", "None"])

    def test_runtime_error_location_and_trace(self):
        # (report's call is not in tail position, so its frame stays on the trace)
        src = "fn avg(xs) = sum(xs) / length(xs)\nfn report() = avg([]) + 0\nreport()"
        with self.assertRaises(RuntimeErr) as cm:
            ev(src)
        e = cm.exception
        self.assertEqual((e.line, e.col), (1, 22))
        self.assertEqual(e.notes[:3], ["in avg (line 1)", "in report (line 2)", "in <main> (line 3)"])

    def test_error_inside_prelude_points_at_user_code(self):
        with self.assertRaises(RuntimeErr) as cm:
            ev('let xs = [1, 0]\nmap(xs, fn(x) => 10 / x)')
        self.assertEqual(cm.exception.line, 2)
        self.assertTrue(any("prelude" in n for n in cm.exception.notes))

    def test_panic(self):
        with self.assertRaises(RuntimeErr) as cm:
            ev('fn must(o) = match o { Some(x) => x, None => panic("empty") }\nmust(None) + 1')
        self.assertIn("panic: empty", cm.exception.message)


class ToolingTests(unittest.TestCase):
    def test_disassembler_lists_nested_code(self):
        c = compile_source("fn add1(x) = x + 1\nprint(add1(2))")
        listing = "\n".join(disassemble(c.main, c.global_names))
        self.assertIn("== add1", listing)
        self.assertIn("LOAD_LOCAL_CONST_ADD", listing)  # superinstruction for `x + 1`
        self.assertIn("RETURN", listing)

    def test_tail_call_opcode_is_used(self):
        c = compile_source("fn f(n) = if n == 0 { 0 } else { f(n - 1) }")
        self.assertIn("TAIL_CALL", "\n".join(disassemble(c.main, c.global_names)))

    def test_cli_and_examples(self):
        def cli(*args):
            return subprocess.run([sys.executable, "-m", "ember", *args], cwd=ROOT,
                                  capture_output=True, text=True)
        r = cli(os.path.join("examples", "ember", "showcase.em"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("tree in order: [20, 30, 40, 50, 60, 70, 80], depth 3", r.stdout)
        self.assertIn("starts at 6171 (261 steps)", r.stdout)
        r = cli("--types", os.path.join("examples", "ember", "showcase.em"))
        self.assertIn("fn insert : (Tree[a], a, (a, a) -> Bool) -> Tree[a]", r.stdout)
        r = cli("-e", 'print(1 + "x")')
        self.assertEqual(r.returncode, 1)
        self.assertIn("TypeError at 1:11", r.stderr)


if __name__ == "__main__":
    unittest.main()
