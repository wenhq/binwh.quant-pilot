"""py_mini_racer stub — 解除 akshare 顶层对 py_mini_racer 的硬依赖.

akshare 1.18.64 顶层 (air/air_zhenqi.py) `from py_mini_racer import MiniRacer`.
py-mini-racer 的 V8 binary 在 macOS arm64 间歇崩溃, 且作为非声明依赖会被 uv sync 移除,
导致 `import akshare` 失败 → 所有 services.data 子模块 import 崩.

本 stub 向 sys.modules 注入空壳 MiniRacer, 使 akshare 可正常 import.
运行时永不调用 MiniRacer: baostock 是 A 股主源 (纯 HTTP), akshare_source 绕过东财走腾讯/新浪
(纯 HTTP), 不触发 V8.

必须在任何 `import akshare` 之前执行 — 由 services/data/__init__.py 第一行导入保证.
"""
import sys
import types

_stub = types.ModuleType("py_mini_racer")
# 空壳类: 构造不报错, 但任何 eval/call 都不会被触达 (业务路径不走东财 V8).
_stub.MiniRacer = type(
    "MiniRacer",
    (),
    {"__init__": lambda self, *args, **kwargs: None},
)
# 无条件覆盖: 即便残留空包已进 sys.modules, 也以本 stub 为准.
sys.modules["py_mini_racer"] = _stub
