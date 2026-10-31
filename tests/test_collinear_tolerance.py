"""共线判定的容差规格。

背景：坐标在入口处量化到 0.1mm 网格，量化不是线性映射，
「本应共线」的点会被挤出直线。偏离上界 = (q/2)·√3 ≈ 0.87q，
所以 _on_segment 的容差取 1 个量化步长（q）。

本文件钉住四条边界：
  1. 量化造成的偏离仍判为共线
  2. 容差是垂直距离的上界，且含边界
  3. 离端点不足一个容差的点不切（避免微段）
  4. 容差只用于「点—线段」，不用于「点—点」合并
"""

import pytest

from strutkit import Axis, Model, PointSet, get_quantum, set_quantum, to_um


@pytest.fixture(autouse=True)
def _restore_quantum():
    old = get_quantum()
    yield
    set_quantum(old)


def _um(p):
    return tuple(to_um(c) for c in p)


# ─────────────────────────────────────────────────────────────
# 1. 量化造成的偏离，仍然算共线
# ─────────────────────────────────────────────────────────────

def test_quantized_third_point_still_splits():
    """3-4-5 斜杆的 1/3 处：理想坐标 1333.333mm，量化后 1333.3mm。

    偏离直线 0.02mm —— 在容差内，所以必须判为在杆上并打断。
    没有容差时这里会漏切，表现为「图上看着连上、计算里断开」。
    """
    m = Model()
    m.define("BR", split="all").add((0, 0, 0), (3000, 0, 4000))
    m.define("V", split="none").add((1000, 0, 4000 / 3), (1000, 0, 2500))

    brace = [mb for mb in m.members.values() if mb.group == "BR"]
    assert len(brace) == 2, f"斜杆应被打断成两段，实际 {len(brace)} 段"


def test_all_quantized_points_on_a_diagonal_are_detected():
    """斜杆上任意参数位置取点，量化后都应判为在杆上。

    这是容差取 1q 的依据。分母取 199（与 3000、4000 互质），
    保证落点一般不在网格上 —— 用 200 这种整除分母会让测试失去意义。
    """
    m = Model()
    A, B = (0, 0, 0), (3000, 0, 4000)
    p, q = _um(A), _um(B)
    misses = 0
    for i in range(1, 199):
        t = i / 199
        n = _um((A[0] + t * (B[0] - A[0]),
                 A[1] + t * (B[1] - A[1]),
                 A[2] + t * (B[2] - A[2])))
        if not m._on_segment(p, q, n):
            misses += 1
    assert misses == 0


# ─────────────────────────────────────────────────────────────
# 2. 容差是垂直距离的上界，边界含在内
# ─────────────────────────────────────────────────────────────

def test_tolerance_is_inclusive_on_perpendicular_distance():
    """容差 = 1 个量化步长 = 100μm，正好 100μm 算在杆上，101μm 不算。"""
    m = Model()
    p, q = (0, 0, 0), (100_000, 0, 0)          # 100mm 长的水平杆
    assert m._on_segment(p, q, (50_000, 100, 0)) is True
    assert m._on_segment(p, q, (50_000, 101, 0)) is False


def test_tolerance_follows_quantum():
    """容差跟着 set_quantum 走，不写死成 0.1mm。"""
    set_quantum(1.0)                            # 步长 1mm = 1000μm
    m = Model()
    p, q = (0, 0, 0), (100_000, 0, 0)
    assert m._on_segment(p, q, (50_000, 1000, 0)) is True
    assert m._on_segment(p, q, (50_000, 1001, 0)) is False


# ─────────────────────────────────────────────────────────────
# 3. 端点余量：离端点不足一个容差的点不切
# ─────────────────────────────────────────────────────────────

def test_endpoint_margin_blocks_micro_split():
    """距端点 0.05mm（不足 1 个容差）不切，距 0.5mm 切。

    否则会在端点旁边切出一根长度 0.05mm 的微段。
    """
    m = Model()
    p, q = (0, 0, 0), (100_000, 0, 0)
    assert m._on_segment(p, q, (50, 0, 0)) is False
    assert m._on_segment(p, q, (500, 0, 0)) is True


def test_projection_outside_span_is_rejected():
    """投影落在杆的延长线上（不在跨度内）一律不算。"""
    m = Model()
    p, q = (0, 0, 0), (100_000, 0, 0)
    assert m._on_segment(p, q, (150_000, 0, 0)) is False
    assert m._on_segment(p, q, (-1_000, 0, 0)) is False


# ─────────────────────────────────────────────────────────────
# 4. 容差只管「点—线段」，合并仍然是格子判定
# ─────────────────────────────────────────────────────────────

def test_merge_by_grid_cell_not_by_distance():
    """合并判据是「落在同一个格子」，不是「距离小于某个值」。

    相距 0.0002mm 的两点，如果跨在格子边界两侧，不会被合并。
    这条看起来反直觉，但正是它保证了合并是划分（幂等、顺序无关）。
    若改成距离聚类，就会退化成一个不传递的关系。
    """
    assert to_um(0.0499) != to_um(0.0501)        # 0.0002mm 之隔 → 不合并
    assert to_um(0.051) == to_um(0.149)          # 0.098mm 之隔 → 合并


def test_two_near_nodes_stay_distinct_in_model():
    m = Model()
    G = m.define("G", split="all")
    G.add((0.0499, 0, 0), (0.0499, 0, 1000))
    G.add((0.0501, 0, 0), (0.0501, 0, 1000))
    assert len(m.nodes) == 4                     # 两套端点，四个节点


def test_axis_aligned_projection_stays_on_grid():
    """轴对齐方向：垂直投影只改一个坐标，吸附后仍落在网格上。

    这是「轴对齐可以自动吸附、斜杆不行」这条分界线的来源。
    """
    A = Axis.points([0, 1000, 2000], axis="x")
    assert list(A.shift(0.1)) == [0.1, 1000.1, 2000.1]
    # 不足半个量化步长的位移被并入同一个格子
    assert list(A.shift(0.05)) == [0.1, 1000.1, 2000.1]