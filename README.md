# 两门从零实现的编程语言

都用纯 Python 写成，零依赖（Python 3.10+），代表了语言实现的两种经典路线：

| | [Mini](mini/README.md) | [Ember](ember/README.md) |
| --- | --- | --- |
| 类型 | 动态类型 | 静态类型，Hindley-Milner 类型推导 |
| 执行方式 | 树遍历解释器 | 编译成字节码，在栈式虚拟机上运行 |
| 特色 | 闭包、管道运算符、精确报错 | 代数数据类型、穷尽性检查、尾调用优化 |
| 速度 | 基准 | 递归和循环快 4 倍以上 |

```bash
python3 -m mini  examples/showcase.mini
python3 -m ember examples/ember/showcase.em
python3 -m ember --types examples/ember/showcase.em   # 查看编译器推导出的类型
python3 -m unittest discover -s tests                 # 两门语言的全部 70 个测试
python3 benchmarks/run.py                             # 性能对比
```

同一类问题（漏处理某种情况），两门语言发现的时机不同：

```
$ python3 -m mini examples/error_demo.mini        # Mini：程序跑到那一行才出错
examples/error_demo.mini: RuntimeError at 3:36: division by zero

$ python3 -m ember examples/ember/type_error.em   # Ember：运行之前就拒绝
examples/ember/type_error.em: TypeError at 6:16: match is not exhaustive
   6 | fn amount(p) = match p {
                      ^
  note: for example, this value is not handled: Voucher(None)
```

## 目录

```
mini/          动态类型语言（词法分析、Pratt 解析、树遍历解释器）
ember/         静态类型语言（类型推导、穷尽性检查、字节码编译器、虚拟机）
examples/      两门语言的示例程序
tests/         单元测试和端到端测试
benchmarks/    性能对比脚本
```
