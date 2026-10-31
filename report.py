"""体检报告：把「图上看着连上、计算里断开」变成一行行文字。"""

from __future__ import annotations

from collections import defaultdict
from .geometry import UM_PER_MM
from .model import Member, Model

__all__ = ["report", "inv_violations", "unconnected_nodes"]

_EPS = 1e-9


def _fmt(p) -> str:
    """坐标格式化：(3000, 0, 800)"""
    return "(" + ", ".join(f"{v:g}" for v in p) + ")"


def _fmt_z(z_um: int) -> str:
    """标高显示成米，保留三位小数：1000mm → 0.000"""
    if z_um == 0:
        return "±0.000"
    return f"{z_um / UM_PER_MM / 1000:.3f}"


def _length_um(model: Model, mb: Member) -> int:
    p, q = model.nodes[mb.i].xyz, model.nodes[mb.j].xyz
    return int(round(((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 + (q[2] - p[2]) ** 2) ** 0.5))


def inv_violations(model: Model) -> list[tuple[Member, int]]:
    """不变式 INV：构件内部不应存在「允许打断它」的节点。返回违反项。"""
    bad = []
    for mb in model.members.values():
        p, q = model.nodes[mb.i].xyz, model.nodes[mb.j].xyz
        for node in model.nodes.values():
            if node.id in (mb.i, mb.j):
                continue
            if not model._on_segment(p, q, node.xyz):
                continue
            if model._allows(mb, node.id):
                bad.append((mb, node.id))
    return bad


def unconnected_nodes(model: Model) -> list[tuple[Member, int]]:
    """内部有节点、但 split 策略不允许打断（大 X 背拉的正常情形）"""
    out = []
    for mb in model.members.values():
        p, q = model.nodes[mb.i].xyz, model.nodes[mb.j].xyz
        for node in model.nodes.values():
            if node.id in (mb.i, mb.j):
                continue
            if not model._on_segment(p, q, node.xyz):
                continue
            if not model._allows(mb, node.id):
                out.append((mb, node.id))
    return out


def _components(model: Model) -> int:
    """连通分量个数（节点—构件图）"""
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for mb in model.members.values():
        union(mb.i, mb.j)
    roots = {find(n) for n in model.nodes if model.nodes[n].sources}
    return len(roots)


def _near_pairs(model: Model, step_um: int) -> list[tuple[int, int]]:
    """距离小于一个量化步长、但不是同一坐标的节点对"""
    nodes = [(n.id, n.xyz) for n in model.nodes.values()]
    if len(nodes) > 5000:
        return []
    out = []
    for a in range(len(nodes)):
        ida, xa = nodes[a]
        for b in range(a + 1, len(nodes)):
            idb, xb = nodes[b]
            d2 = sum((xa[k] - xb[k]) ** 2 for k in range(3))
            if 0 < d2 < step_um * step_um:
                out.append((ida, idb))
    return out


def report(model: Model, *, short_mm: float = 150.0, show_cuts: bool = True) -> str:
    """生成体检报告。只报告，不修改模型。"""
    lines: list[str] = []
    members = list(model.members.values())
    nodes = list(model.nodes.values())

    # ── 规模 ──────────────────────────────────────────────
    by_group: dict[str | None, list[Member]] = defaultdict(list)
    for mb in members:
        by_group[mb.group].append(mb)
    lines.append(f"Nodes: {len(nodes)}    Members: {len(members)}")
    for g, lst in sorted(by_group.items(), key=lambda kv: (kv[0] or "", )):
        origins: dict[tuple, int] = defaultdict(int)
        for mb in lst:
            origins[mb.origin] += 1
        pieces = [n for n in origins.values() if n > 1]
        extra = f"（{len(pieces)} 根被切成多段）" if pieces else ""
        lines.append(f"  {g or '(未分组)':<10} {len(lst):>5}{extra}")
    lines.append("")

    # ── INV ──────────────────────────────────────────────
    bad = inv_violations(model)
    lines.append("INV: OK" if not bad else f"INV: ✗ 违反 {len(bad)} 处")
    if bad:
        for mb, nid in bad[:10]:
            lines.append(f"    {mb.group} {_fmt(model.nodes[mb.i].point)}→"
                         f"{_fmt(model.nodes[mb.j].point)} 内部节点 {_fmt(model.nodes[nid].point)}")

    # ── 内部有节点但未打断 ────────────────────────────────
    unc = unconnected_nodes(model)
    lines.append("")
    if unc:
        lines.append(f"内部有节点但未打断（{len(unc)}）：")
        for mb, nid in unc[:20]:
            srcs = {model.members[m].group for m in model.nodes[nid].sources
                    if m in model.members}
            lines.append(
                f"  {mb.group} {_fmt(model.nodes[mb.i].point)}→{_fmt(model.nodes[mb.j].point)}"
                f"   内部 {_fmt(model.nodes[nid].point)}  节点来源: {sorted(srcs) or ['(显式)']}"
            )
        lines.append('  → 符合 split="none" 的声明；若需连接请改用 split="all"')
    else:
        lines.append("内部有节点但未打断：0")

    # ── 端点（度 = 1）──────────────────────────────────────
    loose = []
    for nd in nodes:
        if len(nd.sources) == 1 and not nd.attrs:
            loose.append(nd)
    lines.append("")
    if loose:
        lines.append(f"端点（度=1 且无节点属性，可能漏连或未标支座）：{len(loose)}")
        for nd in loose[:10]:
            lines.append(f"  {_fmt(nd.point)}")
    else:
        lines.append("端点（度=1 且无节点属性）：0")

    # ── 端部未指定 ────────────────────────────────────────
    unspecified = 0
    for mb in members:
        for k in ("i", "j"):
            if mb.ends.get(k) is None:
                unspecified += 1
    lines.append("")
    lines.append(f"端部未指定：{unspecified}")

    # ── 短段 ──────────────────────────────────────────────
    shorts = [(mb, _length_um(model, mb) / UM_PER_MM) for mb in members]
    shorts = [(mb, L) for mb, L in shorts if L < short_mm - _EPS]
    lines.append("")
    if shorts:
        lines.append(f"短段告警（< {short_mm:g} mm）：{len(shorts)}")
        for mb, L in sorted(shorts, key=lambda t: t[1])[:10]:
            lines.append(f"  {L:.3f} mm  {mb.group} {_fmt(model.nodes[mb.i].point)}→"
                         f"{_fmt(model.nodes[mb.j].point)}")
    else:
        lines.append(f"短段（< {short_mm:g} mm）：0")

    # ── 地面检查：±0 处不应有水平构件 ─────────────────────
    zmin = min((n.point[2] for n in model.nodes.values()), default=None)
    if zmin is not None:
        on_ground = [mb for mb in members
                     if abs(model.nodes[mb.i].point[2] - zmin) < _EPS
                     and abs(model.nodes[mb.j].point[2] - zmin) < _EPS]
        lines.append("")
        if on_ground:
            by_group = {}
            for mb in on_ground:
                by_group[mb.group] = by_group.get(mb.group, 0) + 1
            lines.append(f"最低标高 z={_fmt_z(zmin)} 处的水平构件：{len(on_ground)} 根"
                         f"  {by_group}")
            lines.append("  → 若不是有意为之（如地梁），检查是否把梁/水平拉放到了柱脚平面")
        else:
            lines.append(f"最低标高 z={_fmt_z(zmin)} 处无水平构件：OK")

    # ── 连通性 ────────────────────────────────────────────
    lines.append("")
    lines.append(f"连通分量：{_components(model)}")

    # ── 孤立断点（可合并）─────────────────────────────────
    orphans = []
    seen = set()
    for mb in members:
        if mb.id in seen:
            continue
        neigh = model._neighbors(mb)
        if neigh:
            orphans.append(mb)
            seen.add(mb.id)
    lines.append("")
    if orphans:
        lines.append(f"孤立断点（可 merge_orphans 合并）：{len(orphans)}")
        for mb in orphans[:10]:
            lines.append(f"  {mb.group} origin={mb.origin} 端点 {_fmt(model.nodes[mb.i].point)}"
                         f"→{_fmt(model.nodes[mb.j].point)}")
    else:
        lines.append("孤立断点：0")

    # ── 量化近似点 ────────────────────────────────────────
    from .geometry import get_quantum
    near = _near_pairs(model, int(round(get_quantum() * UM_PER_MM)))
    lines.append("")
    if near:
        lines.append(f"量化近似点（距离 < 1 个量化步长但未合并）：{len(near)}")
        for a, b in near[:10]:
            lines.append(f"  {_fmt(model.nodes[a].point)} ↔ {_fmt(model.nodes[b].point)}")
    else:
        lines.append("量化近似点：0")

    # ── 切点来源 ──────────────────────────────────────────
    if show_cuts:
        lines.append("")
        lines.append("切点来源（被打断的构件）：")
        by_origin: dict[tuple, list[Member]] = defaultdict(list)
        for mb in members:
            by_origin[(mb.group, mb.origin)].append(mb)
        shown = 0
        for (g, origin), segs in by_origin.items():
            if len(segs) > 1 and shown < 10:
                dn = sorted({model.nodes[m.i if m.i != segs[0].i else m.j].point
                             for m in segs})
                lines.append(f"  {g} origin={origin}: 1 根 → {len(segs)} 段")
                shown += 1
        if shown == 0:
            lines.append("  （无）")

    return "\n".join(lines)