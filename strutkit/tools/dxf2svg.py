"""把 strutkit 导出的 DXF 渲染成 SVG / PNG 预览。

    python tools/dxf2svg.py out/frame.dxf

默认只出等轴测图 <name>_iso.png（加 --svg 同时输出矢量版）。
需要别的视图时用 --views 指定，逗号分隔：

    --views front          正立面 X–Z
    --views front,side     正立面 + 侧立面
    --views front,side,top,iso   全部

可选：--only-y <值> / --y-range <a,b> 按 Y 切片；--stretch 允许非等比拉伸

只认 LINE 实体（本库导出的 DXF 只有 LINE）。
"""

from __future__ import annotations

import math
import os
import sys

COLORS = {
    # 立柱
    "LZ":     (32, 92, 168),
    "COL":    (32, 92, 168),
    # 横梁 / 主梁（X 向绿、Y 向蓝，便于区分双向）
    "HL":     (40, 150, 80),
    "MBEAM":  (40, 150, 80),
    "MBX":    (40, 150, 80),
    "MBY":    (60, 90, 200),
    # 次梁
    "SEC":    (200, 120, 20),
    # 斜撑 / 横撑
    "XC":     (214, 130, 26),
    "YBRACE": (214, 130, 26),
    "ZBRACE": (214, 130, 26),
    # 水平拉 / 交叉支撑
    "SPL":    (150, 70, 180),
    "SPACER": (150, 150, 150),
    "BL":     (200, 50, 50),
    # 其他
    "NT":     (120, 120, 120),
}
DEFAULT_COLOR = (110, 110, 110)

# 线宽：竖向主构件加粗，避免密集图里被淹没
WIDTHS = {"LZ": 2, "COL": 2, "BL": 2, "SEC": 1}


def parse_dxf(path):
    """返回 [(layer, (x,y,z), (x,y,z)), ...]"""
    with open(path, encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f]
    out = []
    i = 0
    n = len(lines)
    while i < n - 1:
        if lines[i].strip() == "0" and lines[i + 1].strip() == "LINE":
            ent = {}
            j = i + 2
            while j < n - 1 and lines[j].strip() != "0":
                ent[lines[j].strip()] = lines[j + 1].strip()
                j += 2
            try:
                a = (float(ent["10"]), float(ent["20"]), float(ent["30"]))
                b = (float(ent["11"]), float(ent["21"]), float(ent["31"]))
                out.append((ent.get("8", "0"), a, b))
            except KeyError:
                pass
            i = j
        else:
            i += 1
    return out


def _project(kind):
    if kind == "front":
        return lambda p: (p[0], p[2])
    if kind == "side":
        return lambda p: (p[1], p[2])
    if kind == "top":
        return lambda p: (p[0], p[1])
    if kind == "iso":
        # 等轴测：Z 轴在屏幕上指向上方
        #   u = (x − y)·cos30
        #   v = z − (x + y)·sin30
        c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
        return lambda p: ((p[0] - p[1]) * c, p[2] - (p[0] + p[1]) * s)
    raise ValueError(kind)


def _filter_y(lines, only_y=None, y_range=None):
    """only_y: 两端 y 都等于该值；y_range: 两端 y 都落在 [y0, y1] 内"""
    if only_y is not None:
        return [(layer, a, b) for layer, a, b in lines
                if abs(a[1] - only_y) < 1e-6 and abs(b[1] - only_y) < 1e-6]
    if y_range is not None:
        y0, y1 = y_range
        return [(layer, a, b) for layer, a, b in lines
                if y0 - 1e-6 <= a[1] <= y1 + 1e-6 and y0 - 1e-6 <= b[1] <= y1 + 1e-6]
    return lines


def _fit(lines, proj, w, h, pad, stretch=False):
    pts = []
    for _, a, b in lines:
        pts.append(proj(a))
        pts.append(proj(b))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    sx = (w - 2 * pad) / max(maxx - minx, 1e-9)
    sy = (h - 2 * pad) / max(maxy - miny, 1e-9)
    kx, ky = (sx, sy) if stretch else (min(sx, sy), min(sx, sy))

    def tx(p):
        return (pad + (p[0] - minx) * kx, h - pad - (p[1] - miny) * ky)

    return tx, min(kx, ky)


AXIS_COLORS = {"X": (200, 50, 50), "Y": (40, 150, 60), "Z": (50, 80, 200)}


def _axis_vectors(kind, size=64):
    """坐标轴在屏幕上的方向（屏幕坐标 y 向下），与各视图的投影保持一致"""
    c, s30 = math.cos(math.radians(30)), math.sin(math.radians(30))
    if kind == "iso":
        return {"X": (c * size, s30 * size), "Y": (-c * size, s30 * size), "Z": (0, -size)}
    if kind == "front":
        return {"X": (size, 0), "Z": (0, -size)}
    if kind == "side":
        return {"Y": (size, 0), "Z": (0, -size)}
    return {"X": (size, 0), "Y": (0, size)}          # top


def _draw_axes(d, kind, ox, oy, size=64, font=None):
    """PIL：在 (ox, oy) 处画坐标轴指示器"""
    for name, (dx, dy) in _axis_vectors(kind, size).items():
        c = AXIS_COLORS[name]
        d.line([(ox, oy), (ox + dx, oy + dy)], fill=c, width=2)
        d.text((ox + dx * 1.2 - 6, oy + dy * 1.2 - 10), name, fill=c, font=font)


def write_svg(lines, path, kind, *, w=1800, h=1100, pad=30, only_y=None,
              y_range=None, stretch=False, axes=True):
    lines = _filter_y(lines, only_y, y_range)
    proj = _project(kind)
    tx, scale = _fit(lines, proj, w, h, pad, stretch)

    buckets: dict[str, list[str]] = {}
    for layer, a, b in lines:
        p, q = tx(proj(a)), tx(proj(b))
        buckets.setdefault(layer, []).append(
            f"M{p[0]:.1f},{p[1]:.1f}L{q[0]:.1f},{q[1]:.1f}"
        )

    title = {"front": "正立面 X–Z", "side": "侧立面 Y–Z",
             "top": "平面 X–Y", "iso": "等轴测"}[kind]
    if only_y is not None:
        title += f"（仅 y = {only_y:g}）"
    elif y_range is not None:
        title += f"（y ∈ [{y_range[0]:g}, {y_range[1]:g}]）"

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">',
        f'<rect width="{w}" height="{h}" fill="white"/>',
        f'<text x="{w/2}" y="22" text-anchor="middle" font-size="15" '
        f'font-family="sans-serif" fill="#333">{title}　共 {len(lines)} 条线</text>',
    ]
    for layer, segs in sorted(buckets.items()):
        r, g, b = COLORS.get(layer, DEFAULT_COLOR)
        parts.append(
            f'<path d="{"".join(segs)}" stroke="rgb({r},{g},{b})" '
            f'stroke-width="0.7" fill="none"/>'
        )
    x = pad
    for layer in sorted(buckets):
        r, g, b = COLORS.get(layer, DEFAULT_COLOR)
        parts.append(f'<rect x="{x}" y="{h-18}" width="10" height="10" fill="rgb({r},{g},{b})"/>')
        parts.append(f'<text x="{x+14}" y="{h-8}" font-size="12" '
                     f'font-family="sans-serif" fill="#333">{layer} ({len(buckets[layer])})</text>')
        x += 90
    # ── 左下角坐标轴指示器 ──
    if axes:
        ox_, oy_ = pad + 40, h - pad - 70
        for name, (dx, dy) in _axis_vectors(kind, 64).items():
            r_, g_, b_ = AXIS_COLORS[name]
            parts.append(
                f'<line x1="{ox_}" y1="{oy_}" x2="{ox_+dx:.1f}" y2="{oy_+dy:.1f}" '
                f'stroke="rgb({r_},{g_},{b_})" stroke-width="2"/>'
            )
            parts.append(
                f'<text x="{ox_+dx*1.2-6:.1f}" y="{oy_+dy*1.2-2:.1f}" '
                f'font-size="16" font-family="sans-serif" '
                f'fill="rgb({r_},{g_},{b_})">{name}</text>'
            )

    parts.append("</svg>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    return len(lines)


def write_png(lines, path, kind, *, w=2400, h=1400, pad=40, only_y=None,
              y_range=None, stretch=False, axes=True):
    """axes=True 时在左下角画坐标轴指示器（X 红 / Y 绿 / Z 蓝）。"""
    from PIL import Image, ImageDraw

    lines = _filter_y(lines, only_y, y_range)
    proj = _project(kind)
    tx, scale = _fit(lines, proj, w, h, pad, stretch)

    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    for layer, a, b in lines:
        p, q = tx(proj(a)), tx(proj(b))
        d.line([p, q], fill=COLORS.get(layer, DEFAULT_COLOR),
               width=WIDTHS.get(layer, 1))

    # ── 左下角坐标轴指示器（不画在地面上，避免被误认为构件）──
    if axes:
        try:
            from PIL import ImageFont
            font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 22)
        except Exception:
            font = None
        _draw_axes(d, kind, pad + 40, h - pad - 70, size=64, font=font)

    img.save(path)
    return len(lines)


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    src = argv[0]
    stretch = "--stretch" in argv
    only_y = None
    y_range = None
    if "--only-y" in argv:
        only_y = float(argv[argv.index("--only-y") + 1])
    if "--y-range" in argv:
        a, b = argv[argv.index("--y-range") + 1].split(",")
        y_range = (float(a), float(b))

    lines = parse_dxf(src)
    base = os.path.splitext(src)[0]
    print(f"读入 {len(lines)} 条 LINE")

    if only_y is not None:
        suffix = f"_y{only_y:g}"
    elif y_range is not None:
        suffix = f"_y{y_range[0]:g}-{y_range[1]:g}"
    else:
        suffix = ""

    views = argv[argv.index("--views") + 1].split(",") if "--views" in argv else ["iso"]
    for kind in views:
        svg_path = f"{base}_{kind}{suffix}.svg"
        png_path = f"{base}_{kind}{suffix}.png"
        n = write_png(lines, png_path, kind, only_y=only_y, y_range=y_range, stretch=stretch)
        note = ""
        if "--svg" in argv:
            write_svg(lines, svg_path, kind, only_y=only_y, y_range=y_range, stretch=stretch)
            note = " + .svg"
        print(f"  {kind:<6} → {kind}.png{note}  ({n} 条)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))