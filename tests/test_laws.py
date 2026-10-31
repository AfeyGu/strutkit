"""代数律测试：把「不变式」写成机器能搜索的断言。

与 tests/test_*.py 里那些「例子测试」的分工：
  - 例子测试回答「这一种情况对不对」
  - 本文件回答「是不是所有情况都对」，由 hypothesis 负责搜索反例

生成器只用整数格点（INDEX_GRID × SPAN_MM），坐标天然落在量化网格上，
避免把浮点取整的噪声混进拓扑测试。
"""

from __future__ import annotations

import math

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from strutkit import Axis, ConflictError, Model, PointSet, get_quantum, set_quantum

# ─────────────────────────────────────────────────────────────
# 生成器
# ─────────────────────────────────────────────────────────────

SPAN_MM = 1000
INDEX_GRID = st.integers(0, 3)          # 4×4×4 = 64 个格点
MAX_SEGS = 6

Point = tuple[int, int, int]


def _mm(idx: Point) -> tuple[float, float, float]:
    return (idx[0] * SPAN_MM, idx[1] * SPAN_MM, idx[2] * SPAN_MM)


def _dedup_key(seg) -> tuple:
    """同一组内，无向端点对相同即视为同一根构件（会撞 ConflictError）"""
    group, p, q = seg
    return (group, tuple(sorted((p, q))))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _collinear_overlap(s, t) -> bool:
    """同组两根构件是否共线且重叠。

    这种配置等价于「同一根杆被描述了两遍」，库会抛 ConflictError
    （见 test_overlapping_member_conflicts），所以主生成器要把它排掉，
    否则顺序无关性测试会被合法报错打断。
    """
    _, p1, q1 = s
    _, p2, q2 = t
    d1 = [q1[k] - p1[k] for k in range(3)]
    d2 = [q2[k] - p2[k] for k in range(3)]
    v = [p2[k] - p1[k] for k in range(3)]
    if any(_cross(d1, d2)) or any(_cross(d1, v)):
        return False
    dd = sum(c * c for c in d1)
    lo2 = min(sum(d1[k] * v[k] for k in range(3)),
              sum(d1[k] * (q2[k] - p1[k]) for k in range(3)))
    hi2 = max(sum(d1[k] * v[k] for k in range(3)),
              sum(d1[k] * (q2[k] - p1[k]) for k in range(3)))
    return max(0, lo2) < min(dd, hi2)


def _distinct_spans(segs) -> bool:
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            if _collinear_overlap(segs[i], segs[j]):
                return False
    return True


segments = st.lists(
    st.tuples(
        st.sampled_from(["G"]),
        st.tuples(INDEX_GRID, INDEX_GRID, INDEX_GRID),
        st.tuples(INDEX_GRID, INDEX_GRID, INDEX_GRID),
    ),
    min_size=1,
    max_size=MAX_SEGS,
    unique_by=_dedup_key,
).filter(lambda ss: all(s[1] != s[2] for s in ss)     # 去掉零长构件
         and _distinct_spans(ss))                     # 去掉共线重叠


def build(segs, split="all") -> Model:
    """按给定顺序建模型。split 固定，避免生成器同时扰动两处。"""
    m = Model()
    defined: set[str] = set()
    for group, p, q in segs:
        if group not in defined:
            m.define(group, split=split)
            defined.add(group)
        m.group(group).add(_mm(p), _mm(q))
    return m


def signature(m: Model) -> tuple:
    """与编号无关的指纹。

    刻意排除 member.id / member.origin：编号依赖添加顺序，属于实现细节，
    不是模型的语义。若把它们算进指纹，顺序无关性就永远测不出来。
    """
    nodes = tuple(sorted(tuple(n.xyz) for n in m.nodes.values()))
    members = tuple(sorted(
        (
            mb.group,
            tuple(sorted((m.nodes[mb.i].xyz, m.nodes[mb.j].xyz))),
            tuple(sorted(mb.attrs.items())),
        )
        for mb in m.members.values()
    ))
    return nodes, members


# ─────────────────────────────────────────────────────────────
# 律 1：书写顺序无关
# ─────────────────────────────────────────────────────────────

@settings(max_examples=120, deadline=None)
@given(segs=segments, seed=st.integers(0, 2**31 - 1))
def test_order_independent(segs, seed):
    """同一组构件，任意排列建出的模型必须完全相同。

    这条成立的前提是打断双向维持不变式：新点切旧杆 + 旧点切新杆。
    少做任一侧，某些顺序就会漏切。
    """
    import random

    base = signature(build(segs))
    for _ in range(3):
        shuffled = list(segs)
        random.Random(seed).shuffle(shuffled)
        assert signature(build(shuffled)) == base

    # 逆序是最强的单一扰动：它把「先长后短」和「先短后长」直接对调
    assert signature(build(list(reversed(segs)))) == base


@settings(max_examples=120, deadline=None)
@given(segs=segments)
def test_split_is_complete(segs):
    """打断完成后，构件内部不应再存在「允许打断它」的节点。

    这是 INV 不变式的通用版本；diagnostics.py 的 inv_violations 是它的报告形态。
    """
    m = build(segs, split="all")
    for mb in m.members.values():
        p, q = m.nodes[mb.i].xyz, m.nodes[mb.j].xyz
        for node in m.nodes.values():
            if node.id in (mb.i, mb.j):
                continue
            assert not m._on_segment(p, q, node.xyz), (
                f"构件 {mb.group} 内部仍有节点 {node.point} 未被打断"
            )


def test_overlapping_member_conflicts():
    """同组共线且重叠的两根构件 = 同一根杆描述了两遍，必须报错。

    不加这道闸，打断会产出一段与已有构件完全重合的构件，
    _poskey 被静默覆盖 → 构件数比位置键多 → 之后 remove()/merge() 会错删。
    """
    m = Model()
    G = m.define("G", split="all")
    G.add((0, 0, 0), (0, 0, 3000))
    with pytest.raises(ConflictError):
        G.add((0, 0, 1000), (0, 0, 2000))       # 被完全包含

    # 反序必须同样报错，否则顺序无关性就在这里破了个洞
    m2 = Model()
    G2 = m2.define("G", split="all")
    G2.add((0, 0, 1000), (0, 0, 2000))
    with pytest.raises(ConflictError):
        G2.add((0, 0, 0), (0, 0, 3000))         # 包含别人


def test_overlap_allowed_across_groups():
    """不同组共线重叠是允许的：位置键含组名，它们是两根独立的杆。

    只校验不重复段这个核心不变式 —— 构件总数会因打断而变（A 被切成 3 段
    再加 B 一段，共 4 段），那个数字不是这里要断言的东西。
    """
    m = Model()
    m.define("A", split="all").add((0, 0, 0), (0, 0, 3000))
    m.define("B", split="all").add((0, 0, 1000), (0, 0, 2000))

    keys = [(mb.group, min(mb.i, mb.j), max(mb.i, mb.j)) for mb in m.members.values()]
    assert len(keys) == len(set(keys)), "同组出现了重合段"
    assert len(m._poskey) == len(m.members)     # 位置键与构件一一对应


# ─────────────────────────────────────────────────────────────
# 律 2：打断保持连通性
# ─────────────────────────────────────────────────────────────

def _components(m: Model) -> int:
    parent: dict[int, int] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for mb in m.members.values():
        a, b = find(mb.i), find(mb.j)
        if a != b:
            parent[a] = b
    return len({find(n) for n in m.nodes if m.nodes[n].sources})


@settings(max_examples=80, deadline=None)
@given(segs=segments)
def test_split_creates_no_new_nodes(segs):
    """打断只搬运已有节点，不造新点。

    切点必须是模型里已经存在的节点；若打断能凭空造点，
    坐标就不再只由用户输入决定，量化体系也就不封闭了。
    """
    a = build(segs, split="all")
    b = build(segs, split="none")
    assert {n.xyz for n in a.nodes.values()} == {n.xyz for n in b.nodes.values()}


@settings(max_examples=80, deadline=None)
@given(segs=segments)
def test_split_only_connects_never_disconnects(segs):
    """打断可以把两条交叉的杆接起来（这正是它的目的），但绝不能把杆断开。

    所以连通分量数满足单调性：打断后 ≤ 打断前。
    """
    with_split = build(segs, split="all")
    without = build(segs, split="none")
    assert _components(with_split) <= _components(without)


# ─────────────────────────────────────────────────────────────
# 律 3：添加是幂等的（重复即冲突）
# ─────────────────────────────────────────────────────────────

@settings(max_examples=80, deadline=None)
@given(segs=segments)
def test_duplicate_member_conflicts(segs):
    """同一位置同一组再加一次，必须抛 ConflictError，不能静默变成两根。"""
    group, p, q = segs[0]
    m = build(segs)
    with pytest.raises(ConflictError):
        m.group(group).add(_mm(p), _mm(q))
    # 反方向也算同一根（位置键是无向的）
    with pytest.raises(ConflictError):
        m.group(group).add(_mm(q), _mm(p))


# ─────────────────────────────────────────────────────────────
# 律 4：PointSet 的集合运算
# ─────────────────────────────────────────────────────────────

def _ps(coords_um) -> PointSet:
    """直接用 μm 坐标造单点集，避免量化干扰"""
    pts = [tuple(c / 1000 for c in cc) for cc in coords_um]
    return PointSet.of(pts)


@given(
    pts=st.lists(
        st.tuples(st.integers(0, 5000), st.integers(0, 5000), st.integers(0, 5000)),
        min_size=1,
        max_size=6,
        unique=True,
    )
)
def test_union_idempotent(pts):
    """P | P == P（幂等）"""
    P = _ps(pts)
    assert (P | P).count() == P.count()
    assert set((P | P).points()) == set(P.points())


@given(
    pts=st.lists(
        st.tuples(st.integers(0, 5000), st.integers(0, 5000), st.integers(0, 5000)),
        min_size=1,
        max_size=6,
        unique=True,
    )
)
def test_intersection_idempotent(pts):
    """P & P == P（幂等）"""
    P = _ps(pts)
    assert set((P & P).points()) == set(P.points())


@given(
    a=st.lists(st.integers(0, 5000), min_size=1, max_size=4, unique=True),
    b=st.lists(st.integers(0, 5000), min_size=1, max_size=4, unique=True),
)
def test_offset_survives_set_ops(a, b):
    """平移过的点集做并集，平移量必须保留。

    这是一条曾经真实违反过的律：_set_op 重建 PointSet 时丢掉了 offset，
    于是 keep 用「带偏移的坐标」去匹配「不带偏移的坐标」，结果静默为空集。
    """
    P = PointSet.of([(x, 0, 0) for x in a]).shift(z=500)
    Q = PointSet.of([(x, 0, 0) for x in b]).shift(z=500)
    R = P | Q
    assert R.offset == P.offset
    assert R.count() > 0
    assert all(abs(p[2] - 500) < 1e-9 for p in R.points())


@given(
    a=st.lists(st.integers(0, 5000), min_size=1, max_size=4, unique=True),
    b=st.lists(st.integers(0, 5000), min_size=1, max_size=4, unique=True),
)
def test_union_commutative(a, b):
    """P | Q == Q | P"""
    P = PointSet.of([(x, 0, 0) for x in a])
    Q = PointSet.of([(x, 0, 0) for x in b])
    assert set((P | Q).points()) == set((Q | P).points())


# ─────────────────────────────────────────────────────────────
# 律 5：Axis 的变换
# ─────────────────────────────────────────────────────────────

@given(coords=st.lists(st.integers(0, 5000), min_size=1, max_size=5, unique=True))
def test_mirror_twice_is_identity(coords):
    """镜像两次回到原位（对合律）"""
    A = Axis.points(sorted(float(c) for c in coords), axis="x")
    assert list(A.mirror(1500).mirror(1500)) == list(A)


@given(
    coords=st.lists(st.integers(0, 5000), min_size=1, max_size=4, unique=True),
    a=st.floats(-200, 200, allow_nan=False, allow_infinity=False),
    b=st.floats(-200, 200, allow_nan=False, allow_infinity=False),
)
def test_shift_composition_is_quantized(coords, a, b):
    """连续两次平移 ≈ 一次合成平移，误差不超过一个量化步长。

    为什么不是严格相等：量化不是平移群的同态，
    to_um(a) + to_um(b) 一般 ≠ to_um(a+b)。这是离散化的固有代价，
    不是 bug —— 本测试把它钉成「误差有界」，防止将来无声放大。
    """
    A = Axis.points(sorted(float(c) for c in coords), axis="x")
    twice = list(A.shift(a).shift(b))
    once = list(A.shift(a + b))
    tol = get_quantum()
    for x, y in zip(twice, once):
        assert abs(x - y) <= tol + 1e-9


@given(coords=st.lists(st.integers(0, 5000), min_size=2, max_size=5, unique=True))
def test_axis_set_ops_drop_role_consistently(coords):
    """集合运算后 role 一律丢弃 —— 这是刻意约定，不是遗漏。

    若哪天改成「保留 role」，这条会失败，提醒同步修改文档里的约定。
    值层面的幂等仍然成立。
    """
    cs = sorted(float(c) for c in coords)
    A = Axis.points(cs, axis="x", role=[f"r{i}" for i in range(len(cs))])
    assert (A | A).role is None
    assert (A & A).role is None
    assert list((A | A)) == cs