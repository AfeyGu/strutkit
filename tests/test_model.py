"""Model / Group：添加、打断、split 策略、冲突、删除、合并"""

import pytest

from strutkit import Axis, ConflictError, Model


def _m():
    return Model()


# ── 基本 ────────────────────────────────────────────────────

def test_add_single():
    m = _m()
    G = m.define("G")
    G.add((0, 0, 0), (0, 0, 1000))
    assert len(m.members) == 1
    assert len(m.nodes) == 2


def test_zero_length_rejected():
    m = _m()
    G = m.define("G")
    with pytest.raises(ValueError, match="零长"):
        G.add((0, 0, 0), (0, 0, 0))


def test_duplicate_rejected():
    m = _m()
    G = m.define("G")
    G.add((0, 0, 0), (0, 0, 1000))
    with pytest.raises(ConflictError):
        G.add((0, 0, 0), (0, 0, 1000))
    # 反向同一条线也算重复
    with pytest.raises(ConflictError):
        G.add((0, 0, 1000), (0, 0, 0))


def test_group_attrs_applied():
    m = _m()
    G = m.define("G", attrs={"layer": "L1", "section": "S1"})
    mb = G.add((0, 0, 0), (1000, 0, 0))
    assert mb.attrs["layer"] == "L1"
    assert mb.attrs["section"] == "S1"


def test_group_keys_schema():
    m = _m()
    G = m.define("G", keys={"layer": str})
    with pytest.raises(KeyError, match="不认识属性"):
        G.add((0, 0, 0), (1000, 0, 0), layar="typo")


# ── 打断 ────────────────────────────────────────────────────

def test_split_by_endpoint_inside():
    m = _m()
    COL = m.define("COL", split="all")
    BEAM = m.define("BEAM", split="none")
    COL.add((0, 0, 0), (0, 0, 5000))
    BEAM.add((0, 0, 2000), (3000, 0, 2000))
    assert COL.count() == 2                     # 柱被切成两段
    assert BEAM.count() == 1


def test_split_none_never_splits():
    m = _m()
    COL = m.define("COL", split="none")
    BEAM = m.define("BEAM", split="none")
    COL.add((0, 0, 0), (0, 0, 5000))
    BEAM.add((0, 0, 2000), (3000, 0, 2000))
    assert COL.count() == 1                     # 不切


def test_split_order_independent():
    """先梁后柱，柱照样被切"""
    m = _m()
    COL = m.define("COL", split="all")
    BEAM = m.define("BEAM", split="none")
    BEAM.add((0, 0, 2000), (3000, 0, 2000))
    COL.add((0, 0, 0), (0, 0, 5000))
    assert COL.count() == 2


def test_crossing_splits_only_when_both_sides_allow():
    """X 形交叉：双方都放行才在交点断开；单向放行等于白断（断了一边没连上）"""
    def build(col_split, beam_split):
        m = _m()
        COL = m.define("COL", split=col_split)
        BEAM = m.define("BEAM", split=beam_split)
        for x in (0, 3000, 6000):
            COL.add((x, 0, 0), (x, 0, 3000))
        BEAM.add((0, 0, 1500), (6000, 0, 1500))     # 中间那根柱是被"穿过"的
        return COL, BEAM, m

    COL, BEAM, m = build("all", ["COL"])            # 双向放行
    assert (COL.count(), BEAM.count()) == (6, 2)
    assert m._xsplit == 1

    COL, BEAM, m = build("none", ["COL"])           # 柱不放行 → 什么都不做
    assert (COL.count(), BEAM.count()) == (3, 1)
    assert m._xsplit == 0


def test_cell_mm_validation_and_equivalence():
    """cell_mm 只影响速度：非法值报错，不同大小建出的模型必须完全一致"""
    with pytest.raises(ValueError):
        Model(cell_mm=0)
    with pytest.raises(ValueError):
        Model(cell_mm=-5)
    Model(cell_mm=None)                      # 关闭索引 = 全表扫

    def build(cell):
        m = Model(cell_mm=cell)
        C = m.define("C", split="all")
        B = m.define("B", split=["C"])
        for x in (0, 2000, 4000):
            C.add((x, 0, 0), (x, 0, 6000))
        B.add((0, 0, 3000), (4000, 0, 3000))     # 穿过中间柱
        return m

    def fingerprint(m):
        return (sorted(tuple(n.xyz) for n in m.nodes.values()),
                sorted((mb.group, m.nodes[mb.i].xyz, m.nodes[mb.j].xyz)
                       for mb in m.members.values()))

    a = fingerprint(build(None))
    b = fingerprint(build(500.0))
    c = fingerprint(build(9000.0))
    assert a == b == c


def test_split_string_is_rejected():
    """split 写成字符串要立刻报错：它会被当成字符集合，白名单静默失效"""
    m = _m()
    with pytest.raises(ValueError, match="组名白名单要写成列表"):
        m.define("X", split="COL")          # 少写了方括号
    m.define("A", split="none")             # 合法取值照常
    m.define("B", split="all")
    m.define("C", split=["A"])


def test_split_whitelist():
    """只允许被 BEAM 打断：斜撑端点落在柱上不切，梁端点落在柱上才切"""
    m = _m()
    COL   = m.define("COL", split=["BEAM"])
    BEAM  = m.define("BEAM", split="none")
    BRACE = m.define("BRACE", split="none")
    COL.add((0, 0, 0), (0, 0, 5000))
    BRACE.add((0, 0, 3000), (1000, 0, 3000))    # 斜撑，不在白名单 → 不切
    assert COL.count() == 1
    BEAM.add((0, 0, 2000), (1000, 0, 2000))     # 梁，在白名单 → 切
    assert COL.count() == 2


def test_split_ends_written_to_new_joint():
    m = _m()
    COL = m.define("COL", split="all", ends={"i": "铰接", "j": "自由"},
                   split_ends="刚接")
    BEAM = m.define("BEAM", split="none")
    COL.add((0, 0, 0), (0, 0, 4000))
    BEAM.add((0, 0, 2000), (1000, 0, 2000))
    segs = sorted(COL.all(), key=lambda s: m.nodes[s.i].xyz[2])
    assert len(segs) == 2
    assert segs[0].ends["i"] == "铰接"          # 保留原 i 端
    assert segs[0].ends["j"] == "刚接"          # 新接缝
    assert segs[1].ends["i"] == "刚接"          # 新接缝
    assert segs[1].ends["j"] == "自由"          # 保留原 j 端


def test_split_ends_none_by_default():
    m = _m()
    COL = m.define("COL", split="all")
    BEAM = m.define("BEAM", split="none")
    COL.add((0, 0, 0), (0, 0, 4000))
    BEAM.add((0, 0, 2000), (1000, 0, 2000))
    segs = COL.all()
    assert all(s.ends.get("i") is None for s in segs)   # 不猜


def test_split_end_in_the_middle_chain():
    """柱被梁和斜撑同时打断，切成 3 段"""
    m = _m()
    COL = m.define("COL", split="all")
    X1 = m.define("X1", split="none")
    X2 = m.define("X2", split="none")
    COL.add((0, 0, 0), (0, 0, 5000))
    X1.add((0, 0, 2000), (1000, 0, 2000))
    X2.add((0, 0, 4000), (1000, 0, 4000))
    assert COL.count() == 3


def test_origin_shared_by_segments():
    m = _m()
    COL = m.define("COL", split="all")
    BEAM = m.define("BEAM", split="none")
    COL.add((0, 0, 0), (0, 0, 4000))
    BEAM.add((0, 0, 2000), (1000, 0, 2000))
    segs = COL.all()
    assert len({s.origin for s in segs}) == 1     # 同一根


# ── 节点属性 ────────────────────────────────────────────────

def test_node_attrs():
    m = _m()
    m.node((0, 0, 0), attrs={"支座": "铰接"})
    G = m.define("G")
    G.add((0, 0, 0), (0, 0, 1000))
    nd = [n for n in m.nodes.values() if n.xyz == (0, 0, 0)][0]
    assert nd.attrs["支座"] == "铰接"


# ── 删除 ────────────────────────────────────────────────────

def test_remove_does_not_merge_back():
    m = _m()
    COL = m.define("COL", split="all")
    BEAM = m.define("BEAM", split="none")
    COL.add((0, 0, 0), (0, 0, 4000))
    beam = BEAM.add((0, 0, 2000), (1000, 0, 2000))
    assert COL.count() == 2
    m.remove([beam])
    assert COL.count() == 2          # 删除不会自动合并
    assert len(m.members) == 2


# ── 合并 ────────────────────────────────────────────────────

def test_merge_roundtrip():
    m = _m()
    COL = m.define("COL", split="all", ends={"i": "铰接", "j": "固定"},
                   split_ends="刚接")
    BEAM = m.define("BEAM", split="none")
    COL.add((0, 0, 0), (0, 0, 4000))
    beam = BEAM.add((0, 0, 2000), (1000, 0, 2000))
    assert COL.count() == 2

    m.remove([beam])                  # 先删掉梁，断点才「孤立」
    n = m.merge_orphans()
    assert n == 1
    assert COL.count() == 1
    seg = COL.all()[0]
    assert seg.ends["i"] == "铰接"
    assert seg.ends["j"] == "固定"


def test_merge_requires_no_other_member_at_joint():
    m = _m()
    COL = m.define("COL", split="all")
    BEAM = m.define("BEAM", split="none")
    COL.add((0, 0, 0), (0, 0, 4000))
    BEAM.add((0, 0, 2000), (1000, 0, 2000))
    assert m.merge_orphans() == 0      # 该节点上还有梁，不能合并
    assert COL.count() == 2


def test_merge_different_origin_rejected():
    m = _m()
    G = m.define("G", split="all")
    G.add((0, 0, 0), (0, 0, 1000))
    G.add((0, 0, 1000), (0, 0, 2000))
    a, b = G.all()
    with pytest.raises(ValueError, match="origin"):
        m.merge(a, b)


# ── 批量 ────────────────────────────────────────────────────

def test_add_pairs_shape_mismatch():
    m = _m()
    X = Axis.points([0, 1000], axis="x")
    Y = Axis.points([0, 1000, 2000], axis="y")
    G = m.define("G")
    with pytest.raises(ValueError, match="形状"):
        G.add_pairs(X * Y, (X * Y).at(y=0))


def test_add_pairs_atomic():
    """批量里有一根重位 → 整批拒绝，一根都不加"""
    from strutkit import PointSet
    m = _m()
    G = m.define("G")
    G.add((0, 0, 0), (1000, 0, 0))
    P1 = PointSet.of([(0, 0, 0), (5000, 0, 0)])        # 第一根会冲突
    P2 = PointSet.of([(1000, 0, 0), (2000, 0, 0)])
    with pytest.raises(ConflictError):
        G.add_pairs(P1, P2)
    assert G.count() == 1                               # 第二根也没加进去（整批原子）


# ── 点阵批量 ────────────────────────────────────────────────

def test_add_chain():
    m = _m()
    X = Axis.points([0, 1000, 2000], axis="x")
    Z = Axis.points([0, 800], axis="z")
    Y = Axis.points([1000], axis="y")
    G = m.define("G")
    G.add_chain(X * Z * Y, along="x")
    assert G.count() == 4          # 2 条线 × 2 跨


def test_add_x():
    m = _m()
    X = Axis.points([0, 1000], axis="x")
    Y = Axis.points([0, 1000], axis="y")
    G = m.define("G")
    G.add_X(X * Y)
    assert G.count() == 2


def test_add_zigzag():
    m = _m()
    Z = Axis.points([0, 800], axis="z")
    Y = Axis.points([0, 600, 1200], axis="y")
    G = m.define("G")
    G.add_zigzag(Z * Y, along="y")
    assert G.count() == 2          # 2 格，每格 1 根


def test_add_chain_multidim_requires_along():
    m = _m()
    X = Axis.points([0, 1000], axis="x")
    Y = Axis.points([0, 1000], axis="y")
    G = m.define("G")
    with pytest.raises(KeyError):
        G.add_chain(X * Y, along="z")     # 没有 z 维