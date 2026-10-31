"""strutkit —— 杆系结构几何建模库。

定位：把任意结构离散成「有限个节点 + 有限根杆件」，让几何精确、属性原样、问题可见。
不涉及任何力学计算。

坐标系约定（库本身与轴名无关，这里只是推荐约定）：
    X = 纵向（沿排列方向）
    Y = 进深（柱片宽度方向）
    Z = 竖直，重力方向为 −Z
这样导出的 DXF 在 CAD 的 3D 视图里方向是对的。

快速上手：

    from strutkit import Axis, Model

    X  = Axis.spans([3000, 3000], axis="x")                  # 0, 3000, 6000
    Y  = Axis.spans([800], axis="y")                         # 0, 800
    ZL = Axis.spans([2000], axis="z", include_base=False)    # 2000

    m = Model()
    COL  = m.define("COL",  split="all",  attrs={"layer": "COLUMN"})
    BEAM = m.define("BEAM", split="none", attrs={"layer": "BEAM"})

    for x in X:
        for y in Y:
            COL.add((x, y, 0), (x, y, 4000))          # 柱沿 Z 竖直
    for z in ZL:
        for y in Y:
            for i in range(len(X) - 1):
                BEAM.add((X[i], y, z), (X[i + 1], y, z))

    print(m.report())
"""

from .geometry import Axis, PointSet, get_quantum, set_quantum, to_mm, to_um
from .model import ConflictError, Group, Member, Model, Node
from .report import inv_violations, report, unconnected_nodes
from .export import export_dxf, export_fea

__version__ = "0.1.0"

__all__ = [
    "Axis", "PointSet",
    "Model", "Group", "Node", "Member", "ConflictError",
    "report", "inv_violations", "unconnected_nodes",
    "export_dxf", "export_fea",
    "set_quantum", "get_quantum", "to_um", "to_mm",
]