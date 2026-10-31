"""出口：DXF（分图层直线）与 FEA（节点表 + 单元表）。

两个原则：
  - 不引第三方依赖：DXF 手写 R12 最小格式
  - 属性原样搬运：DXF 只用 layer，其余全部写进 CSV
"""

from __future__ import annotations

import csv
import json
from typing import Mapping

from .geometry import UM_PER_MM
from .model import Model

__all__ = ["export_dxf", "export_fea"]


# ─────────────────────────────────────────────────────────────
# DXF
# ─────────────────────────────────────────────────────────────

def _dxf_num(v: float) -> str:
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s if s else "0"


def export_dxf(model: Model, path: str, *, layers: Mapping[str, int] | None = None,
               encoding: str = "utf-8") -> str:
    """导出 DXF：每个构件一条直线，按 attrs['layer'] 分图层。

    layers: {图层名: AutoCAD 颜色号}。
    优先用 ezdxf 生成标准 R2000 文件；没装 ezdxf 时回退到手写 R12。

    注意坐标系：本库 Z 竖直，而 CAD 默认 Z 向上，所以导出的 3D 视图方向是对的。
    """
    layers = dict(layers or {})
    try:
        import ezdxf  # noqa: F401
    except ImportError:
        return _export_dxf_manual(model, path, layers, encoding)
    return _export_dxf_ezdxf(model, path, layers)


def _export_dxf_ezdxf(model: Model, path: str, layers: Mapping[str, int]) -> str:
    import ezdxf

    doc = ezdxf.new("R2000", setup=False)
    doc.header["$INSUNITS"] = 4          # 4 = 毫米
    doc.header["$MEASUREMENT"] = 1       # 公制

    used: dict[str, int] = {}
    for name in layers:
        used.setdefault(name, layers[name])
    for mb in model.members.values():
        name = mb.attrs.get("layer") or "0"
        used.setdefault(name, layers.get(name, 7))

    for name, color in used.items():
        if name.upper() in doc.layers:
            doc.layers.get(name).color = color
        else:
            doc.layers.add(name, color=color)

    msp = doc.modelspace()
    for mb in model.members.values():
        p, q = model.nodes[mb.i].point, model.nodes[mb.j].point
        msp.add_line(p, q, dxfattribs={"layer": mb.attrs.get("layer") or "0"})

    try:
        doc.saveas(path)
    except PermissionError as e:
        raise PermissionError(
            f"无法写入 {path}：文件可能正被 CAD 等程序占用，请关闭后重试"
        ) from e
    return path


def _export_dxf_manual(model: Model, path: str, layers: Mapping[str, int],
                       encoding: str = "utf-8") -> str:
    """无第三方依赖的最小 R12 写法（兜底）"""
    layers = dict(layers)
    used: dict[str, int] = {}
    for name in layers:
        used.setdefault(name, layers[name])
    for mb in model.members.values():
        name = mb.attrs.get("layer") or "0"
        used.setdefault(name, layers.get(name, 7))

    out: list[str] = []

    def w(code: int, value) -> None:
        out.append(str(code))
        out.append(str(value))

    # ── HEADER ──
    w(0, "SECTION"); w(2, "HEADER")
    w(9, "$ACADVER"); w(1, "AC1009")
    w(9, "$INSUNITS"); w(70, 4)
    w(0, "ENDSEC")

    # ── TABLES：LTYPE + LAYER（R12 下 LAYER 引用 CONTINUOUS，必须先定义）──
    w(0, "SECTION"); w(2, "TABLES")
    w(0, "TABLE"); w(2, "LTYPE"); w(70, 1)
    w(0, "LTYPE"); w(2, "CONTINUOUS"); w(70, 0)
    w(3, "Solid line"); w(72, 65); w(73, 0); w(40, 0.0)
    w(0, "ENDTAB")
    w(0, "TABLE"); w(2, "LAYER"); w(70, len(used) + 1)
    w(0, "LAYER"); w(2, "0"); w(70, 0); w(62, 7); w(6, "CONTINUOUS")
    for name, color in used.items():
        w(0, "LAYER"); w(2, name); w(70, 0); w(62, color); w(6, "CONTINUOUS")
    w(0, "ENDTAB")
    w(0, "ENDSEC")

    # ── ENTITIES ──
    w(0, "SECTION"); w(2, "ENTITIES")
    for mb in model.members.values():
        p, q = model.nodes[mb.i].point, model.nodes[mb.j].point
        w(0, "LINE")
        w(8, mb.attrs.get("layer") or "0")
        w(10, _dxf_num(p[0])); w(20, _dxf_num(p[1])); w(30, _dxf_num(p[2]))
        w(11, _dxf_num(q[0])); w(21, _dxf_num(q[1])); w(31, _dxf_num(q[2]))
    w(0, "ENDSEC")
    w(0, "EOF")

    with open(path, "w", encoding=encoding, newline="\n") as f:
        f.write("\n".join(out) + "\n")
    return path


# ─────────────────────────────────────────────────────────────
# FEA：节点表 + 单元表
# ─────────────────────────────────────────────────────────────

def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str, sort_keys=True)


def export_fea(model: Model, nodes_path: str, members_path: str, *,
               encoding: str = "utf-8-sig") -> tuple[str, str]:
    """导出有限元输入：1 Member = 1 单元，属性原样带出。

    nodes.csv   : id, x_mm, y_mm, z_mm, attrs
    members.csv : id, node_i, node_j, group, length_mm, attrs, ends_i, ends_j, origin
    """
    with open(nodes_path, "w", encoding=encoding, newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["id", "x_mm", "y_mm", "z_mm", "attrs"])
        for nid, nd in sorted(model.nodes.items()):
            x, y, z = nd.point
            wr.writerow([nid, f"{x:.6f}", f"{y:.6f}", f"{z:.6f}",
                         _json(nd.attrs) if nd.attrs else ""])

    with open(members_path, "w", encoding=encoding, newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["id", "node_i", "node_j", "group", "length_mm",
                     "attrs", "ends_i", "ends_j", "origin"])
        for mid, mb in sorted(model.members.items()):
            p, q = model.nodes[mb.i].xyz, model.nodes[mb.j].xyz
            length = (((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2
                       + (q[2] - p[2]) ** 2) ** 0.5) / UM_PER_MM
            wr.writerow([
                mid, mb.i, mb.j, mb.group or "", f"{length:.6f}",
                _json(mb.attrs) if mb.attrs else "",
                _json(mb.ends.get("i")), _json(mb.ends.get("j")),
                _json(mb.origin) if mb.origin else "",
            ])
    return nodes_path, members_path