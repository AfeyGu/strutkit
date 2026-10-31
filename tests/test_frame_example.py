"""多层框架 + 次梁：主梁刚接、次梁铰接

柱网 3 跨 × 2 跨，4 层。验证：
  - 双向主梁都布置（X 向 36 根、Y 向 32 根）
  - X 向主梁被次梁从跨内三分点打断（每根 3 段）
  - Y 向主梁和次梁都不被打断
  - 主梁全刚接、次梁全铰接
  - split 白名单写错时，报告必须报「内部有节点但未打断」而不是静默
"""

from collections import Counter

from frame_demo import build


def test_counts():
    m, COL, MBX, MBY, SEC = build()
    assert len(m.nodes) == 132
    assert len(m.members) == 236
    assert COL.count() == 48         # 12 根柱 × 4 层
    assert MBX.count() == 108        # 36 根 × 3 段
    assert MBY.count() == 32         # 32 根 × 1 段
    assert SEC.count() == 48         # 48 根 × 1 段


def test_both_directions_have_main_beams():
    """双向都有主梁：X 向 3 条 Y 线 × 3 跨 × 4 层，Y 向 4 条 X 线 × 2 跨 × 4 层"""
    m, _COL, MBX, MBY, _SEC = build()
    assert len(MBX.all()) > 0 and len(MBY.all()) > 0
    # 按 origin 聚合，确认每根原构件都被生成过
    assert len({mb.origin for mb in MBX.all()}) == 36
    assert len({mb.origin for mb in MBY.all()}) == 32


def test_x_main_beams_split_at_thirds():
    """X 向主梁在跨内三分点（x = 2000 / 4000）被次梁打断 → 每根 3 段"""
    m, _COL, MBX, _MBY, _SEC = build()
    seg_count = Counter(mb.origin for mb in MBX.all())
    assert set(seg_count.values()) == {3}

    # 每根主梁的中间接缝必须落在 2000 / 4000 / 8000 / 10000 / 14000 / 16000
    expected_cuts = {2000.0, 4000.0, 8000.0, 10000.0, 14000.0, 16000.0}
    seen = set()
    for mb in MBX.all():
        for p in (m.nodes[mb.i].point, m.nodes[mb.j].point):
            if p[0] in expected_cuts:
                seen.add(p[0])
    assert seen == expected_cuts


def test_y_main_beams_not_split():
    """Y 向主梁在柱线上，次梁碰不到它"""
    m, _COL, _MBX, MBY, _SEC = build()
    seg_count = Counter(mb.origin for mb in MBY.all())
    assert set(seg_count.values()) == {1}


def test_secondary_not_split():
    """次梁永不被打断：每根都跨 1 个 Y 跨"""
    m, _COL, _MBX, _MBY, SEC = build()
    seg_count = Counter(mb.origin for mb in SEC.all())
    assert set(seg_count.values()) == {1}
    for mb in SEC.all():
        a, b = m.nodes[mb.i].point, m.nodes[mb.j].point
        assert abs(b[1] - a[1]) == 6000


def test_end_conditions():
    """主梁（含被断开的段）全刚接；次梁全铰接"""
    m, COL, MBX, MBY, SEC = build()
    for grp, expect in ((COL, "刚接"), (MBX, "刚接"), (MBY, "刚接"), (SEC, "铰接")):
        for mb in grp.all():
            assert mb.ends["i"] == expect, f"{grp.name} 端部条件不对"
            assert mb.ends["j"] == expect, f"{grp.name} 端部条件不对"


def test_no_unspecified_ends():
    m, *_ = build()
    bad = [mb for mb in m.members.values()
           if mb.ends.get("i") is None or mb.ends.get("j") is None]
    assert bad == []


def test_inv_and_connectivity():
    from strutkit import inv_violations
    from strutkit.diagnostics import _components

    m, *_ = build()
    assert inv_violations(m) == []
    assert _components(m) == 1


def test_whitelist_typo_is_reported():
    """反例：把 X 向主梁的白名单写成 Y 向主梁（次梁不在里面），
    主梁就不会被打断，但报告必须报出来，而不是静默断开。"""
    from strutkit import unconnected_nodes

    m, _COL, MBX, _MBY, _SEC = build(split_policy=["MBY"])

    seg_count = Counter(mb.origin for mb in MBX.all())
    assert set(seg_count.values()) == {1}          # 主梁没被打断
    assert len(unconnected_nodes(m)) > 0           # 但报告抓到了
    assert "内部有节点但未打断" in m.report()