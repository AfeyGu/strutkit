"""坐标量化、一维轴、多维点集。

设计要点（见 .sisyph/notes/2026-10-30-货架几何库-设计规划.md）：
  - 对外单位 mm（float），对内单位 μm（int），入口处按 quantum 量化一次
  - 量化用「舍入到固定网格」而不是「容差比较」：一次决定，永久确定
  - Axis 是一维离散坐标表 + 每点语义角色；PointSet 是笛卡尔积的子集
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Iterable, Iterator, Sequence

UM_PER_MM = 1000
_AXES = ("x", "y", "z")

__all__ = ["Axis", "PointSet", "set_quantum", "get_quantum", "to_um", "to_mm"]


# ─────────────────────────────────────────────────────────────
# 量化
# ─────────────────────────────────────────────────────────────

def _round_half_away(x: float) -> int:
    """四舍五入（远离零方向），不用 Python round 的银行家舍入。"""
    return int(math.copysign(math.floor(abs(x) + 0.5), x))


class _Quantizer:
    """把 mm 值舍入到 quantum 网格，返回 μm 整数。

    用 Decimal 而不是浮点除法，否则 1033.55 / 0.1 会算成 10335.499999999998，
    被舍到 1033.5 而不是 1033.6。
    """

    __slots__ = ("quantum_mm", "step_um", "_q")

    def __init__(self, quantum_mm: float = 0.1):
        if not quantum_mm > 0:
            raise ValueError(f"quantum 必须为正数，收到 {quantum_mm!r}")
        self.quantum_mm = float(quantum_mm)
        self._q = Decimal(str(quantum_mm))
        self.step_um = _round_half_away(quantum_mm * UM_PER_MM)
        if self.step_um <= 0:
            raise ValueError(f"quantum 太小（{quantum_mm} mm 折算不足 1 μm）")

    def __call__(self, value_mm: float) -> int:
        d = Decimal(str(float(value_mm))) / self._q
        n = int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))
        return n * self.step_um


_QUANTIZER = _Quantizer(0.1)


def set_quantum(quantum_mm: float) -> None:
    """设置全局量化精度（默认 0.1 mm）。

    必须在构造任何 Axis 之前调用；一旦有 Axis 存在再改会改变身份体系，
    因此这里不做「事后兼容」，只负责把新值装上。
    """
    global _QUANTIZER
    _QUANTIZER = _Quantizer(quantum_mm)


def get_quantum() -> float:
    return _QUANTIZER.quantum_mm


def to_um(value_mm: float) -> int:
    """mm → μm 整数（带量化）"""
    return _QUANTIZER(value_mm)


def to_mm(value_um: int) -> float:
    """μm 整数 → mm"""
    return value_um / UM_PER_MM


# ─────────────────────────────────────────────────────────────
# Axis
# ─────────────────────────────────────────────────────────────

def _as_axis_name(axis: str) -> str:
    a = str(axis).lower()
    if a not in _AXES:
        raise ValueError(f"轴名必须是 'x'/'y'/'z'，收到 {axis!r}")
    return a


@dataclass(frozen=True)
class Axis:
    """一维离散坐标表。

    um    : 内部整数坐标（μm），严格递增
    axis  : 该轴映射到哪个空间方向（'x'/'y'/'z'）
    role  : 每个点的语义标签，长度必须等于点数
    name  : 可选显示名（报告里用）
    """

    axis: str
    um: tuple[int, ...]
    role: tuple[str, ...] | None = None
    name: str = ""

    # ── 构造 ──────────────────────────────────────────────

    @classmethod
    def _build(cls, coords_mm: Sequence[float], axis: str, role=None, name="") -> "Axis":
        if axis not in _AXES:
            raise ValueError(f"轴名必须是 'x'/'y'/'z'，收到 {axis!r}")
        um = tuple(to_um(v) for v in coords_mm)
        if not um:
            raise ValueError("轴不能为空")
        for a, b in zip(um, um[1:]):
            if b <= a:
                raise ValueError(
                    f"Axis 坐标必须严格递增：{to_mm(a)} → {to_mm(b)}"
                )
        if role is not None:
            role = tuple(role)
            if len(role) != len(um):
                raise ValueError(
                    f"role 长度 {len(role)} 与点数 {len(um)} 不一致"
                )
        return cls(axis=axis, um=um, role=role, name=name)

    @classmethod
    def spans(cls, deltas: Iterable[float], axis: str, base: float = 0.0,
              role=None, name="", include_base: bool = True) -> "Axis":
        """按间距序列累加出坐标。

        include_base=True （默认）：含起点 base → n 个间距得 n+1 个点
            典型用途：跨长 → 柱位（0, 3000, 6000, ...）
        include_base=False：不含起点 → n 个间距得 n 个点
            典型用途：层高 → 横梁层位（600, 1150, ...，地面不是一层）
        """
        coords = [base] if include_base else []
        v = base
        for d in deltas:
            v += d
            coords.append(v)
        if not coords:
            raise ValueError("spans 至少要产生一个点")
        return cls._build(coords, axis, role, name)

    @classmethod
    def points(cls, values: Iterable[float], axis: str, role=None, name="") -> "Axis":
        """直接给坐标值"""
        return cls._build(list(values), axis, role, name)

    @classmethod
    def step(cls, step: float, n: int, axis: str, base: float = 0.0,
             role=None, name="") -> "Axis":
        """等距 n 个点：base, base+step, ..., base+(n-1)*step"""
        if n <= 0:
            raise ValueError(f"n 必须为正整数，收到 {n!r}")
        return cls._build([base + i * step for i in range(n)], axis, role, name)

    # ── 查询 ──────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self.um)

    def __iter__(self) -> Iterator[float]:
        return (to_mm(v) for v in self.um)

    def __getitem__(self, key):
        if isinstance(key, int):
            return to_mm(self.um[key])
        # slice / list / tuple → 返回子轴
        if isinstance(key, slice):
            idx = tuple(range(len(self.um)))[key]
        else:
            idx = tuple(key)
        return self._take(idx)

    def _take(self, idx: Sequence[int]) -> "Axis":
        um = tuple(self.um[i] for i in idx)
        role = tuple(self.role[i] for i in idx) if self.role is not None else None
        return Axis(axis=self.axis, um=um, role=role, name=self.name)

    def um_at(self, i: int) -> int:
        """内部用：取第 i 个点的 μm 整数"""
        return self.um[i]

    @property
    def idx(self) -> range:
        return range(len(self.um))

    @property
    def cells(self) -> tuple[tuple[float, float], ...]:
        """n-1 个跨（相邻点对，mm）"""
        return tuple((to_mm(a), to_mm(b)) for a, b in zip(self.um, self.um[1:]))

    def role_of(self, label: str) -> float:
        """按语义角色取坐标（mm）。没有该角色则报错，不猜。"""
        if self.role is None:
            raise KeyError(
                f"轴 {self.name or self.axis!r} 没有角色标签；请先用 with_role() 标注"
            )
        try:
            i = self.role.index(label)
        except ValueError:
            raise KeyError(
                f"轴 {self.name or self.axis!r} 中没有角色 {label!r}；"
                f"已有角色：{list(self.role)}"
            ) from None
        return to_mm(self.um[i])

    def index_of(self, value: float) -> int:
        """反查索引；不存在则报错（不返回最近值）"""
        target = to_um(value)
        try:
            return self.um.index(target)
        except ValueError:
            raise ValueError(
                f"{value} mm 不在轴 {self.name or self.axis!r} 上"
            ) from None

    # ── 选择 ──────────────────────────────────────────────

    def where(self, fn: Callable[[int, float], bool]) -> "Axis":
        """按条件过滤，fn(索引, 坐标值) -> bool。返回新轴，role 保留。"""
        idx = [i for i, v in enumerate(self) if fn(i, v)]
        if not idx:
            raise ValueError("where() 过滤后没有剩余点")
        return self._take(idx)

    def with_role(self, role: Sequence[str] | None) -> "Axis":
        """显式重标角色"""
        if role is not None and len(role) != len(self.um):
            raise ValueError(f"role 长度 {len(role)} 与点数 {len(self.um)} 不一致")
        return Axis(axis=self.axis, um=self.um,
                    role=tuple(role) if role is not None else None, name=self.name)

    # ── 集合运算 ──────────────────────────────────────────

    def __add__(self, other: "Axis") -> "Axis":
        """拼接（保序、允许重复）。role：两边都有才拼，否则 None。"""
        if not isinstance(other, Axis):
            return NotImplemented
        if self.axis != other.axis:
            raise ValueError(f"不能拼接不同方向的轴：{self.axis} + {other.axis}")
        um = self.um + other.um
        if any(b <= a for a, b in zip(um, um[1:])):
            raise ValueError(
                "拼接后的轴不再严格递增。拼接要求 self 的最大值 < other 的最小值；"
                "如果想去重排序请用 |（并集）"
            )
        role = None
        if self.role is not None and other.role is not None:
            role = self.role + other.role
        return Axis(axis=self.axis, um=um, role=role, name=self.name)

    def _set_op(self, other: "Axis", op: str) -> "Axis":
        if not isinstance(other, Axis):
            return NotImplemented
        if self.axis != other.axis:
            raise ValueError(f"不能对不同方向的轴做集合运算：{self.axis} vs {other.axis}")
        a, b = set(self.um), set(other.um)
        if op == "or":
            um = tuple(sorted(a | b))
        elif op == "and":
            um = tuple(sorted(a & b))
        elif op == "sub":
            um = tuple(sorted(a - b))
        else:  # pragma: no cover
            raise ValueError(op)
        if not um:
            raise ValueError(f"集合运算结果为空心轴（{op}）")
        # 集合运算后 role 一律丢弃，避免错位
        return Axis(axis=self.axis, um=um, role=None, name=self.name)

    def __or__(self, other):  # 并集
        return self._set_op(other, "or")

    def __and__(self, other):  # 交集
        return self._set_op(other, "and")

    def __sub__(self, other):  # 差集
        return self._set_op(other, "sub")

    def __mul__(self, other):
        # 1) 与另一个轴 → 笛卡尔积
        if isinstance(other, Axis):
            return PointSet(axes=(self, other))
        # 2) 与点集 → 在前面加一维
        if isinstance(other, PointSet):
            return PointSet(axes=(self,) + other.axes, keep=None, offset=other.offset)
        # 3) 整数 → 重复（同一坐标表连排，要求严格递增）
        if isinstance(other, int):
            if other <= 0:
                raise ValueError(f"重复次数必须为正整数，收到 {other!r}")
            um = self.um
            for _ in range(other - 1):
                um = um + self.um
            if any(b <= a for a, b in zip(um, um[1:])):
                raise ValueError("重复后坐标不再严格递增，请检查轴是否有重叠")
            return Axis(axis=self.axis, um=um,
                        role=self.role * other if self.role else None, name=self.name)
        return NotImplemented

    # ── 变换 ──────────────────────────────────────────────

    def shift(self, d: float) -> "Axis":
        """整体平移（mm）。role 跟着点走，保留。"""
        delta = to_um(d)
        return Axis(axis=self.axis, um=tuple(v + delta for v in self.um),
                    role=self.role, name=self.name)

    def mirror(self, about: float = 0.0) -> "Axis":
        """按 about 镜像（mm）。结果仍严格递增，role 顺序反转。"""
        c = to_um(about)
        um = tuple(sorted(2 * c - v for v in self.um))
        role = tuple(reversed(self.role)) if self.role is not None else None
        return Axis(axis=self.axis, um=um, role=role, name=self.name)

    # ── 显示 ──────────────────────────────────────────────

    def __repr__(self) -> str:
        coords = ", ".join(f"{to_mm(v):g}" for v in self.um[:6])
        more = " …" if len(self.um) > 6 else ""
        return f"Axis({self.axis}, [{coords}{more}], n={len(self.um)})"


# ─────────────────────────────────────────────────────────────
# PointSet
# ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PointSet:
    """多维点集：笛卡尔积的子集。

    axes   : 每一维的坐标表（axis 名互不重复）
    keep   : 保留点的线性索引；None = 全选（纯笛卡尔积）
    offset : 整体平移（μm）
    """

    axes: tuple[Axis, ...]
    keep: tuple[int, ...] | None = None
    offset: tuple[int, int, int] = (0, 0, 0)

    def __post_init__(self):
        names = [a.axis for a in self.axes]
        if len(set(names)) != len(names):
            raise ValueError(f"PointSet 的轴方向重复：{names}")
        if self.keep is not None:
            total = 1
            for a in self.axes:
                total *= len(a)
            if any(i < 0 or i >= total for i in self.keep):
                raise ValueError("keep 索引越界")

    # ── 构造 ──────────────────────────────────────────────

    @classmethod
    def of(cls, points: Iterable[Sequence[float]]) -> "PointSet":
        """显式点表：退化为 3 个单点轴 + keep（只能当点列表用）"""
        pts = {tuple(to_um(c) for c in p) for p in points}
        if not pts:
            raise ValueError("点表为空")
        um_x = tuple(sorted({p[0] for p in pts}))
        um_y = tuple(sorted({p[1] for p in pts}))
        um_z = tuple(sorted({p[2] for p in pts}))
        axes = (Axis("x", um_x), Axis("y", um_y), Axis("z", um_z))
        nx, ny, nz = len(um_x), len(um_y), len(um_z)
        pos = {(u, v, w): i * ny * nz + j * nz + k
               for i, u in enumerate(um_x)
               for j, v in enumerate(um_y)
               for k, w in enumerate(um_z)}
        keep = tuple(sorted(pos[p] for p in pts))
        return cls(axes=axes, keep=keep)

    # ── 维度 ──────────────────────────────────────────────

    def __mul__(self, other):
        if isinstance(other, Axis):
            return PointSet(axes=self.axes + (other,), keep=None, offset=self.offset)
        if isinstance(other, PointSet):
            if other.offset != (0, 0, 0):
                raise ValueError("只允许左边带 offset 的乘法")
            return PointSet(axes=self.axes + other.axes, keep=None, offset=self.offset)
        return NotImplemented

    def __rmul__(self, other):
        if isinstance(other, Axis):
            return PointSet(axes=(other,) + self.axes, keep=None, offset=self.offset)
        return NotImplemented

    @property
    def shape(self) -> tuple[int, ...]:
        return tuple(len(a) for a in self.axes)

    def count(self) -> int:
        if self.keep is None:
            n = 1
            for a in self.axes:
                n *= len(a)
            return n
        return len(self.keep)

    # ── 迭代 ──────────────────────────────────────────────

    def items(self) -> Iterator[tuple[tuple[int, ...], tuple[float, float, float]]]:
        """迭代 (索引元组, 坐标 mm)"""
        shape = self.shape
        strides = []
        s = 1
        for n in reversed(shape):
            strides.append(s)
            s *= n
        strides.reverse()
        ox, oy, oz = self.offset
        keep = self.keep if self.keep is not None else range(self.count())
        for lin in keep:
            idx = []
            rem = lin
            for st, n in zip(strides, shape):
                idx.append(rem // st)
                rem %= st
            coord = [0, 0, 0]
            for i, ax in zip(idx, self.axes):
                coord[_AXES.index(ax.axis)] = ax.um[i]
            yield tuple(idx), (
                to_mm(coord[0] + ox), to_mm(coord[1] + oy), to_mm(coord[2] + oz)
            )

    def points(self) -> Iterator[tuple[float, float, float]]:
        for _, p in self.items():
            yield p

    def __iter__(self) -> Iterator[tuple[float, float, float]]:
        return self.points()

    def __len__(self) -> int:
        return self.count()

    # ── 选择 ──────────────────────────────────────────────

    def _axis_pos(self, name: str) -> int:
        for i, a in enumerate(self.axes):
            if a.axis == name:
                return i
        raise KeyError(f"点集中没有 {name!r} 方向的轴；现有：{[a.axis for a in self.axes]}")

    def at(self, **fixed) -> "PointSet":
        """固定若干维：P.at(x=2) 表示 x 维只取第 2 个值"""
        indices = {}
        for name, val in fixed.items():
            pos = self._axis_pos(_as_axis_name(name))
            ax = self.axes[pos]
            if isinstance(val, int):
                if not -len(ax) <= val < len(ax):
                    raise IndexError(f"{name}[{val}] 越界（长度 {len(ax)}）")
                indices[pos] = [val % len(ax)]
            else:
                indices[pos] = [ax.index_of(v) for v in val]
        return self._select(indices)

    def _select(self, indices: dict[int, list[int]]) -> "PointSet":
        new_axes = []
        for i, ax in enumerate(self.axes):
            new_axes.append(ax._take(indices[i]) if i in indices else ax)
        new = PointSet(axes=tuple(new_axes), keep=None, offset=self.offset)
        # 重建 keep：把原 keep 映射到新坐标
        if self.keep is None:
            # 全选中，但若某些维被限制，无需 keep
            return new
        # 有洞：按坐标重建
        old_pts = {tuple(p) for p in self.points()}
        keep = [i for i, (_, p) in enumerate(new.items()) if p in old_pts]
        if len(keep) == new.count():
            return new
        return PointSet(axes=new.axes, keep=tuple(keep), offset=new.offset)

    def mask(self, fn: Callable[[tuple[float, float, float]], bool]) -> "PointSet":
        """过滤点：fn(坐标) -> True 保留"""
        old_pts = {tuple(to_um(c) for c in p) for p in self.points()}
        kept = {tuple(to_um(c) for c in p) for p in self.points() if fn(p)}
        if not kept:
            raise ValueError("mask() 之后没有剩余点")
        full = PointSet(axes=self.axes, keep=None, offset=self.offset)
        keep = tuple(i for i, (_, p) in enumerate(full.items())
                     if tuple(to_um(c) for c in p) in kept)
        return PointSet(axes=self.axes, keep=keep, offset=self.offset)

    def where(self, fn: Callable[[tuple[int, ...], tuple[float, float, float]], bool]) -> "PointSet":
        """按 (索引, 坐标) 过滤"""
        kept = {tuple(to_um(c) for c in p) for idx, p in self.items() if fn(idx, p)}
        if not kept:
            raise ValueError("where() 之后没有剩余点")
        full = PointSet(axes=self.axes, keep=None, offset=self.offset)
        keep = tuple(i for i, (_, p) in enumerate(full.items())
                     if tuple(to_um(c) for c in p) in kept)
        return PointSet(axes=self.axes, keep=keep, offset=self.offset)

    def __getitem__(self, key) -> "PointSet":
        if not isinstance(key, tuple):
            key = (key,)
        if len(key) > len(self.axes):
            raise IndexError("索引维数超过点集维数")
        indices = {}
        for pos, k in enumerate(key):
            ax = self.axes[pos]
            if isinstance(k, int):
                indices[pos] = [k % len(ax)]
            elif isinstance(k, slice):
                indices[pos] = list(range(len(ax)))[k]
            else:
                indices[pos] = list(k)
        return self._select(indices)

    # ── 变换 ──────────────────────────────────────────────

    def shift(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> "PointSet":
        """整体平移（mm）。P.shift(z=-200) 即把点阵往 -Z 挪 200。"""
        ox, oy, oz = self.offset
        return PointSet(
            axes=self.axes,
            keep=self.keep,
            offset=(ox + to_um(x), oy + to_um(y), oz + to_um(z)),
        )

    def mirror(self, axis: str, about: float = 0.0) -> "PointSet":
        """镜像。注意：构件有朝向时须同时补偿 roll（本层不涉及）。"""
        name = _as_axis_name(axis)
        c = to_um(about)
        new_axes = []
        for ax in self.axes:
            if ax.axis == name:
                new_axes.append(ax.mirror(about))
            else:
                new_axes.append(ax)
        ox, oy, oz = self.offset
        off = [ox, oy, oz]
        k = _AXES.index(name)
        off[k] = 2 * c - off[k]
        # 轴已镜像到新位置，offset 也要镜像
        return PointSet(axes=tuple(new_axes), keep=self.keep,
                        offset=(off[0], off[1], off[2]))

    # ── 集合运算 ──────────────────────────────────────────

    def _pts_um(self) -> set[tuple[int, int, int]]:
        return {tuple(to_um(c) for c in p) for p in self.points()}

    def _same_layout(self, other: "PointSet") -> bool:
        return ([a.axis for a in self.axes] == [a.axis for a in other.axes])

    def _set_op(self, other: "PointSet", op: str) -> "PointSet":
        if not isinstance(other, PointSet):
            return NotImplemented
        if not self._same_layout(other):
            raise ValueError(
                f"集合运算要求轴的维度与方向一致："
                f"{[a.axis for a in self.axes]} vs {[a.axis for a in other.axes]}"
            )
        if op == "or":
            pts = self._pts_um() | other._pts_um()
        elif op == "and":
            pts = self._pts_um() & other._pts_um()
        else:
            pts = self._pts_um() - other._pts_um()
        if not pts:
            raise ValueError("集合运算结果为空")
        # 轴取并集（保守），再重算 keep
        new_axes = []
        for i, name in enumerate([a.axis for a in self.axes]):
            a, b = self.axes[i], other.axes[i]
            um = tuple(sorted(set(a.um) | set(b.um)))
            new_axes.append(Axis(axis=name, um=um))
        full = PointSet(axes=tuple(new_axes), keep=None)
        keep = tuple(i for i, (_, p) in enumerate(full.items())
                     if tuple(to_um(c) for c in p) in pts)
        return PointSet(axes=tuple(new_axes), keep=keep)

    def __or__(self, other):
        return self._set_op(other, "or")

    def __and__(self, other):
        return self._set_op(other, "and")

    def __sub__(self, other):
        return self._set_op(other, "sub")

    def __repr__(self) -> str:
        dims = ", ".join(f"{a.axis}[{len(a)}]" for a in self.axes)
        return f"PointSet({dims}, n={self.count()})"