"""节点池、构件、模型、构件组。

设计要点：
  - Member 就是单元：打断后变成多根独立构件
  - 打断双向维持不变式 INV（新点切旧杆 + 旧点切新杆），无 finalize()
  - split 策略是「组」的属性，默认 "none"（破坏性操作默认关）
  - 增删不对称：加会自动切，删不会自动合；合并需显式调用
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from .geometry import Axis, PointSet, step_um, to_mm, to_um

__all__ = ["Node", "Member", "Model", "Group", "ConflictError"]


class ConflictError(Exception):
    """同位置重复添加构件"""


# ─────────────────────────────────────────────────────────────
# 节点与构件
# ─────────────────────────────────────────────────────────────

@dataclass
class Node:
    id: int
    xyz: tuple[int, int, int]          # μm
    sources: set[int] = field(default_factory=set)   # 引用它的构件编号
    attrs: dict[str, Any] = field(default_factory=dict)  # 支座、主从、附加质量

    @property
    def point(self) -> tuple[float, float, float]:
        return tuple(to_mm(v) for v in self.xyz)  # type: ignore[return-value]


@dataclass
class Member:
    id: int
    i: int                             # 起始节点编号
    j: int                             # 终止节点编号
    group: str | None
    attrs: dict[str, Any] = field(default_factory=dict)   # 跨内属性
    ends: dict[str, Any] = field(default_factory=dict)    # {"i": .., "j": ..}
    origin: tuple | None = None        # 打断前身份

    def end(self, which: str):
        return self.ends.get(which)


def _se_pair(split_ends) -> tuple[Any, Any]:
    """把 split_ends 规范成 (左段 j 端, 右段 i 端)"""
    if split_ends is None:
        return (None, None)
    if isinstance(split_ends, tuple):
        if len(split_ends) != 2:
            raise ValueError("split_ends 二元组必须是 (左段j端, 右段i端)")
        return split_ends
    return (split_ends, split_ends)


# ─────────────────────────────────────────────────────────────
# Model
# ─────────────────────────────────────────────────────────────

class Model:
    """构件容器。只有 4 个入口：define / member / node / remove。"""

    def __init__(self, *, default_split_ends=None):
        self._nodes: dict[int, Node] = {}
        self._node_at: dict[tuple[int, int, int], int] = {}
        self._members: dict[int, Member] = {}
        self._groups: dict[str, "Group"] = {}
        self._next_node = 0
        self._next_member = 0
        self._default_split_ends = default_split_ends
        # 位置键 → 构件编号（防重复）
        self._poskey: dict[tuple, int] = {}
        # 显式节点声明的来源组（as_group），参与 split 判断
        self._virtual: dict[int, str] = {}

    # ── 定义组 ────────────────────────────────────────────

    def define(self, name: str, *, split="none", attrs: dict | None = None,
               keys: dict | None = None, ends: dict | None = None,
               split_ends="__inherit__") -> "Group":
        if name in self._groups:
            raise ValueError(f"组 {name!r} 已定义")
        if split_ends == "__inherit__":
            split_ends = self._default_split_ends
        grp = Group(self, name, split=split, attrs=attrs, keys=keys,
                    ends=ends, split_ends=split_ends)
        self._groups[name] = grp
        return grp

    def group(self, name: str) -> "Group":
        try:
            return self._groups[name]
        except KeyError:
            raise KeyError(f"未定义的组 {name!r}；已定义：{list(self._groups)}") from None

    # ── 节点 ──────────────────────────────────────────────

    def _node_id(self, p: Sequence[float]) -> int:
        xyz = tuple(to_um(c) for c in p)
        if len(xyz) != 3:
            raise ValueError(f"坐标必须是三维，收到 {len(xyz)} 维")
        nid = self._node_at.get(xyz)
        if nid is None:
            nid = self._next_node
            self._next_node += 1
            self._nodes[nid] = Node(id=nid, xyz=xyz)
            self._node_at[xyz] = nid
        return nid

    def node(self, xyz: Sequence[float], *, attrs: dict | None = None,
             as_group: str | None = None) -> Node:
        """显式给节点打属性。as_group 表示「这个节点视为由该组构件产生」，
        不带 as_group 的显式节点不打断任何构件（安全默认）。"""
        nid = self._node_id(xyz)
        node = self._nodes[nid]
        if attrs:
            node.attrs.update(attrs)
        if as_group:
            self._virtual[nid] = as_group
            # 立刻按新身份重新检查打断
            self._split_others_at(nid, skip=None)
        return node

    # ── 加构件 ────────────────────────────────────────────

    def member(self, p: Sequence[float], q: Sequence[float], *,
               group: str | None = None, **attrs) -> Member | list[Member]:
        """底层入口：加一根构件（不带组也行）。返回最终成形的段。"""
        grp = self.group(group) if group else None
        return self._add(p, q, grp, attrs, ends=None, origin=None)

    def _add(self, p, q, grp: "Group | None", attrs: dict,
             ends: dict | None, origin: tuple | None) -> Member | list[Member]:
        ni = self._node_id(p)
        nj = self._node_id(q)
        if ni == nj:
            raise ValueError(f"零长构件：两端都是 {tuple(to_mm(v) for v in self._nodes[ni].xyz)}")

        group_name = grp.name if grp else None
        # 位置键：无向（i,j 与 j,i 视为同一根）
        key = (group_name, min(ni, nj), max(ni, nj))
        if key in self._poskey:
            raise ConflictError(
                f"构件已存在：组={group_name!r} "
                f"{self._nodes[ni].point} → {self._nodes[nj].point}"
            )

        mb = Member(
            id=self._next_member,
            i=ni, j=nj,
            group=group_name,
            attrs=dict(attrs),
            ends=dict(ends or {}),
            origin=origin or (group_name, self._next_member),
        )
        self._next_member += 1
        self._members[mb.id] = mb
        self._poskey[key] = mb.id
        self._nodes[ni].sources.add(mb.id)
        self._nodes[nj].sources.add(mb.id)

        # ① 新节点切旧构件  ② 旧节点切新构件
        try:
            self._split_others_at(ni, skip=mb.id)
            self._split_others_at(nj, skip=mb.id)
            produced = self._split_self(mb)
        except ConflictError:
            # 新构件与已有构件重合（同组共线重叠 = 重复杆件）。
            # 回滚新构件本身：它还没被切开，摘掉即可。
            # 其他构件此前发生的打断切点都是真实节点，属于有效打断，予以保留。
            self._members.pop(mb.id, None)
            self._poskey.pop(key, None)
            self._nodes[ni].sources.discard(mb.id)
            self._nodes[nj].sources.discard(mb.id)
            raise

        return produced[0] if len(produced) == 1 else produced

    # ── 打断 ──────────────────────────────────────────────

    @staticmethod
    def _on_segment(p, q, n) -> bool:
        """n 是否落在 p→q 内部。

        绝对判定：整数叉积/点积，零浮点，结果可复现。

        容差（tolerance = 1 个量化步长）的作用与边界：
          - 放宽「到直线的垂直距离」：量化把本应共线的点挤出直线，
            最大偏离 (q/2)·√3 ≈ 0.87q，故容差取 1q 刚好覆盖；
          - 不放宽「落在两端之间」：点必须在杆的跨度内部；
          - 与两端各留 1q 的余量：否则会在端点旁切出长度 < 1q 的微段。
        判定用平方比较（|cross|² ≤ tol²·|d|²），不开方，仍然全整数。
        """
        dx, dy, dz = q[0] - p[0], q[1] - p[1], q[2] - p[2]
        vx, vy, vz = n[0] - p[0], n[1] - p[1], n[2] - p[2]
        dd = dx * dx + dy * dy + dz * dz
        if dd == 0:
            return False
        limit = step_um() ** 2 * dd          # (tol·|d|)²，同时用于两个判定

        dv = dx * vx + dy * vy + dz * vz
        if not (0 < dv < dd):
            return False                     # 投影必须落在杆的跨度内部
        if dv * dv < limit or (dd - dv) * (dd - dv) < limit:
            return False                     # 离某一端不足一个容差 → 不切，避免微段

        cx = dy * vz - dz * vy
        cy = dz * vx - dx * vz
        cz = dx * vy - dy * vx
        return cx * cx + cy * cy + cz * cz <= limit

    def _group_split(self, group_name: str | None):
        if group_name is None:
            return "none"
        grp = self._groups.get(group_name)
        return grp.split if grp else "none"

    def _allows(self, mb: Member, nid: int) -> bool:
        """节点 nid 是否允许打断 mb（依据 mb 所属组的 split 策略）"""
        policy = self._group_split(mb.group)
        if policy == "none":
            return False
        if policy == "all":
            return True
        if isinstance(policy, tuple) and policy and policy[0] == "whitelist":
            pts = policy[1]
            xyz_mm = tuple(to_mm(v) for v in self._nodes[nid].xyz)
            return xyz_mm in pts
        # 白名单：sources 中至少一个成员的组在白名单内
        allowed = set(policy)
        src_groups = set()
        for mid in self._nodes[nid].sources:
            other = self._members.get(mid)
            if other is not None and other.group:
                src_groups.add(other.group)
        if nid in self._virtual:
            src_groups.add(self._virtual[nid])
        return bool(src_groups & allowed)

    def _split_others_at(self, nid: int, skip: int | None):
        """新节点 nid 可能切开已有构件"""
        node = self._nodes[nid]
        tol = step_um()          # 容差会让"差一点点"的节点也落在杆上，包围盒同步外扩
        for mb in list(self._members.values()):
            if mb.id == skip:
                continue
            if mb.i == nid or mb.j == nid:
                continue
            p, q = self._nodes[mb.i].xyz, self._nodes[mb.j].xyz
            # 包围盒快速排除
            if not (min(p[0], q[0]) - tol <= node.xyz[0] <= max(p[0], q[0]) + tol and
                    min(p[1], q[1]) - tol <= node.xyz[1] <= max(p[1], q[1]) + tol and
                    min(p[2], q[2]) - tol <= node.xyz[2] <= max(p[2], q[2]) + tol):
                continue
            if not self._on_segment(p, q, node.xyz):
                continue
            if not self._allows(mb, nid):
                continue
            self._split_member(mb, [nid])

    def _split_self(self, mb: Member) -> list[Member]:
        """旧节点切开新构件 mb，返回最终成形的段"""
        if mb.id not in self._members:
            return [mb]  # 已被切过
        p, q = self._nodes[mb.i].xyz, self._nodes[mb.j].xyz
        tol = step_um()          # 同 _split_others_at：包围盒随容差外扩
        cuts = []
        for node in self._nodes.values():
            if node.id in (mb.i, mb.j):
                continue
            if not (min(p[0], q[0]) - tol <= node.xyz[0] <= max(p[0], q[0]) + tol and
                    min(p[1], q[1]) - tol <= node.xyz[1] <= max(p[1], q[1]) + tol and
                    min(p[2], q[2]) - tol <= node.xyz[2] <= max(p[2], q[2]) + tol):
                continue
            if self._on_segment(p, q, node.xyz) and self._allows(mb, node.id):
                cuts.append(node.id)
        if not cuts:
            return [mb]
        return self._split_member(mb, cuts)

    def _split_member(self, mb: Member, cuts: list[int]) -> list[Member]:
        """把 mb 在 cuts 处切开，返回新段"""
        p, q = self._nodes[mb.i].xyz, self._nodes[mb.j].xyz
        d = (q[0] - p[0], q[1] - p[1], q[2] - p[2])
        dd = d[0] ** 2 + d[1] ** 2 + d[2] ** 2

        def param(nid: int) -> int:
            n = self._nodes[nid].xyz
            v = (n[0] - p[0], n[1] - p[1], n[2] - p[2])
            # 整数投影（同一线段上，分母相同，比较分子即可）
            return d[0] * v[0] + d[1] * v[1] + d[2] * v[2]

        cuts = sorted(set(cuts), key=param)
        pts = [mb.i] + cuts + [mb.j]
        se_l, se_r = _se_pair(
            (self._groups[mb.group].split_ends if mb.group else None)
        )

        # 预检：打断产生的段若与已有构件重合，说明模型里存在重复杆件
        # （同组、共线、部分重叠）。必须在此拦下 —— 否则 _poskey 会被静默
        # 覆盖，之后 remove()/merge() 会按位置键错删另一根。
        # 注意：本检查在改动 _members 之前完成，因此这一根构件不会留下半成品。
        for a, b in zip(pts, pts[1:]):
            key = (mb.group, min(a, b), max(a, b))
            if key in self._poskey:
                other = self._members.get(self._poskey[key])
                raise ConflictError(
                    f"打断会产生与已有构件重合的段：组={mb.group!r} "
                    f"{self._nodes[a].point} → {self._nodes[b].point}"
                    + (f"（已有构件 id={other.id}）" if other else "")
                )

        # 注销原构件
        del self._members[mb.id]
        self._poskey.pop((mb.group, min(mb.i, mb.j), max(mb.i, mb.j)), None)
        for nid in (mb.i, mb.j):
            self._nodes[nid].sources.discard(mb.id)

        produced = []
        last = len(pts) - 2
        for k in range(len(pts) - 1):
            i0, j0 = pts[k], pts[k + 1]
            seg = Member(
                id=self._next_member,
                i=i0, j=j0,
                group=mb.group,
                attrs=dict(mb.attrs),
                ends={
                    "i": mb.ends.get("i") if k == 0 else se_r,
                    "j": mb.ends.get("j") if k == last else se_l,
                },
                origin=mb.origin,
            )
            self._next_member += 1
            self._members[seg.id] = seg
            self._poskey[(seg.group, min(i0, j0), max(i0, j0))] = seg.id
            self._nodes[i0].sources.add(seg.id)
            self._nodes[j0].sources.add(seg.id)
            produced.append(seg)
        return produced

    # ── 查询 ──────────────────────────────────────────────

    @property
    def nodes(self) -> dict[int, Node]:
        return self._nodes

    @property
    def members(self) -> dict[int, Member]:
        return self._members

    def by(self, **query) -> list[Member]:
        """按属性查询。group= / origin= 特殊处理，其余匹配 attrs。"""
        out = []
        for mb in self._members.values():
            ok = True
            for k, v in query.items():
                if k == "group":
                    ok = (mb.group == v)
                elif k == "origin":
                    ok = (mb.origin == v)
                else:
                    ok = (mb.attrs.get(k) == v)
                if not ok:
                    break
            if ok:
                out.append(mb)
        return out

    # ── 出口 ──────────────────────────────────────────────

    def report(self, **kw) -> str:
        """体检报告（只读，不修改模型）"""
        from .report import report as _report
        return _report(self, **kw)

    def export_dxf(self, path: str, **kw) -> str:
        from .export import export_dxf as _dxf
        return _dxf(self, path, **kw)

    def export_fea(self, nodes_path: str, members_path: str, **kw):
        from .export import export_fea as _fea
        return _fea(self, nodes_path, members_path, **kw)

    # ── 删除与合并 ────────────────────────────────────────

    def _drop(self, mb: Member) -> None:
        self._members.pop(mb.id, None)
        self._poskey.pop((mb.group, min(mb.i, mb.j), max(mb.i, mb.j)), None)
        self._nodes[mb.i].sources.discard(mb.id)
        self._nodes[mb.j].sources.discard(mb.id)

    def remove(self, pred) -> int:
        """删构件。pred 可以是筛选函数、单个 Member、或 Member 列表。
        注意：不会自动把因此断开的构件合并回去。"""
        if callable(pred):
            targets = [mb for mb in self._members.values() if pred(mb)]
        elif isinstance(pred, Member):
            targets = [pred]
        else:
            targets = list(pred)
        n = 0
        for mb in targets:
            if mb.id in self._members:
                self._drop(mb)
                n += 1
        return n

    def _neighbors(self, mb: Member) -> list[Member]:
        """与 mb 共享节点、origin 相同、且该节点无其他构件的相邻段"""
        out = []
        for nid in (mb.i, mb.j):
            node = self._nodes[nid]
            others = [self._members[m] for m in node.sources
                      if m != mb.id and m in self._members]
            if len(others) != 1:
                continue
            other = others[0]
            if other.origin == mb.origin and other.group == mb.group:
                out.append(other)
        return out

    def merge_orphans(self) -> int:
        """批量合并「确定安全」的断点：origin 相同 + 相接 + 该节点无其他构件。
        返回合并掉的构件数。"""
        merged = 0
        changed = True
        while changed:
            changed = False
            for mb in list(self._members.values()):
                if mb.id not in self._members:
                    continue
                for other in self._neighbors(mb):
                    if other.id not in self._members:
                        continue
                    self._merge_pair(mb, other, prefer="a")
                    merged += 1
                    changed = True
                    break
                if changed:
                    break
        return merged

    def merge(self, a: Member, b: Member, *, attrs: str = "a") -> Member:
        """显式合并两根（打断的逆操作）。attrs='a'|'b' 指定冲突时保留谁。"""
        if a.id not in self._members or b.id not in self._members:
            raise ValueError("构件已被删除")
        if a.origin != b.origin:
            raise ValueError(f"origin 不同，不是同一根构件的分段：{a.origin} vs {b.origin}")
        common = {a.i, a.j} & {b.i, b.j}
        if len(common) != 1:
            raise ValueError("两根必须恰好共享一个节点")
        return self._merge_pair(a, b, prefer=attrs)

    def _merge_pair(self, a: Member, b: Member, prefer: str) -> Member:
        """合并两根首尾相接的构件。方向按「前段在前、后段在后」保持，
        不做 i/j 原地交换（那会破坏方向与 sources 的一致性）。"""
        common = {a.i, a.j} & {b.i, b.j}
        if len(common) != 1:
            raise ValueError("两根必须恰好共享一个节点")
        common = common.pop()
        if a.j == common and b.i == common:
            first, second = a, b
        elif a.i == common and b.j == common:
            first, second = b, a
        else:  # pragma: no cover - 由 len(common)==1 保证不会发生
            raise ValueError("两根必须首尾相接")

        if a.attrs == b.attrs:
            keep = dict(a.attrs)
        elif prefer == "a":
            keep = dict(a.attrs)
        elif prefer == "b":
            keep = dict(b.attrs)
        else:
            raise ValueError("两段 attrs 不一致，请用 attrs='a' 或 attrs='b' 指定保留哪一份")

        new_i, new_j = first.i, second.j
        new_ends = {"i": first.ends.get("i"), "j": second.ends.get("j")}
        origin, group = first.origin, first.group

        self._drop(a)
        self._drop(b)
        merged = Member(id=self._next_member, i=new_i, j=new_j, group=group,
                        attrs=keep, ends=new_ends, origin=origin)
        self._next_member += 1
        self._members[merged.id] = merged
        self._poskey[(group, min(new_i, new_j), max(new_i, new_j))] = merged.id
        self._nodes[new_i].sources.add(merged.id)
        self._nodes[new_j].sources.add(merged.id)
        return merged


# ─────────────────────────────────────────────────────────────
# Group
# ─────────────────────────────────────────────────────────────

def _as_pointset(P) -> PointSet:
    """宽容入口：PointSet 直接用；坐标列表自动转成显式点表；Axis 明确拒绝。"""
    if isinstance(P, PointSet):
        return P
    if isinstance(P, Axis):
        raise TypeError(
            f"Axis 是一维坐标表，不能直接当点集用；请用 X * Z * Y 张成点集，"
            f"或改用 add_chain({P.axis}-轴, along=...)"
        )
    return PointSet.of(list(P))


class Group:
    """一组构件的元数据 + 操作。由 Model.define 创建。"""

    def __init__(self, model: Model, name: str, *, split, attrs, keys, ends,
                 split_ends):
        self._model = model
        self.name = name
        self.split = split
        self.attrs = dict(attrs or {})
        self.keys = keys
        self.ends = dict(ends or {})
        self.split_ends = split_ends
        self._seq = 0

    # ── 生成 ──────────────────────────────────────────────

    def _check(self, extra: dict) -> dict:
        merged = dict(self.attrs)
        merged.update(extra)
        if self.keys:
            unknown = set(merged) - set(self.keys)
            if unknown:
                raise KeyError(
                    f"组 {self.name!r} 不认识属性 {sorted(unknown)}；"
                    f"已声明：{sorted(self.keys)}"
                )
        self._seq += 1
        return merged

    def add(self, p, q, **attrs) -> Member | list[Member]:
        merged = self._check(attrs)
        origin = (self.name, self._seq)
        return self._model._add(p, q, self, merged, dict(self.ends), origin)

    def add_pairs(self, P1, P2, **attrs) -> list[Member]:
        """两个点集逐点配对（形状必须完全一致，不做广播；整批预检）"""
        P1, P2 = _as_pointset(P1), _as_pointset(P2)
        if P1.shape != P2.shape:
            raise ValueError(f"两个点集形状必须一致：{P1.shape} vs {P2.shape}")
        left = list(P1.points())
        right = list(P2.points())
        return self._add_many(list(zip(left, right)), attrs)

    def add_chain(self, P, along: str = "x", **attrs) -> list[Member]:
        """沿某方向把相邻点连起来"""
        P = _as_pointset(P)
        pos = P._axis_pos(along)
        buckets: dict[tuple, list[tuple[tuple, tuple]]] = defaultdict(list)
        for idx, coord in P.items():
            key = idx[:pos] + idx[pos + 1:]
            buckets[key].append((idx, coord))
        pairs = []
        for bucket in buckets.values():
            bucket.sort(key=lambda t: t[0][pos])
            for (_, a), (_, b) in zip(bucket, bucket[1:]):
                pairs.append((a, b))
        return self._add_many(pairs, attrs)

    def add_X(self, P, **attrs) -> list[Member]:
        """每个矩形格画两条对角线（X 形）"""
        P = _as_pointset(P)
        if len(P.axes) != 2:
            raise ValueError(f"add_X 需要 2 维点集，收到 {len(P.axes)} 维")
        pts = {idx: coord for idx, coord in P.items()}
        n0, n1 = P.shape
        pairs = []
        for i in range(n0 - 1):
            for j in range(n1 - 1):
                a = pts.get((i, j))
                b = pts.get((i + 1, j))
                c = pts.get((i, j + 1))
                d = pts.get((i + 1, j + 1))
                if None in (a, b, c, d):
                    continue
                pairs.append((a, d))
                pairs.append((b, c))
        return self._add_many(pairs, attrs)

    def add_zigzag(self, P, along: str = "y", **attrs) -> list[Member]:
        """每格一根斜杆，方向逐格交替（之字形）"""
        P = _as_pointset(P)
        if len(P.axes) != 2:
            raise ValueError(f"add_zigzag 需要 2 维点集，收到 {len(P.axes)} 维")
        pos = P._axis_pos(along)
        other = 1 - pos
        pts = {idx: coord for idx, coord in P.items()}
        n0, n1 = P.shape
        pairs = []
        for i in range(n0 - 1):
            for j in range(n1 - 1):
                # 两端的两个点：沿 along 的两个索引 + other 维的一个索引
                if pos == 0:      # along 是第 0 维
                    low_a, low_b = (i, j), (i + 1, j)
                    hi_a, hi_b = (i, j + 1), (i + 1, j + 1)
                    flip = (i + j) % 2
                else:             # along 是第 1 维
                    low_a, low_b = (i, j), (i, j + 1)
                    hi_a, hi_b = (i + 1, j), (i + 1, j + 1)
                    flip = (i + j) % 2
                a = pts.get(low_a)
                b = pts.get(low_b)
                c = pts.get(hi_a)
                d = pts.get(hi_b)
                if None in (a, b, c, d):
                    continue
                if flip:
                    pairs.append((b, c))
                else:
                    pairs.append((a, d))
        return self._add_many(pairs, attrs)

    def _add_many(self, pairs: list[tuple], attrs: dict) -> list[Member]:
        if not pairs:
            return []
        model = self._model
        # 预检：整批原子（任何一根重位则整批拒绝）
        seen = set()
        for p, q in pairs:
            ni, nj = model._node_id(p), model._node_id(q)
            key = (self.name, min(ni, nj), max(ni, nj))
            if key in model._poskey or key in seen:
                raise ConflictError(
                    f"组 {self.name!r} 批量添加冲突：{tuple(to_mm(v) for v in p)} → "
                    f"{tuple(to_mm(v) for v in q)}"
                )
            seen.add(key)
        out: list[Member] = []
        for p, q in pairs:
            got = self.add(p, q, **attrs)
            out.extend(got if isinstance(got, list) else [got])
        return out

    # ── 查询与修改 ────────────────────────────────────────

    def all(self) -> list[Member]:
        return [mb for mb in self._model.members.values() if mb.group == self.name]

    def count(self) -> int:
        return len(self.all())

    def where(self, pred: Callable[[Member], bool]) -> list[Member]:
        return [mb for mb in self.all() if pred(mb)]

    def set(self, **attrs) -> int:
        """批量改已有构件的 attrs（只影响已生成的）"""
        items = self.all()
        for mb in items:
            mb.attrs.update(attrs)
        return len(items)

    def set_ends(self, i=None, j=None) -> int:
        items = self.all()
        for mb in items:
            if i is not None:
                mb.ends["i"] = i
            if j is not None:
                mb.ends["j"] = j
        return len(items)

    def remove(self, pred: Callable[[Member], bool] | None = None) -> int:
        if pred is None:
            return self._model.remove(self.all())
        return self._model.remove([mb for mb in self.all() if pred(mb)])

    def clear(self) -> int:
        return self.remove()

    def __repr__(self) -> str:
        return f"Group({self.name!r}, split={self.split!r}, n={self.count()})"