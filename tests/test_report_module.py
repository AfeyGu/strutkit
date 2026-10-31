"""模块命名与输出编码的约定。

两条都是「看起来没问题、实际会静默出错」的类型，所以钉成测试：

1. 包里的 `report` 是函数，子模块必须另有名字。
   若子模块也叫 report，`import strutkit.report as R` 会拿到函数而不是模块，
   而且没有任何提示。

2. 报告里的字符必须能编码成 GBK。
   中文 Windows 控制台默认 GBK，`print(m.report())` 遇到 GBK 编不出的字符会抛
   UnicodeEncodeError —— 恰好发生在最需要看报告的时候。
"""

import importlib
import io

import pytest

from strutkit import Model
from strutkit import report as report_func


def _messy_model() -> Model:
    """尽量把报告里的每个分支都触发一遍：未打断、短段、近似点、切点来源、负标高。

    INV 保持通过 —— 需要违规分支的测试用下面的 _violating_model。
    """
    m = Model()
    G = m.define("G", split="all")
    G.add((0, 0, 0), (0, 0, 3000))
    N = m.define("N", split="none")          # 不允许打断 → 触发「内部有节点但未打断」
    N.add((0, 0, 1500), (1000, 0, 1500))
    m.define("S", split="all").add((0, 0, 100), (500, 0, 100))   # 400mm，不触发短段
    m.node((3000, 0, 3000), attrs={"support": True})
    return m


def _violating_model() -> Model:
    """故意造一条 INV 违反：显式 node() 不带 as_group，不触发打断，
    但节点的组策略里 split='all' → 该节点的存在就是违规。"""
    m = Model()
    G = m.define("G", split="all")
    G.add((0, 0, 0), (0, 0, 3000))
    m.node((0, 0, 2500))                     # 落在 G 的杆内部，但不参与打断
    return m


# ─────────────────────────────────────────────────────────────
# 1. 模块名不与包级函数冲突
# ─────────────────────────────────────────────────────────────

def test_package_exports_report_function():
    assert callable(report_func)


def test_diagnostics_is_the_module_not_the_function():
    mod = importlib.import_module("strutkit.diagnostics")
    assert mod is not report_func
    assert getattr(mod, "report") is report_func


def test_old_module_name_is_gone():
    """旧的 strutkit.report 子模块已不存在。

    宁可明确模块找不到，也不要静默返回一个同名函数 ——
    后者会让人以为 `R.report(...)` 是在调用模块里的函数，实际不是。
    """
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("strutkit.report")


# ─────────────────────────────────────────────────────────────
# 2. 报告输出必须能打印到 GBK 控制台
# ─────────────────────────────────────────────────────────────

def test_report_is_gbk_encodable():
    for m in (_messy_model(), _violating_model()):
        m.report().encode("gbk")     # 编不出就抛 UnicodeEncodeError


def test_normal_report_is_gbk_encodable():
    m = Model()
    m.define("COL", split="all").add((0, 0, 0), (0, 0, 5000))
    m.report().encode("gbk")


def test_report_text_uses_gbk_safe_markers():
    """健康/失败标记用 GBK 里有的 √ 和 ×，不用 ✗（U+2717 不在 GBK）。"""
    assert "INV: OK" in _messy_model().report()

    text = _violating_model().report()
    assert "INV: ×" in text
    assert "\u2717" not in text and "\u2713" not in text