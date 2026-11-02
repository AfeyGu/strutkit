"""X 形交叉打断：双向门控、网格约束、大 X 安全、顺序对称。

T 形（端点落在对方身上）由节点驱动，只有被穿的一方需要放行；
X 形（两边都没有端点）必须双方都放行，否则断了一边却没连上，等于白断。
"""

from strutkit import Model, inv_violations, step_um
from strutkit.diagnostics import _components


def _fingerprint(m: Model):
    return (
        sorted(tuple(n.xyz) for n in m.nodes.values()),
        sorted((mb.group, m.nodes[mb.i].xyz, m.nodes[mb.j].xyz)
               for mb in m.members.values()),
    )


def test_on_grid_crossing_splits_both_sides():
    """交点在量化网格上 → 两边都切开，并新增一个节点"""
    m = Model()
    A = m.define("A", split=["B"])
    B = m.define("B", split=["A"])
    A.add((0, 0, 0), (0.2, 0, 0.2))          # mm；交点 (0.1, 0, 0.1) 在 0.1mm 网格上
    B.add((0.2, 0, 0), (0, 0, 0.2))
    assert (A.count(), B.count()) == (2, 2)
    assert m._xsplit == 1
    assert inv_violations(m) == []


def test_off_grid_crossing_is_ignored():
    """交点落在网格之间 → 不打断（不引入第二个精度旋钮）"""
    m = Model()
    A = m.define("A", split=["B"])
    B = m.define("B", split=["A"])
    A.add((0, 0, 0), (0.3, 0, 0.1))          # 交点 (0.15, 0, 0.05)：0.15/0.05 都不在网格上
    B.add((0, 0, 0.1), (0.3, 0, 0))
    assert (A.count(), B.count()) == (1, 1)
    assert m._xsplit == 0


def test_skew_segments_are_not_crossings():
    """异面（不相交）的两根杆不能被打断"""
    m = Model()
    A = m.define("A", split=["B"])
    B = m.define("B", split=["A"])
    A.add((0, 0, 0), (4000, 0, 0))
    B.add((2000, 500, -2000), (2000, 500, 2000))   # y 方向错开 500mm，不相交
    assert (A.count(), B.count()) == (1, 1)
    assert m._xsplit == 0


def test_big_x_stays_untouched():
    """大 X 拉杆：交叉点即使在网格上也不能连（split="none" 就是闸门）"""
    m = Model()
    BR = m.define("BR", split="none")
    BR.add((0, 0, 0), (6000, 0, 4000))
    BR.add((0, 0, 4000), (6000, 0, 0))
    assert BR.count() == 2
    assert m._xsplit == 0
    assert _components(m) == 2               # 两根独立斜杆，没连上


def test_one_sided_permission_does_nothing():
    """只有一边放行 → 一根都不切（否则断开的梁挂在空中，等于白断）"""
    m = Model()
    A = m.define("A", split="all")
    B = m.define("B", split="none")
    A.add((0, 0, 0), (0.2, 0, 0.2))
    B.add((0.2, 0, 0), (0, 0, 0.2))
    assert (A.count(), B.count()) == (1, 1)
    assert m._xsplit == 0


def test_crossing_connects_and_keeps_inv():
    """交叉打断的目的就是连上：连通分量下降，且 INV 不被破坏"""
    m = Model()
    COL = m.define("COL", split="all")
    BEAM = m.define("BEAM", split=["COL"])
    for x in (0, 3000, 6000):
        COL.add((x, 0, 0), (x, 0, 3000))
    assert _components(m) == 3                # 三根独立柱
    BEAM.add((0, 0, 1500), (6000, 0, 1500))   # 穿过中间柱
    assert _components(m) == 1                # 全部连成一个
    assert inv_violations(m) == []


def test_crossing_is_order_symmetric():
    """先加 A 还是先加 B，建出来的模型必须完全相同"""
    def build(first: str):
        m = Model()
        m.define("A", split=["B"])
        m.define("B", split=["A"])
        segs = {"A": ((0, 0, 0), (2000, 0, 2000)),
                "B": ((2000, 0, 0), (0, 0, 2000))}
        for g in first:
            m.group(g).add(*segs[g])
        return _fingerprint(m)

    assert build("AB") == build("BA")


def test_crossing_node_is_on_grid():
    """交叉造出来的点必须落在量化网格上"""
    m = Model()
    A = m.define("A", split=["B"])
    B = m.define("B", split=["A"])
    A.add((0, 0, 0), (2000, 0, 2000))
    B.add((2000, 0, 0), (0, 0, 2000))
    step = step_um()
    assert all(c % step == 0 for n in m.nodes.values() for c in n.xyz)
