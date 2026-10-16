# Ember standard library, written in Ember itself.
# Functions take the "subject" first so they read well with |>:  xs |> map(f) |> sum

type Option[a] = None | Some(a)
type Result[a, e] = Ok(a) | Err(e)
type Pair[a, b] = Pair(a, b)

# ---- lists (all loops are tail calls, so they run in constant stack space) ----

fn fold(xs, acc, f) = match xs {
  [] => acc
  x :: rest => fold(rest, f(acc, x), f)
}

fn rev_onto(xs, acc) = match xs {
  [] => acc
  x :: rest => rev_onto(rest, x :: acc)
}

# reverse, length, append, sum, range and join are natives (see runtime.py):
# they never call back into Ember code, so they can run as plain Python loops.

fn map(xs, f) = reverse(map_acc(xs, f, []))
fn map_acc(xs, f, acc) = match xs {
  [] => acc
  x :: rest => map_acc(rest, f, f(x) :: acc)
}

fn filter(xs, keep) = reverse(filter_acc(xs, keep, []))
fn filter_acc(xs, keep, acc) = match xs {
  [] => acc
  x :: rest => filter_acc(rest, keep, if keep(x) { x :: acc } else { acc })
}

fn any(xs, p) = match xs { [] => false, x :: rest => p(x) or any(rest, p) }
fn all(xs, p) = match xs { [] => true, x :: rest => p(x) and all(rest, p) }

fn take(xs, n) = reverse(take_acc(xs, n, []))
fn take_acc(xs, n, acc) = match xs {
  [] => acc
  x :: rest => if n <= 0 { acc } else { take_acc(rest, n - 1, x :: acc) }
}

fn drop(xs, n) = match xs {
  [] => []
  _ :: rest => if n <= 0 { xs } else { drop(rest, n - 1) }
}

fn find(xs, p) = match xs {
  [] => None
  x :: rest => if p(x) { Some(x) } else { find(rest, p) }
}

fn nth(xs, i) = match drop(xs, i) {
  [] => None
  x :: _ => Some(x)
}

fn zip(xs, ys) = reverse(zip_acc(xs, ys, []))
fn zip_acc(xs, ys, acc) = match xs {
  [] => acc
  x :: xt => match ys {
    [] => acc
    y :: yt => zip_acc(xt, yt, Pair(x, y) :: acc)
  }
}

# Merge sort; `less(a, b)` decides the order.
fn sort(xs, less) = match xs {
  [] => []
  [x] => [x]
  _ => match split(xs, [], []) {
    Pair(a, b) => merge(sort(a, less), sort(b, less), less, [])
  }
}

fn split(xs, a, b) = match xs {
  [] => Pair(a, b)
  x :: rest => split(rest, b, x :: a)
}

fn merge(xs, ys, less, acc) = match xs {
  [] => rev_onto(acc, ys)
  x :: xt => match ys {
    [] => rev_onto(acc, xs)
    y :: yt => if less(y, x) { merge(xs, yt, less, y :: acc) } else { merge(xt, ys, less, x :: acc) }
  }
}

# ---- options ----

fn unwrap_or(opt, default) = match opt {
  Some(x) => x
  None => default
}

fn map_option(opt, f) = match opt {
  Some(x) => Some(f(x))
  None => None
}
