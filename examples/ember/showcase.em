# Ember showcase — run with:  python3 -m ember examples/ember/showcase.em
# Not a single type annotation below is required; everything is inferred.
# Try:  python3 -m ember --types examples/ember/showcase.em

# ---- algebraic data types + exhaustive pattern matching -----------------
type Shape = Circle(Int) | Rect(Int, Int) | Triangle(Int, Int)

fn area(s) = match s {
  Circle(r) => 3 * r * r
  Rect(w, h) => w * h
  Triangle(b, h) => b * h / 2
}

let shapes = [Circle(2), Rect(3, 4), Triangle(6, 5)]
print("areas: " ++ to_string(map(shapes, area)))

# ---- a polymorphic binary search tree -----------------------------------
type Tree[a] = Leaf | Node(Tree[a], a, Tree[a])

fn insert(t, x, less) = match t {
  Leaf => Node(Leaf, x, Leaf)
  Node(l, v, r) =>
    if less(x, v) { Node(insert(l, x, less), v, r) }
    else if less(v, x) { Node(l, v, insert(r, x, less)) }
    else { t }
}

fn to_list(t) = walk(t, [])
fn walk(t, acc) = match t {
  Leaf => acc
  Node(l, v, r) => walk(l, v :: walk(r, acc))
}

fn depth(t) = match t {
  Leaf => 0
  Node(l, _, r) => 1 + max(depth(l), depth(r))
}
fn max(a, b) = if a > b { a } else { b }

let int_tree = fold([50, 30, 70, 20, 40, 60, 80, 30], Leaf, fn(t, x) => insert(t, x, fn(a, b) => a < b))
print("tree in order: " ++ to_string(to_list(int_tree)) ++ ", depth " ++ to_string(depth(int_tree)))

# The very same functions work for strings: let-polymorphism at work.
fn shorter(a, b) = str_len(a) < str_len(b)
let word_tree = fold(["banana", "fig", "cherry", "kiwi"], Leaf, fn(t, x) => insert(t, x, shorter))
print("words by length: " ++ join(to_list(word_tree), " < "))

# ---- closures with mutable captured state -------------------------------
fn make_counter() {
  var count = 0
  fn() => {
    count = count + 1
    count
  }
}
let next_id = make_counter()
next_id(); next_id()
print("third id: " ++ to_string(next_id()))

# ---- Option instead of null ---------------------------------------------
fn safe_div(a, b) = if b == 0 { None } else { Some(a / b) }
print("10 / 2 = " ++ to_string(safe_div(10, 2)) ++ ", 1 / 0 = " ++ to_string(safe_div(1, 0)))
print("with default: " ++ to_string(unwrap_or(safe_div(1, 0), -1)))

# ---- pipelines over the standard library --------------------------------
let total = range(1, 101)
  |> filter(fn(n) => n % 3 == 0 or n % 5 == 0)
  |> map(fn(n) => n * n)
  |> sum
print("sum of squares of multiples of 3 or 5 below 101: " ++ to_string(total))

# ---- tail calls: one million iterations, constant stack -----------------
fn count_collatz(n, steps) =
  if n == 1 { steps }
  else if n % 2 == 0 { count_collatz(n / 2, steps + 1) }
  else { count_collatz(3 * n + 1, steps + 1) }

fn longest_collatz(i, limit, best, best_n) =
  if i >= limit { Pair(best_n, best) }
  else {
    let s = count_collatz(i, 0)
    if s > best { longest_collatz(i + 1, limit, s, i) } else { longest_collatz(i + 1, limit, best, best_n) }
  }

match longest_collatz(1, 10000, 0, 1) {
  Pair(n, steps) => print("longest Collatz chain below 10000 starts at " ++ to_string(n) ++ " (" ++ to_string(steps) ++ " steps)")
}

# ---- mutual recursion: inferred together as one strongly connected group --
fn is_even(n) = if n == 0 { true } else { is_odd(n - 1) }
fn is_odd(n) = if n == 0 { false } else { is_even(n - 1) }
print("is_even(100001) = " ++ to_string(is_even(100001)))
