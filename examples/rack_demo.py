"""典型货架：两排背靠背 × 10 跨 × 8 层

按 `货架体系文字描述.md` 的构件清单与几何规则建模（变体 A：有偏置、有水平系杆）。

平面（俯视）：

        y=2200 ┌────────────────────────────────────┐  排2 前立柱线
               │  排2 柱片（宽 W=900）              │
        y=1300 ├────────────────────────────────────┤  排2 后立柱线
               │  ▓ 垂直支撑（在间隙中间，距两侧各 200）
         y=900 ├────────────────────────────────────┤  排1 后立柱线
               │  排1 柱片（宽 W=900）              │
           y=0 └────────────────────────────────────┘  排1 前立柱线
               0        2800        5600        …   X（沿排列方向）

竖向（立面）：X 向 10 跨，Z 向 8 层（层高 2000，总高 16000）

构件与文档 §2 的对应：
  立柱 COL          66→44 根，横斜撑按 600 模数竖向分格（§4.1）
  横梁 BEAM         每层每两条立柱线各一道（§2）
  垂直斜拉杆 BL     只受拉，X 形交叉，交叉点不连接（§4.3）
  水平系杆 STRUT    垂直支撑格的上、下弦，可受压（§4.3）
  连接梁 CONN       沿 Y、长 Δ=200、两端刚接，锚回后立柱梁柱节点（§4.3）
  水平拉 SPL        水平面内跨一个货格的 X 形，设在垂直支撑所在列（§4.4）
  隔撑 SPACER       两排后立柱之间（§4.7）；垂直支撑所在高度由连接梁取代

坐标系：X 纵向、Y 进深、Z 竖直（重力方向 −Z）

    python strutkit/examples/rack_demo.py
"""

import os
import sys
import time

# 把项目根加入搜索路径，这样不用安装也能 import strutkit
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)

from strutkit import Axis, Model

# ── 几何参数 ────────────────────────────────────────────────────
SPAN_X   = 2800     # 横梁长度 L（相邻两柱片的间距）
DEPTH    = 900      # 柱片宽 W（同一柱片两根立柱的间距 = 货架深度）
GAP      = 400      # 两排背靠背之间的空隙 G
FLOOR_H  = 2000     # 层高 h
N_BAYS   = 10       # 跨数
N_FLOORS = 8        # 层数

# 柱片横斜撑的竖向分格（§4.1：最下层横撑距地 e=200，向上按 600 模数）
E_BOTTOM = 200
MODULE   = 600

# 垂直支撑布置（§4.3 变体 A）
DELTA     = GAP // 2    # 后立柱线外偏 Δ（位于两排之间，距两侧各 200）
BL_LAYERS = 2           # 竖向一格跨几层（1~2 层）
BL_EVERY  = 3           # 每几跨布置一道（文档 §8：n 常规 3）


def build():
    """返回 (model, 各组)。测试可复用。"""
    # 轴：4 条立柱线 = 排1（前 0 / 后 900）+ 间隙 + 排2（后 1300 / 前 2200）
    X  = Axis.spans([SPAN_X] * N_BAYS, axis="x")                       # 11 个柱位
    Y  = Axis.spans([DEPTH, GAP, DEPTH], axis="y")                     # 0, 900, 1300, 2200
    ZL = Axis.spans([FLOOR_H] * N_FLOORS, axis="z", include_base=False)  # 2000 … 16000
    H  = ZL[-1]

    FRAMES = [(0, 1), (2, 3)]        # 两个柱片：(前, 后)
    Y_BL   = Y[1] + DELTA            # 垂直支撑所在立面 = 1100（两排之间正中）

    m = Model()

    # ── 组 ────────────────────────────────────────────────────
    COL    = m.define("COL",    split="all",  attrs={"layer": "COL",    "section": "C100"},
                      ends={"i": "铰接", "j": "自由"}, split_ends="刚接")
    BEAM   = m.define("BEAM",   split="none", attrs={"layer": "BEAM",   "section": "HL-1"},
                      ends={"i": "铰接", "j": "铰接"})
    YBRACE = m.define("YBRACE", split="none", attrs={"layer": "YBRACE", "section": "L40x4"},
                      ends={"i": "铰接", "j": "铰接"})
    XBRACE = m.define("XBRACE", split="none", attrs={"layer": "XBRACE", "section": "L40x4"},
                      ends={"i": "铰接", "j": "铰接"})
    SPACER = m.define("SPACER", split="none", attrs={"layer": "SPACER", "section": "L30x3"},
                      ends={"i": "铰接", "j": "铰接"})
    CONN   = m.define("CONN",   split="none", attrs={"layer": "CONN",   "section": "HN200"},
                      ends={"i": "刚接", "j": "刚接"})
    STRUT  = m.define("STRUT",  split="none", attrs={"layer": "STRUT",  "section": "L50x5"},
                      ends={"i": "铰接", "j": "铰接"})
    BL     = m.define("BL",     split="none",
                      attrs={"layer": "BL", "section": "D20", "tension_only": True},
                      ends={"i": "铰接", "j": "铰接"})
    SPL    = m.define("SPL",    split="none",
                      attrs={"layer": "SPL", "section": "D16", "tension_only": True},
                      ends={"i": "铰接", "j": "铰接"})

    # ── 柱脚支座：三选一，货架常规铰接（§2）─────────────────────
    for x in X:
        for y in Y:
            m.node((x, y, 0), attrs={"支座": "铰接"})

    # ── ① 立柱：11 柱位 × 4 条线 = 44 根 ──────────────────────
    for x in X:
        for y in Y:
            COL.add((x, y, 0), (x, y, H))

    # ── ② 横梁：每层、每两条立柱线各一道 = 10×4×8 = 320 根 ─────
    for z in ZL:
        for y in Y:
            for i in range(len(X) - 1):
                BEAM.add((X[i], y, z), (X[i + 1], y, z))

    # ── ③ 柱片内横斜撑：600 模数分格（§4.1）───────────────────
    n_grid = int((H - E_BOTTOM) // MODULE)                     # 26 格
    z_grid = [E_BOTTOM + k * MODULE for k in range(n_grid + 1)]  # 200, 800, …, 15800

    for x in X:
        for a, b in FRAMES:
            ya, yb = Y[a], Y[b]
            # 横撑：柱片最下端（距地 200）与最上端各一道 —— §2 共 2 道
            YBRACE.add((x, ya, z_grid[0]), (x, yb, z_grid[0]))
            YBRACE.add((x, ya, z_grid[-1]), (x, yb, z_grid[-1]))
            # 之字斜撑：每 600 格一根，方向逐格交替 —— §4.1
            for k in range(n_grid):
                z0, z1 = z_grid[k], z_grid[k + 1]
                if k % 2 == 0:
                    XBRACE.add((x, ya, z0), (x, yb, z1))
                else:
                    XBRACE.add((x, yb, z0), (x, ya, z1))

    # ── ④ 垂直支撑（§4.3 变体 A）─────────────────────────────
    #     竖向格：从柱脚起每 BL_LAYERS 层一格，最下一格含柱脚段、无下弦
    bl_z   = [ZL[k] - FLOOR_H for k in range(0, N_FLOORS, BL_LAYERS)] + [H]
    bl_col = set(range(0, N_BAYS, BL_EVERY))          # 设支撑的列（跨索引）
    bl_x   = {X[i] for i in bl_col} | {X[i + 1] for i in bl_col}

    for i in range(0, N_BAYS, BL_EVERY):
        x0, x1 = X[i], X[i + 1]

        # 连接梁：锚回后立柱的「梁柱节点」，所以只设在各层横梁标高（不含柱脚）
        for z in bl_z[1:]:
            for x in (x0, x1):
                for yb in (Y[1], Y[2]):
                    CONN.add((x, yb, z), (x, Y_BL, z))

        # 水平系杆：每格上、下各一根（最下一格无下弦，即柱脚处不设）
        for z in bl_z[1:]:
            STRUT.add((x0, Y_BL, z), (x1, Y_BL, z))

        # 垂直斜拉杆：最下一格柱脚端直接落在立柱柱脚上（不偏置），
        # 水平推力由两个柱脚承担；其余各格在支撑立面内交叉
        BL.add((x0, Y[1], bl_z[0]), (x1, Y_BL, bl_z[1]))
        BL.add((x1, Y[2], bl_z[0]), (x0, Y_BL, bl_z[1]))
        for k in range(1, len(bl_z) - 1):
            z0, z1 = bl_z[k], bl_z[k + 1]
            BL.add((x0, Y_BL, z0), (x1, Y_BL, z1))
            BL.add((x1, Y_BL, z0), (x0, Y_BL, z1))

    # ── ⑤ 水平拉（§4.4）：水平面内跨一个货格（L×W）的 X 形 ──────
    for i in range(0, N_BAYS, BL_EVERY):
        for a, b in FRAMES:
            ya, yb = Y[a], Y[b]
            for z in ZL:
                SPL.add((X[i], ya, z), (X[i + 1], yb, z))
                SPL.add((X[i], yb, z), (X[i + 1], ya, z))

    # ── ⑥ 隔撑（§4.7）：两排后立柱之间，按 1~2 个层高的间距设，从首层楼面起 ──
    for i, x in enumerate(X):
        for z in ZL:                    # 不在 ±0 设（地面没有隔撑）
            if i in bl_col or i - 1 in bl_col:      # 支撑列的两端柱位
                if z in bl_z:                       # 支撑格高度 → 由连接梁取代
                    continue
            SPACER.add((x, Y[1], z), (x, Y[2], z))

    return m, COL, BEAM, YBRACE, XBRACE, SPACER, CONN, STRUT, BL, SPL


def main():
    t0 = time.time()
    m = build()[0]
    dt = time.time() - t0

    print(f"建模 {dt:.2f} s")
    print(m.report())

    out = os.path.join(_ROOT, "out")      # 输出到项目根的 out/，库目录保持干净
    os.makedirs(out, exist_ok=True)
    m.export_dxf(os.path.join(out, "rack.dxf"),
                 layers={"COL": 2, "BEAM": 4, "YBRACE": 7, "XBRACE": 6,
                         "SPACER": 8, "CONN": 3, "STRUT": 9, "BL": 1, "SPL": 5})
    # 需要 FEA 表格时自行调用：m.export_fea("nodes.csv", "members.csv")
    print(f"\n已导出：{out}/rack.dxf")


if __name__ == "__main__":
    main()