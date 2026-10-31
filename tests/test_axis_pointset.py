"""Axis / PointSet 基础测试"""

import pytest

from strutkit import Axis, PointSet, set_quantum


# ── Axis 构造 ────────────────────────────────────────────────

def test_spans_includes_base():
    a = Axis.spans([3000, 1000, 2000], axis="x")
    assert list(a) == [0.0, 3000.0, 4000.0, 6000.0]
    assert len(a) == 4


def test_spans_without_base():
    y = Axis.spans([2000, 2000], axis="y", include_base=False)
    assert list(y) == [2000.0, 4000.0]


def test_spans_with_base_offset():
    y = Axis.spans([2000], axis="y", base=2000, include_base=False)
    assert list(y) == [4000.0]


def test_step():
    ys = Axis.step(600, 4, axis="y", base=200)
    assert list(ys) == [200.0, 800.0, 1400.0, 2000.0]


def test_points_and_role():
    z = Axis.points([0, 800, 1000, 1800], axis="z",
                    role=["排1前", "排1后", "排2后", "排2前"])
    assert z.role_of("排1后") == 800.0
    assert z.index_of(1800) == 3


def test_role_lookup_missing():
    z = Axis.points([0, 800], axis="z")
    with pytest.raises(KeyError):
        z.role_of("排1后")


def test_axis_must_increase():
    with pytest.raises(ValueError):
        Axis.points([0, 800, 800], axis="z")


def test_role_length_mismatch():
    with pytest.raises(ValueError):
        Axis.points([0, 800], axis="z", role=["a"])


# ── Axis 选择与运算 ─────────────────────────────────────────

def test_slice_keeps_role():
    z = Axis.points([0, 800, 1000, 1800], axis="z", role=list("ABCD"))
    sub = z[1:3]
    assert list(sub) == [800.0, 1000.0]
    assert sub.role == ("B", "C")


def test_concat_vs_union():
    a = Axis.points([0, 1000], axis="y")
    b = Axis.points([2000, 3000], axis="y")
    assert list(a + b) == [0.0, 1000.0, 2000.0, 3000.0]      # 拼接保序
    assert list(a | b) == [0.0, 1000.0, 2000.0, 3000.0]      # 并集同结果
    c = Axis.points([500, 1000], axis="y")
    assert list(a | c) == [0.0, 500.0, 1000.0]
    assert list(a & c) == [1000.0]
    assert list(a - c) == [0.0]


def test_union_drops_role():
    a = Axis.points([0, 1000], axis="y", role=["A", "B"])
    b = Axis.points([2000], axis="y")
    assert (a | b).role is None          # 集合运算后 role 置空


def test_concat_role_needs_both():
    a = Axis.points([0, 1000], axis="y", role=["A", "B"])
    b = Axis.points([2000], axis="y")
    assert (a + b).role is None
    c = Axis.points([2000], axis="y", role=["C"])
    assert (a + c).role == ("A", "B", "C")


def test_concat_requires_increasing():
    a = Axis.points([0, 2000], axis="y")
    b = Axis.points([1000], axis="y")
    with pytest.raises(ValueError, match="严格递增"):
        _ = a + b


def test_shift_and_mirror():
    a = Axis.points([0, 800], axis="z")
    assert list(a.shift(200)) == [200.0, 1000.0]
    assert list(a.mirror(800)) == [800.0, 1600.0]
    assert list(a.mirror(0)) == [-800.0, 0.0]


def test_where():
    a = Axis.spans([1000, 1000, 1000], axis="x")
    assert list(a.where(lambda i, v: i % 2 == 0)) == [0.0, 2000.0]


# ── PointSet ────────────────────────────────────────────────

def test_cartesian_product():
    X = Axis.points([0, 1000], axis="x")
    Z = Axis.points([0, 800], axis="z")
    P = X * Z
    assert P.shape == (2, 2)
    assert P.count() == 4
    pts = list(P.points())
    assert (0.0, 0.0, 0.0) in pts and (1000.0, 0.0, 800.0) in pts


def test_three_axis_product():
    X = Axis.points([0, 1000], axis="x")
    Z = Axis.points([0], axis="z")
    Y = Axis.points([0, 2000, 4000], axis="y")
    P = X * Z * Y
    assert P.shape == (2, 1, 3)
    assert P.count() == 6


def test_mask_leaves_hole():
    X = Axis.points([0, 1000, 2000], axis="x")
    Z = Axis.points([0, 800], axis="z")
    P = (X * Z).mask(lambda p: not (p[0] == 1000 and p[2] == 0))
    assert P.count() == 5


def test_at_fixes_axis():
    X = Axis.points([0, 1000, 2000], axis="x")
    Z = Axis.points([0, 800], axis="z")
    P = (X * Z).at(z=1)
    assert P.count() == 3
    assert all(p[2] == 800.0 for p in P.points())


def test_pointset_union_requires_same_layout():
    X = Axis.points([0, 1000], axis="x")
    Z = Axis.points([0], axis="z")
    Y = Axis.points([0], axis="y")
    with pytest.raises(ValueError):
        _ = (X * Z) | (X * Y)


def test_pointset_union_keeps_structure():
    X1 = Axis.points([0, 1000], axis="x")
    X2 = Axis.points([2000], axis="x")
    Z = Axis.points([0], axis="z")
    u = (X1 * Z) | (X2 * Z)
    assert u.count() == 3
    assert {p[0] for p in u.points()} == {0.0, 1000.0, 2000.0}


def test_shift_pointset():
    X = Axis.points([0, 1000], axis="x")
    Y = Axis.points([0, 2000], axis="y")
    P = (X * Y).shift(z=-200)
    assert all(p[2] == -200.0 for p in P.points())


# ── 量化 ────────────────────────────────────────────────────

def test_quantum_default():
    a = Axis.points([1033.55], axis="y")
    # 0.1mm 量化 → 1033.6
    assert list(a) == [pytest.approx(1033.6)]


def test_quantum_switch_and_restore():
    set_quantum(1.0)
    try:
        a = Axis.points([1033.4], axis="y")
        assert list(a) == [1033.0]
    finally:
        set_quantum(0.1)