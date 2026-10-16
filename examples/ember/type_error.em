# This program is rejected before it runs: the compiler proves the match below
# forgets a case. Run:  python3 -m ember examples/ember/type_error.em

type Payment = Cash(Int) | Card(String, Int) | Voucher(Option[Int])

fn amount(p) = match p {
  Cash(n) => n
  Card(_, n) => n
  Voucher(Some(n)) => n
}

print(amount(Voucher(None)))
