"""用 `牛腿库.lsp` 的真实参数做回归

验证两件事：
  1. 新库自动算出的立柱分段 == LSP 手工算的 LZ1/LZ2
  2. 生成的构件数与逐条复现 LSP 逻辑的结果一致

坐标系：LSP 的 (x, y, h) → 新库的 (x, y, z)，Z 竖直。

    python examples/lsp_regression.py
"""

import os
import sys
import time

# 把项目根加入搜索路径，这样不用安装也能 import strutkit
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)

from strutkit import Axis, Model

# ── LSP 原始参数（逐字照抄）──────────────────────────────────
XC_dist = 1200
HL_h = [600, 550, 400, 400, 400, 650, 550, 400, 400, 400, 400, 650, 550, 400,
        400, 400, 400, 650, 550, 400, 400, 400, 400, 650, 550, 400, 400, 400,
        400, 500]
X_raw = [2640, 1066, 2640, 2640, 2640, 2640, 2640, 2640, 2640, 2640, 2640, 2640, 1170]
Y_raw = [710, 766, 1033, 766, 1033, 766, 710]

BL_X, BL_H, BL_X_n, BL_Y_n, BL_H_n = 1, 5, 5, 6, 5
SPL_X, SPL_Y, SPL_X_n, SPL_Y_n, SPL_H_n = 1, 1, 5, 1, 5


def cum(seq):
    """LSP 的 height2high：累加成坐标，含起点 0"""
    out = [0]
    for d in seq:
        out.append(out[-1] + d)
    return out


Xs = cum(X_raw)          # 14 个柱位
Ys = cum(Y_raw)          # 8 条立柱线
HL = cum(HL_h)           # 31 个标高（含 0 与顶）
TOP = HL[-1]
HALF = XC_dist // 2      # 600


def xc1_nodes():
    """A/D 柱（j%4 == 0 或 3）的斜撑节点：先 +600，再 +1200 循环，末尾 +600"""
    lst = [200]
    lst = [lst[0] + HALF] + lst
    while lst[0] + XC_dist <= TOP:
        lst = [lst[0] + XC_dist] + lst
    if lst[0] + HALF <= TOP:
        lst = [lst[0] + HALF] + lst
    lst.reverse()
    return lst


def xc2_nodes():
    """B/C 柱的斜撑节点：只 +1200 循环，末尾 +600"""
    lst = [200]
    while lst[0] + XC_dist <= TOP:
        lst = [lst[0] + XC_dist] + lst
    if lst[0] + HALF <= TOP:
        lst = [lst[0] + HALF] + lst
    lst.reverse()
    return lst


XC1 = xc1_nodes()
XC2 = xc2_nodes()
LZ1 = sorted(set(XC1) | set(HL))      # A/D 柱的节点标高（LSP 手工算的）
LZ2 = sorted(set(XC2) | set(HL))      # B/C 柱的节点标高


def zigzag(X1, Y1, X2, Y2, A, B):
    """复现 LSP 的 drawXC：两套标高交替，逐段前进"""
    out = []
    while A and B:
        out.append(((X1, Y1, A[0]), (X2, Y2, B[0])))
        X1, Y1, X2, Y2 = X2, Y2, X1, Y1
        A, B = B, A[1:]
    return out


def build():
    m = Model()
    COL  = m.define("LZ",  split="all",  attrs={"layer": "LZ",  "section": "C100"})
    XBR  = m.define("XC",  split="none", attrs={"layer": "XC",  "section": "L40"})
    BEAM = m.define("HL",  split="none", attrs={"layer": "HL",  "section": "HL-1"})
    SPL  = m.define("SPL", split="none", attrs={"layer": "SPL", "tension_only": True})
    BL   = m.define("BL",  split="none", attrs={"layer": "BL",  "tension_only": True})

    # ① 立柱：14 柱位 × 8 条线 = 112 根，从 0 到 TOP（分段交给打断）
    for j in range(len(Ys)):
        for i in range(len(Xs)):
            COL.add((Xs[i], Ys[j], 0), (Xs[i], Ys[j], TOP))

    # ② 斜撑：j ∈ {0,2,4,6} 的柱片平面内，逐 X 画之字折线
    for j in (0, 2, 4, 6):
        for i in range(len(Xs)):
            for p, q in zigzag(Xs[i], Ys[j], Xs[i], Ys[j + 1], XC1, XC2):
                XBR.add(p, q)

    # ③ 横梁：每个 (Y线, 跨, 标高)，去掉首末标高
    for j in range(len(Ys)):
        for i in range(len(Xs) - 1):
            for k in range(1, len(HL) - 1):
                BEAM.add((Xs[i], Ys[j], HL[k]), (Xs[i + 1], Ys[j], HL[k]))

    # ④ 水平拉：X 每 5 跨、Y 每段、H 每 5 层（跳过 k=0）
    for i in range(len(Xs)):
        if not (i + 1 < len(Xs) and i % SPL_X_n == 0):
            continue
        for j in range(len(Ys)):
            if not (j + 1 < len(Ys) and j % SPL_Y_n == 0):
                continue
            for k in range(len(HL)):
                if not (k + 1 < len(HL) and k % SPL_H_n == 0 and k != 0):
                    continue
                x0, x1 = Xs[i], Xs[i + SPL_X]
                y0, y1 = Ys[j], Ys[j + SPL_Y]
                z = HL[k]
                SPL.add((x0, y0, z), (x1, y1, z))
                SPL.add((x0, y1, z), (x1, y0, z))

    # ⑤ 背拉：X 每 5 跨、Y 每 6 段（余 1）、H 每 5 层；竖向跨 BL_H 层
    for i in range(len(Xs)):
        if not (i < len(Xs) and i % BL_X_n == 0):
            continue
        for j in range(len(Ys)):
            if not (j < len(Ys) and j % BL_Y_n == 1):
                continue
            for k in range(len(HL)):
                if not (k < len(HL) and k % BL_H_n == 0):
                    continue
                k2 = k + BL_H
                if k2 >= len(HL):          # LSP 里 nth 越界返回 nil，不画
                    continue
                x0, x1, y = Xs[i], Xs[i + BL_X], Ys[j]
                BL.add((x0, y, HL[k]), (x1, y, HL[k2]))
                BL.add((x1, y, HL[k]), (x0, y, HL[k2]))
    return m, dict(COL=COL, XC=XBR, HL=BEAM, SPL=SPL, BL=BL)


def main():
    t0 = time.time()
    m, groups = build()
    dt = time.time() - t0

    print("=" * 66)
    print(f"建模完成：{dt:.1f} s")
    print(f"  节点 {len(m.nodes)}   构件 {len(m.members)}")
    for name, g in groups.items():
        print(f"    {name:<4} {g.count()}")
    print()

    # ── 回归 1：立柱分段数是否等于 LSP 手工算的 ──
    col_by_xy = {}
    for mb in groups["COL"].all():
        p = m.nodes[mb.i].xyz
        key = (p[0], p[1])
        col_by_xy.setdefault(key, []).append(mb)

    def to_um(v):
        return int(round(v * 1000))

    # 正确规则：斜撑画在 (Y[j], Y[j+1]) 平面内，起点 Y[j] 用 XC1 标高、
    # 终点 Y[j+1] 用 XC2 标高 → 偶数 j 的柱应被 XC1∪HL 打断，奇数 j 被 XC2∪HL。
    expect = {}
    for j in range(len(Ys)):
        n = len(LZ1 if j % 2 == 0 else LZ2) - 1
        for i in range(len(Xs)):
            expect[(to_um(Xs[i]), to_um(Ys[j]))] = n

    got = {k: len(v) for k, v in col_by_xy.items()}
    mismatch = [(k, got.get(k), expect.get(k)) for k in expect if got.get(k) != expect.get(k)]

    # 同时对比 LSP 自己的规则（(rem j 4) ∈ {0,3} → LZ1）
    lsp_expect = {}
    for j in range(len(Ys)):
        n = len(LZ1 if j % 4 in (0, 3) else LZ2) - 1
        for i in range(len(Xs)):
            lsp_expect[(to_um(Xs[i]), to_um(Ys[j]))] = n
    lsp_mismatch = [k for k in lsp_expect if got.get(k) != lsp_expect[k]]

    print("── 回归 1：立柱分段数 ──")
    print(f"  新库自动打断：{sorted(set(got.values()))} 段/根")
    print(f"  按「斜撑实际端点」推算：{sorted(set(expect.values()))} 段/根")
    print(f"  不一致：{len(mismatch)} 根" + ("  ✓" if not mismatch else f"  ✗ {mismatch[:3]}"))
    print(f"  按 LSP 原始规则((j mod 4)∈{{0,3}}→LZ1)：{len(lsp_mismatch)} 根不一致")
    print()
    print("  ⚠ LSP 自身的不一致（不是新库的问题）：")
    print("     斜撑画在 (Y[j], Y[j+1]) 平面内，起点用 XC1 标高、终点用 XC2 标高，")
    print("     所以偶数 j 的柱该用 LZ1、奇数 j 该用 LZ2；")
    print("     但 LSP 用的是 (j mod 4)∈{0,3}→LZ1，导致 j=2,3,6,7 四条线的柱分段标高错位。")
    print(f"     涉及 {len(lsp_mismatch)} 根柱：斜撑端点落在柱段中间，图上看着连上、实际断开。")
    print()

    # ── 回归 2：构件总数 ──
    print("── 回归 2：构件统计 ──")
    total = sum(g.count() for g in groups.values())
    print(f"  分组构件合计 {total}，模型总数 {len(m.members)}"
          + ("  ✓" if total == len(m.members) else "  ✗ 有未分组构件"))
    print()

    # ── 报告摘要 ──
    text = m.report(show_cuts=False)
    print(text.split("切点来源")[0].rstrip())
    print()

    # ── 导出 ──
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(_ROOT, "out")      # 输出到项目根的 out/，库目录保持干净
    os.makedirs(out, exist_ok=True)
    m.export_dxf(os.path.join(out, "rack_full.dxf"),
                 layers={"LZ": 2, "HL": 4, "XC": 7, "SPL": 6, "BL": 1})
    # 需要 FEA 表格时自行调用：m.export_fea("nodes.csv", "members.csv")
    print(f"已导出 {out}\\rack_full.dxf")


if __name__ == "__main__":
    main()