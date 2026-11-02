"""多层框架 + 次梁（主梁刚接、次梁铰接）

几何：柱网 3 跨 × 2 跨（柱距 6000），4 层，层高 3900，顶标高 15600

        Y
        │
   12000├──●───●───●───●        柱网：X 4 条轴线 × Y 3 条轴线 = 12 根柱
        │  │   │   │   │
    6000├──●───●───●───●        X 向主梁：3 条 Y 线 × 3 跨 × 4 层 = 36 根
        │  │   │   │   │        Y 向主梁：4 条 X 线 × 2 跨 × 4 层 = 32 根
       0├──●───●───●───●        次梁   ：每 X 跨 2 根，沿 Y，共 3×2×2×4 = 48 根
         0  6000 12000 18000  X
                                        ↑ 次梁两端铰接在主梁上

标高：±0.000 只有柱脚（支座），**不建地梁、不建基础**——框架模型只管上部结构；
      楼面梁依次在 3.900 / 7.800 / 11.700 / 15.600。

演示四件事：
  1. **双向主梁**都布置，不是只有一个方向
  2. **split 白名单**：X 向主梁只允许被次梁打断（`split=["SEC"]`）
  3. **split_ends**：主梁被打断后接缝写「刚接」，力学上仍连续
  4. **端部条件分组填**：主梁刚接、次梁铰接，互不影响

坐标系：X 纵向、Y 进深、Z 竖直（重力方向 −Z）

    python strutkit/examples/frame_demo.py
"""

import os
import sys

# 把项目根加入搜索路径，这样不用安装也能 import strutkit
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 仓库根 = 包的上一级
sys.path.insert(0, _ROOT)     # 装过包（pip install -e .）就不需要这行，留着保证不装也能跑

from strutkit import Axis, Model

# ── 几何参数 ────────────────────────────────────────────────────
SPAN_X = 6000        # X 向柱距
SPAN_Y = 6000        # Y 向柱距
FLOOR_H = 3900       # 层高
N_FLOORS = 4         # 层数
SUB_PER_BAY = 2      # 每个 X 跨内布置几根次梁


def build(split_policy=None):
    """返回 (model, COL, MBEAM_X, MBEAM_Y, SEC)。测试复用这个函数。

    split_policy: 可覆盖 X 向主梁的白名单（测试用反例）。
    """
    X  = Axis.spans([SPAN_X] * 3, axis="x")                          # 0, 6000, 12000, 18000
    Y  = Axis.spans([SPAN_Y] * 2, axis="y")                          # 0, 6000, 12000
    ZL = Axis.spans([FLOOR_H] * N_FLOORS, axis="z", include_base=False)  # 3900 … 15600
    H  = ZL[-1]

    m = Model()

    # ── 组：几何、属性、端部条件、打断策略 ──────────────────────
    COL = m.define("COL", split="all",
                   attrs={"layer": "COL", "section": "H500"},
                   ends={"i": "刚接", "j": "刚接"},       # 柱脚固接、柱顶刚接
                   split_ends="刚接")                     # 被楼面梁打断处也连续

    MBX = m.define("MBX", split=split_policy or ["SEC"],  # 只允许被次梁打断
                   attrs={"layer": "MBX", "section": "HN400"},
                   ends={"i": "刚接", "j": "刚接"},
                   split_ends="刚接")

    MBY = m.define("MBY", split="none",                    # Y 向主梁不被次梁穿过
                   attrs={"layer": "MBY", "section": "HN400"},
                   ends={"i": "刚接", "j": "刚接"},
                   split_ends="刚接")

    SEC = m.define("SEC", split="none",                    # 次梁永不被打断
                   attrs={"layer": "SEC", "section": "HN250"},
                   ends={"i": "铰接", "j": "铰接"})        # 次梁两端铰接

    # ── 柱脚支座（节点属性）───────────────────────────────────
    # ±0.000 处不建地梁/基础：框架模型只描述上部结构，柱脚作为支座约束。
    for x in X:
        for y in Y:
            m.node((x, y, 0), attrs={"支座": "刚接"})

    # ── ① 柱：4 × 3 = 12 根 ──────────────────────────────────
    for x in X:
        for y in Y:
            COL.add((x, y, 0), (x, y, H))

    # ── ② X 向主梁：3 条 Y 线 × 3 跨 × 4 层 = 36 根 ───────────
    for z in ZL:
        for y in Y:
            for i in range(len(X) - 1):
                MBX.add((X[i], y, z), (X[i + 1], y, z))

    # ── ③ Y 向主梁：4 条 X 线 × 2 跨 × 4 层 = 32 根 ───────────
    for z in ZL:
        for x in X:
            for j in range(len(Y) - 1):
                MBY.add((x, Y[j], z), (x, Y[j + 1], z))

    # ── ④ 次梁：每 X 跨内分 SUB_PER_BAY 份，沿 Y 每跨一根 ──────
    for z in ZL:
        for i in range(len(X) - 1):
            for k in range(1, SUB_PER_BAY + 1):
                xc = X[i] + (X[i + 1] - X[i]) * k / (SUB_PER_BAY + 1)
                for j in range(len(Y) - 1):
                    SEC.add((xc, Y[j], z), (xc, Y[j + 1], z))

    return m, COL, MBX, MBY, SEC


def main():
    m, COL, MBX, MBY, SEC = build()

    print(m.report())

    print("\n── 分组与端部条件 ──")
    for name, grp in (("柱 COL", COL), ("X向主梁 MBX", MBX),
                      ("Y向主梁 MBY", MBY), ("次梁 SEC", SEC)):
        ends = {(mb.ends.get("i"), mb.ends.get("j")) for mb in grp.all()}
        print(f"  {name:<14} {len(grp.all()):>4} 段   端部 {sorted(ends, key=str)}")

    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(_ROOT, "out")      # 输出到仓库根的 out/（已 gitignore）
    os.makedirs(out, exist_ok=True)
    m.export_dxf(os.path.join(out, "frame.dxf"),
                 layers={"COL": 2, "MBX": 4, "MBY": 5, "SEC": 3})
    # 需要 FEA 表格时自行调用：m.export_fea("nodes.csv", "members.csv")
    print(f"\n已导出：{out}/frame.dxf")


if __name__ == "__main__":
    main()