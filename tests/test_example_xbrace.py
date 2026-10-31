"""验收测试 2：大 X 背拉跨越中间节点但不被打断

坐标系约定：X = 排的纵向，Y = 进深（柱片宽度方向），**Z = 竖直（重力方向 -Z）**

这是整个设计里最容易做错的语义：一根只受拉斜杆跨 2 跨 2 层，
中点正好撞在中间柱与梁的交点上（一个真节点），但它绝不能被打断——
一旦打断，拉杆中点被约束，力学模型就完全变了。
"""

from strutkit import Axis, Model


def build(brace_split="none"):
    X  = Axis.spans([3000, 3000, 3000], axis="x")                  # 0, 3000, 6000, 9000
    Y  = Axis.spans([800], axis="y", role=["前排", "后排"])           # 0, 800（进深）
    ZL = Axis.spans([2000, 2000], axis="z", include_base=False)     # 2000, 4000（标高）
    H  = 5000

    m = Model()
    COL    = m.define("COL",    split="all",  attrs={"layer": "COLUMN", "section": "C100x80"})
    BEAM   = m.define("BEAM",   split="none", attrs={"layer": "BEAM", "section": "HL-1"})
    YBRACE = m.define("YBRACE", split="none", attrs={"layer": "YBRACE", "section": "L40x4"})
    BRACE  = m.define("BRACE",  split=brace_split,
                      attrs={"layer": "BRACE", "section": "D20", "tension_only": True})

    for x in X:                       # 柱脚支座（节点属性）
        for y in Y:
            m.node((x, y, 0), attrs={"支座": "铰接"})

    for x in X:                       # 柱：沿 Z 竖直
        for y in Y:
            COL.add((x, y, 0), (x, y, H))

    for x in X:                       # 柱片横撑：沿 Y 连接两根立柱，最低 z=200、最高 z=H
        for z in (200, H):
            YBRACE.add((x, Y[0], z), (x, Y[1], z))

    for z in ZL:                      # 横梁：沿 X，位于各层标高
        for y in Y:
            for i in range(len(X) - 1):
                BEAM.add((X[i], y, z), (X[i + 1], y, z))

    x0, x1, yy = X[1], X[3], Y[1]     # 大 X 背拉：X–Z 竖直平面，y = 800
    BRACE.add((x0, yy, 0), (x1, yy, ZL[-1]))
    BRACE.add((x0, yy, ZL[-1]), (x1, yy, 0))
    return m, COL, BEAM, YBRACE, BRACE


def test_counts():
    m, COL, BEAM, YBR, BRACE = build()
    assert len(m.nodes) == 40
    assert len(m.members) == 54
    assert COL.count() == 32        # 8 根柱 × 4 段（切点 0/200/2000/4000/5000）
    assert BEAM.count() == 12
    assert YBR.count() == 8
    assert BRACE.count() == 2


def test_inv_ok():
    from strutkit import inv_violations
    m, *_ = build()
    assert inv_violations(m) == []


def test_xbrace_not_sliced_by_mid_node():
    """核心断言：两根斜杆的中点撞在中间柱节点上，但一根都没被切"""
    m, _COL, _BEAM, _YBR, BRACE = build(brace_split="none")
    assert BRACE.count() == 2
    for mb in BRACE.all():
        p = m.nodes[mb.i].point
        q = m.nodes[mb.j].point
        assert abs(p[0] - q[0]) == 6000      # 跨 2 跨，中间没断点


def test_xbrace_reports_unconnected_mid_node():
    """报告必须把「内部有节点但没打断」列出来，而不是静默"""
    from strutkit import unconnected_nodes
    m, *_ = build(brace_split="none")
    unc = unconnected_nodes(m)
    assert len(unc) == 2                      # 两根斜杆各一条
    mids = {m.nodes[nid].point for _, nid in unc}
    assert mids == {(6000.0, 800.0, 2000.0)}  # 中间柱与第 1 层梁的交点


def test_xbrace_split_all_would_slice():
    """反例：split='all' 时会被切成 4 根 —— 这正是不能选 all 的理由"""
    from strutkit import inv_violations, unconnected_nodes
    m, *_ , BRACE = build(brace_split="all")
    assert BRACE.count() == 4
    assert unconnected_nodes(m) == []
    assert inv_violations(m) == []


def test_connectivity():
    from strutkit.report import _components
    m, *_ = build()
    assert _components(m) == 1


def test_report_text():
    m, *_ = build()
    text = m.report()
    assert "INV: OK" in text
    assert "内部有节点但未打断（2）" in text
    assert "连通分量：1" in text
    assert "端点（度=1 且无节点属性）：0" in text