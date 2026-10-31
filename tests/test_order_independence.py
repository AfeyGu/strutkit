"""验收测试 1：书写顺序无关性

同一组构件，用不同的添加顺序建模型，最终结果必须完全一致。
这条通过，才敢说「用户想怎么排就怎么排」。

坐标系约定：X = 排的纵向，Y = 进深，Z = 竖直（重力方向 -Z）
"""

import itertools

from strutkit import Axis, Model


def _axes():
    X  = Axis.spans([3000, 3000, 3000], axis="x")                  # 0, 3000, 6000, 9000
    Y  = Axis.spans([800], axis="y")                                # 0, 800（进深）
    ZL = Axis.spans([2000, 2000], axis="z", include_base=False)     # 2000, 4000（标高）
    return X, Y, ZL


H = 5000


def _add_columns(m, X, Y, ZL):
    COL = m.define("COL", split="all", attrs={"layer": "COLUMN"})
    for x in X:
        for y in Y:
            COL.add((x, y, 0), (x, y, H))


def _add_beams(m, X, Y, ZL):
    BEAM = m.define("BEAM", split="none", attrs={"layer": "BEAM"})
    for z in ZL:
        for y in Y:
            for i in range(len(X) - 1):
                BEAM.add((X[i], y, z), (X[i + 1], y, z))


def _add_ybraces(m, X, Y, ZL):
    YB = m.define("YBRACE", split="none", attrs={"layer": "YBRACE"})
    for x in X:
        for z in (200, H):
            YB.add((x, Y[0], z), (x, Y[1], z))


def _add_xbrace(m, X, Y, ZL):
    BR = m.define("BRACE", split="none", attrs={"layer": "BRACE"})
    x0, x1, y = X[1], X[3], Y[1]
    BR.add((x0, y, 0), (x1, y, ZL[-1]))
    BR.add((x0, y, ZL[-1]), (x1, y, 0))


BUILDERS = {
    "COL":    _add_columns,
    "BEAM":   _add_beams,
    "YBRACE": _add_ybraces,
    "BRACE":  _add_xbrace,
}


def build(order):
    X, Y, ZL = _axes()
    m = Model()
    for name in order:
        BUILDERS[name](m, X, Y, ZL)
    return m


def signature(m):
    """与编号无关的指纹：节点坐标集 + 构件坐标对集 + 分组统计"""
    node_pts = sorted(tuple(round(c, 6) for c in n.point) for n in m.nodes.values())
    edges = sorted(
        tuple(sorted([
            tuple(round(c, 6) for c in m.nodes[mb.i].point),
            tuple(round(c, 6) for c in m.nodes[mb.j].point),
        ]))
        for mb in m.members.values()
    )
    by_group = {}
    for mb in m.members.values():
        by_group[mb.group] = by_group.get(mb.group, 0) + 1
    return len(node_pts), len(edges), tuple(node_pts), tuple(edges), tuple(sorted(by_group.items()))


def test_all_orders_give_same_result():
    names = list(BUILDERS)
    base = signature(build(names))
    for perm in itertools.permutations(names):
        got = signature(build(perm))
        assert got == base, f"顺序 {perm} 得到不同结果"


def test_order_independence_single_member():
    """两根构件互相搭接：先加谁都要得到同样的拓扑"""
    def build2(first_is_column):
        m = Model()
        COL = m.define("COL", split="all")
        BEAM = m.define("BEAM", split="none")
        if first_is_column:
            COL.add((0, 0, 0), (0, 0, 5000))          # 柱：沿 Z 竖直
            BEAM.add((0, 0, 2000), (3000, 0, 2000))   # 梁：沿 X，z = 2000
        else:
            BEAM.add((0, 0, 2000), (3000, 0, 2000))
            COL.add((0, 0, 0), (0, 0, 5000))
        return len(m.nodes), len(m.members)

    assert build2(True) == build2(False) == (4, 3)