# Ember：带类型推导的静态类型脚本语言

Ember 写起来像脚本语言（几乎不用写类型），但它是**静态类型**的：程序运行前，编译器会推导出每个表达式的类型，并证明所有 `match` 都覆盖了全部情况。通过检查后，程序被编译成字节码，在自制的栈式虚拟机上运行。

纯 Python 实现，零依赖。以下命令都在仓库根目录运行：

```bash
python3 -m ember examples/ember/showcase.em            # 运行示例
python3 -m ember --types examples/ember/showcase.em    # 查看推导出的类型
python3 -m ember --dis -e 'fn sq(x) = x * x'           # 查看字节码
python3 -m ember examples/ember/type_error.em          # 看编译期如何拒绝有漏洞的程序
python3 -m unittest tests.test_ember -v                # 39 个测试
python3 benchmarks/run.py                              # 和 Mini 比较性能
```

## 一分钟语法

```rust
# 代数数据类型（可以带类型参数）
type Shape = Circle(Int) | Rect(Int, Int)
type Tree[a] = Leaf | Node(Tree[a], a, Tree[a])

# 函数：`= 表达式` 或 `{ 代码块 }`，最后一个表达式就是返回值
fn area(s) = match s {
  Circle(r) => 3 * r * r
  Rect(w, h) => w * h
}

# 类型标注是可选的，写了就会被检查
fn first(xs: List[a]) -> Option[a] = match xs {
  [] => None
  x :: _ => Some(x)
}

let xs = [1, 2, 3]                     # 不可变绑定
var total = 0                          # 可变变量
while total < 10 { total = total + 1 }
let double = fn(x) => x * 2            # lambda
xs |> map(double) |> sum               # 管道：x |> f(a) 即 f(x, a)
```

模式支持：`_`、变量、整数/字符串/布尔字面量、`()`、`[]`、`h :: t`、`[a, b]`、`Ctor(p1, p2)`，可以任意嵌套。

## 编译流水线

```
源码 ─► lexer.py ─► parser.py ─► syntax.py (AST) ─► typecheck.py ─► compiler.py ─► vm.py
                    Pratt 解析                       HM 类型推导      作用域分析      栈式虚拟机
                                                     穷尽性检查       字节码生成      尾调用
                                                     (exhaustive.py)                (二分分发)
```

## 类型系统（`typecheck.py`）

* **Hindley-Milner 类型推导**：合一（unification）基于并查集和路径压缩，带 occurs check，所以 `fn f(x) = x(x)` 会报"无限类型"。
* **基于层级（level）的泛化**：用 Rémy 的 level 技术判断哪些类型变量可以泛化，不需要每次扫描整个环境。
* **let 多态 + 值限制**：`let id = fn(x) => x` 之后可以同时用于 `id(1)` 和 `id("a")`。函数参数是单态的，`var` 和函数调用的结果不泛化（ML 的 value restriction），保证可变状态下的类型安全。
* **强连通分量**：顶层函数会被提升（hoist），可以互相递归。编译器用 Tarjan 算法把函数划分为强连通分量，按依赖顺序逐组推导，这样互相递归的函数在同一组里推导，其他函数仍然保持最一般的多态类型。
* **相等类型变量**（借鉴 Standard ML）：`==` 用过的类型变量带有标记，以后如果被实例化成函数类型就报错。所以 `fn same(a, b) = a == b` 之后，`same(f, g)` 会在编译期被拒绝。
* **穷尽性和冗余检查**（`exhaustive.py`）：实现了 Maranget 的 usefulness 算法（*Warnings for pattern matching*, JFP 2007）。漏掉的情况会被当作**错误**，并给出一个具体的反例，例如 `Some(None)`、`_ :: _ :: _`。永远匹配不到的分支会给出警告。

推导结果示例（`--types` 的输出，全部没有写标注）：

```
fn insert : (Tree[a], a, (a, a) -> Bool) -> Tree[a]
fn make_counter : () -> (() -> Int)
fn safe_div : (Int, Int) -> Option[Int]
```

## 编译器与虚拟机（`compiler.py`、`vm.py`）

* **两遍编译**：第一遍做作用域分析，找出被内层函数捕获的变量；第二遍生成字节码。被捕获的变量放进堆上的 `Cell`（和 CPython 的 cellvar 机制一样），所以多个闭包可以共享同一个可变变量。循环里每次迭代都会创建新的绑定。
* **显式调用栈**：Ember 函数调用不占用 Python 的调用栈，5 万层非尾递归也能正常运行（CPython 自身的递归限制约为 1000）。超过 20 万层会报 `stack overflow`。
* **尾调用优化**：尾位置的调用（包括 `if`/`match` 分支末尾和 `and`/`or` 的右侧）会编译成 `TAIL_CALL`，复用当前栈帧，循环写成递归也只占常数栈空间。代价是尾调用的调用者不会出现在错误的调用栈里，这和 Scheme 一样。
* **超级指令**：`n - 1`、`i + 1`、`n < 2` 这类"局部变量 ⊕ 整数常量"的模式会被编译成一条指令。
* **二分分发**：Python 没有 computed goto，一条 50 分支的 `if/elif` 链对排在后面的指令要比较二十多次。VM 在导入时根据每条指令的处理代码**自动生成**一棵按操作码二分的判断树，每条指令都只需约 6 次比较。这一项优化让循环基准测试从 5.0 秒降到 2.2 秒。
* **精确的错误位置**：每条字节码都记录了源码的行号和列号。运行时错误会指向具体的列，并给出调用栈。如果错误发生在标准库内部，会定位到调用它的用户代码那一行。

`fib` 的字节码（`--dis`）：

```
== fib  (arity 1, 1 locals, 0 free) ==
   1     0  LOAD_LOCAL_CONST_LT   0 0     ; local 0, 2
         3  JUMP_IF_FALSE         9       ; -> 9
         5  LOAD_LOCAL            0
         7  JUMP                  24      ; -> 24
         9  LOAD_GLOBAL           33      ; fib
        11  LOAD_LOCAL_CONST_SUB  0 1     ; local 0, 1
        14  CALL                  1
        16  LOAD_GLOBAL           33      ; fib
        18  LOAD_LOCAL_CONST_SUB  0 0     ; local 0, 2
        21  CALL                  1
        23  ADD
        24  RETURN
```

## 性能（`benchmarks/run.py`，三次取最好，包含启动时间）

| 测试 | Mini（树遍历） | Ember（字节码） | 加速比 |
| --- | --- | --- | --- |
| fib(25)，递归调用 | 1.60s | 0.35s | 4.5× |
| while 循环 100 万次 | 7.08s | 1.59s | 4.4× |
| 构建并求和 20 万元素的列表 | 1.04s | 1.05s | 1.0× |

最后一项打平是因为 Mini 的 `map` 是 Python 原生函数，而 Ember 的 `map`/`filter`/`fold` 等高阶函数是用 Ember 自己写的（见 `prelude.em`），每个元素的回调都要在虚拟机里解释执行。不调用回调的纯数据操作（`range`、`reverse`、`length`、`sum`、`join` 等）是原生实现。

## 已知限制

* 顶层函数是提升的，看不到顶层的 `let` 值（编译器会给出提示）。需要的话，把值作为参数传入，或者写成函数。
* 只有 `Int`，没有浮点数；`/` 是向下取整的整数除法。
* 比较大小（`<` 等）只支持 `Int`；`==` 支持除函数外的所有类型。
* 如果用户定义的数据类型里有函数字段，`==` 在运行时会按引用比较这些字段，相等类型检查覆盖不到这种情况。
* 没有模块系统和类型类。

## 文件

| 文件 | 内容 |
| --- | --- |
| `lexer.py` | 词法分析，区分大写开头的类型名/构造器 |
| `parser.py` | 递归下降 + Pratt 表达式解析 |
| `syntax.py` | AST 节点 |
| `typecheck.py` | HM 类型推导、SCC、相等类型、模式类型检查 |
| `exhaustive.py` | Maranget 穷尽性/冗余算法 |
| `compiler.py` | 作用域分析 + 字节码生成 |
| `opcodes.py` | 指令集 |
| `vm.py` | 虚拟机（自动生成的二分分发循环） |
| `runtime.py` | 运行时值和原生函数 |
| `disasm.py` | 反汇编器 |
| `prelude.em` | 用 Ember 写的标准库 |
