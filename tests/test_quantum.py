"""验收测试 4：量化

量化 = 入库前舍入到固定网格，之后只存整数、精确比较。
与「容差合并」的区别：一次决定，永久确定，不存在传递性问题。
"""

import pytest

from strutkit import Axis, ConflictError, Model, get_quantum, set_quantum


@pytest.fixture(autouse=True)
def _restore_quantum():
    old = get_quantum()
    yield
    set_quantum(old)


def test_fraction_is_quantized_deterministically():
    """1/3 跨：量化到 0.1mm 得 2333.3，两次结果相同"""
    a = Axis.points([7000 / 3], axis="x")
    b = Axis.points([7000 / 3], axis="x")
    assert list(a) == [2333.3]
    assert a == b


def test_float_noise_collapses_to_same_node():
    """10/3*3 与 10 在浮点上不等，量化后必须是同一个节点"""
    m = Model()
    G = m.define("G")
    G.add((0, 0, 0), (10 / 3 * 3, 0, 0))
    with pytest.raises(ConflictError):
        G.add((0, 0, 0), (10, 0, 0))     # 撞车 → 说明落到了同一个点
    assert len(m.nodes) == 2


def test_quantum_1mm_rounds_half_up():
    set_quantum(1.0)
    assert list(Axis.points([1033.5], axis="y")) == [1034.0]
    assert list(Axis.points([1033.4], axis="y")) == [1033.0]
    assert list(Axis.points([-1033.5], axis="y")) == [-1034.0]


def test_quantum_01mm():
    set_quantum(0.1)
    assert list(Axis.points([1033.55], axis="y")) == [1033.6]
    assert list(Axis.points([1033.54], axis="y")) == [1033.5]


def test_quantum_rejects_bad_value():
    with pytest.raises(ValueError):
        set_quantum(0)
    with pytest.raises(ValueError):
        set_quantum(-1)


def test_quantum_affects_node_identity():
    """精度变了，同一批坐标的节点数可能不同（这就是 quantum 不可事后修改的原因）"""
    set_quantum(0.1)
    m1 = Model()
    G1 = m1.define("G")
    G1.add((0, 0, 0), (1000.04, 0, 0))
    G1.add((1000.04, 0, 0), (2000, 0, 0))
    assert len(m1.nodes) == 3          # 1000.04 → 1000.0，与第二根共享

    set_quantum(1.0)
    m2 = Model()
    G2 = m2.define("G")
    G2.add((0, 0, 0), (1000.04, 0, 0))
    G2.add((1000.04, 0, 0), (2000, 0, 0))
    assert len(m2.nodes) == 3          # 1000.04 → 1000，同样共享


def test_near_pair_reported():
    """两个点在量化后仍然很近但不重合时，报告要提示"""
    set_quantum(0.1)
    m = Model()
    G = m.define("G")
    # 0.5mm 的差别小于 1mm 但大于一个量化步长（0.1mm），两个独立节点
    G.add((0, 0, 0), (1000.0, 0, 0))
    G.add((1000.5, 0, 0), (2000.0, 0, 0))
    assert len(m.nodes) == 4
    text = m.report()
    assert "量化近似点" in text


def test_near_pair_skipped_is_declared(monkeypatch):
    """跳过扫描时，报告必须写「未检查」，不能写成「0 个」。

    「没查」伪装成「查过没问题」是诊断工具最坏的失败方式。
    索引开启后按格子查（O(n) 而非 O(n²)），不再受节点数上限约束，
    所以「未检查」只会出现在关闭索引（cell_mm=None）的全表扫分支。
    """
    import strutkit.diagnostics as R

    m = Model(cell_mm=None)                  # 关闭索引 → 全表扫，受上限约束
    m.define("G").add((0, 0, 0), (1000, 0, 0))
    monkeypatch.setattr(R, "NEAR_PAIRS_LIMIT", 1)
    assert "未检查" in m.report()

    m2 = Model()                              # 索引开启 → 真的查了，如实报数
    m2.define("G").add((0, 0, 0), (1000, 0, 0))
    text = m2.report()
    assert "未检查" not in text
    assert "量化近似点：0" in text