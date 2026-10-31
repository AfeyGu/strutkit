"""验收测试 3：合并是打断的逆运算

打断：两端继承原件，中间填 split_ends
合并：只保留最左 i 端和最右 j 端，中间那两端丢弃
"""

from strutkit import Model


def _build():
    m = Model()
    COL  = m.define("COL",  split="all",   ends={"i": "铰接", "j": "固定"},
                    split_ends="刚接")
    BEAM = m.define("BEAM", split="none")
    COL.add((0, 0, 0), (0, 0, 6000))
    b1 = BEAM.add((0, 0, 2000), (3000, 0, 2000))
    b2 = BEAM.add((0, 0, 4000), (3000, 0, 4000))
    return m, COL, BEAM, b1, b2


def test_split_three_segments():
    m, COL, _, _, _ = _build()
    assert COL.count() == 3
    segs = sorted(COL.all(), key=lambda s: m.nodes[s.i].xyz[2])
    # 第 1 段：原 i 端 = 铰接，接缝 = 刚接
    assert segs[0].ends["i"] == "铰接"
    assert segs[0].ends["j"] == "刚接"
    # 中间段：两端都是接缝
    assert segs[1].ends["i"] == "刚接"
    assert segs[1].ends["j"] == "刚接"
    # 末段：接缝 + 原 j 端
    assert segs[2].ends["i"] == "刚接"
    assert segs[2].ends["j"] == "固定"


def test_merge_roundtrip_restores_original():
    m, COL, BEAM, b1, b2 = _build()
    assert COL.count() == 3
    m.remove([b1, b2])                       # 先删掉梁，断点才「孤立」
    n = m.merge_orphans()
    assert n == 2                            # 3 段 → 2 次合并
    assert COL.count() == 1
    seg = COL.all()[0]
    assert seg.ends["i"] == "铰接"            # 两端复原
    assert seg.ends["j"] == "固定"
    assert m.nodes[seg.i].point == (0.0, 0.0, 0.0)
    assert m.nodes[seg.j].point == (0.0, 0.0, 6000.0)


def test_merge_orphans_refuses_when_joint_still_used():
    m, COL, _, _, _ = _build()
    assert m.merge_orphans() == 0            # 接缝上还连着梁，不能合
    assert COL.count() == 3


def test_merge_explicit_discards_middle_ends():
    m, COL, _, b1, b2 = _build()
    segs = sorted(COL.all(), key=lambda s: m.nodes[s.i].xyz[2])
    m.remove([b1, b2])
    merged = m.merge(segs[0], segs[1])
    assert merged.ends["i"] == "铰接"         # 保留最左
    assert merged.ends["j"] == "刚接"         # 保留最右（这是第二段的 j，即接缝 2）


def test_merge_rejects_different_origin():
    m = Model()
    G = m.define("G", split="all")
    G.add((0, 0, 0), (0, 0, 1000))
    G.add((0, 0, 1000), (0, 0, 2000))
    a, b = G.all()
    try:
        m.merge(a, b)
    except ValueError as e:
        assert "origin" in str(e)
    else:
        raise AssertionError("应当拒绝不同 origin 的合并")


def test_delete_leaves_isolated_joint_visible():
    """删构件不会自动合并，但孤立断点必须在报告里出现"""
    m, COL, BEAM, b1, b2 = _build()
    m.remove([b1, b2])
    text = m.report()
    assert "孤立断点（可 merge_orphans 合并）" in text
    assert COL.count() == 3