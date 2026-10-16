# Mini：一门用纯 Python 从零实现的小型编程语言

零依赖（只用 Python 3.10+ 标准库），约 1000 行代码，包含一个完整语言实现的所有层次：

```
源代码 ──► Lexer ──► Token 流 ──► Pratt Parser ──► AST ──► 树遍历解释器 ──► 结果
          (lexer.py)            (parser.py)       (ast.py)  (interpreter.py + builtins.py)
```

## 快速开始

```bash
python3 -m mini examples/showcase.mini          # 运行示例程序
python3 -m mini examples/error_demo.mini        # 看错误报告长什么样
python3 -m mini                                 # 交互式 REPL（支持多行输入）
python3 -m unittest discover -s tests -v        # 运行 31 个测试
```

## 语言速览

```python
# 函数：最后一个表达式就是返回值；`->` 是单表达式简写
fn fib(n) { if n < 2 { n } else { fib(n - 1) + fib(n - 2) } }
let square = fn(x) -> x * x

# 闭包按引用捕获外层变量
fn make_counter() { let count = 0; fn() { count = count + 1 } }

# 管道运算符：x |> f(a)  等价于  f(x, a)
1..20 |> filter(fn(x) -> x % 2 == 1) |> map(square) |> reduce(fn(a, b) -> a + b, 0)

# 数组、Map、点号访问、for / while / break / continue
let p = {name: "Ada", born: 1815}
for i in 0..10 { if i % 2 == 0 { continue }; print(i, p.name) }
```

完整演示见 [`examples/showcase.mini`](examples/showcase.mini)：递归、闭包计数器、用 Mini 自己写的快速排序、埃氏筛、词频统计、基于闭包的记忆化（`fib(90)` 只需几毫秒）。

## 设计要点

| 主题 | 做法 |
| --- | --- |
| 解析 | **Pratt 解析器**（自顶向下算符优先），优先级表集中在 `PRECEDENCE` 一处；赋值右结合，其余左结合 |
| 换行歧义 | 调用 `(` / 下标 `[` 必须与前一个 token 同行，避免 JavaScript 式的 `f()\n[1,2]` 被误读为 `f()[1,2]` |
| `not` 优先级 | 与 Python 一致：`not a == b` 等于 `not (a == b)` |
| 作用域 | 词法作用域链（`Env`），每个块一个新作用域；`let` 声明、`=` 只能给已声明变量赋值（防拼写错误） |
| 控制流 | `return` / `break` / `continue` 用内部异常实现非局部跳转 |
| 一切皆表达式 | `if` 和代码块都有值，函数隐式返回最后一个表达式 |
| 真值 | 仅 `false` 和 `nil` 为假（`0`、`""` 为真），与 Ruby / Lua 相同 |
| 相等 | 结构化比较且区分类型：`[1,[2]] == [1,[2]]` 为真，`true == 1` 为假（Python 里是真） |
| 深递归 | 解释器在 256MB 栈的线程中运行，支持数千层 Mini 递归；超过上限报 `stack overflow` 而不是让 CPython 崩溃 |
| 错误报告 | 每个 AST 节点记录行列号，报错时显示源码行、`^` 指示符和调用栈 |

错误报告示例：

```
examples/error_demo.mini: RuntimeError at 3:36: division by zero
   3 |   reduce(xs, fn(a, b) -> a + b, 0) / len(xs)
                                          ^
  in average() called at 5:25
  in report() called at 7:13
```

## 内置函数

`print` `len` `push` `pop` `str` `int` `type` `map` `filter` `reduce` `sort`（稳定归并排序，可传 key 函数）
`keys` `has` `join` `split` `range` `assert` `min` `max` `abs` `clock`

## 目录结构

```
mini/
  lexer.py        词法分析（行列号、转义、注释、区分 1..5 与 2.5）
  parser.py       Pratt 解析器
  ast.py          AST 节点（dataclass）
  interpreter.py  求值器、作用域、闭包、调用栈
  builtins.py     标准库
  errors.py       带位置信息的错误与渲染
  __main__.py     命令行与 REPL
examples/         示例程序
tests/            单元测试 + 端到端测试
```
