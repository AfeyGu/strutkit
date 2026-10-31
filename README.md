# strutkit

通用杆系几何建模库。把任意结构离散成「有限个节点 + 有限根杆件」，让**几何精确、属性原样、问题可见**。

不涉及任何力学计算——荷载、截面、铰接/刚接、支座上拔，全部作为属性原样搬运。

```
坐标量化（μm 整数，零容差）
    ↓
Axis 轴 ────────── 数列 → 离散坐标 + 语义标签
PointSet 点阵 ──── 笛卡尔积、切片、打洞、平移镜像、并交差
NodePool 节点池 ── 精确去重 + 谁引用了我
Member 构件 ────── 两端节点 + 自由属性 + 端部条件 + 打断前身份
    ↓
出口：DXF（分图层直线）/ FEA（节点表 + 单元表）/ 体检报告
```

**坐标约定**：X 纵向、Y 进深、**Z 竖直（重力方向 −Z）**。库本身与轴名无关，这个约定只影响脚本习惯和 DXF 在 CAD 里的朝向。

## 怎么用（不用安装）

`strutkit/` 目录本身就是包，把它的**上一级**加入搜索路径即可，三种方式任选：

**① 脚本里两行（最省事）**

```python
import sys
sys.path.insert(0, r"F:\工作区\货架体系")     # 指向 strutkit 的上一级

from strutkit import Axis, Model
```

**② 环境变量 `PYTHONPATH`（一次配置，所有项目生效）**

```cmd
set PYTHONPATH=F:\工作区\货架体系          :: 当前窗口临时生效
```
或者加进「系统属性 → 环境变量 → 用户变量」长期生效。

**③ 想装进 Python 环境（可选）**

需要自己补一个 `pyproject.toml`。

> 为什么不做成 pip 包：这是自用库，代码会持续改。`sys.path` / `PYTHONPATH` 方式改完立即生效、换机器拷目录即可，没有安装卸载的负担。

## 快速开始

```python
from strutkit import Axis, Model

X  = Axis.spans([3000, 3000, 3000], axis="x")                  # 0, 3000, 6000, 9000
Y  = Axis.spans([800], axis="y", role=["前排", "后排"])           # 0, 800
ZL = Axis.spans([2000, 2000], axis="z", include_base=False)     # 2000, 4000

m = Model()
COL  = m.define("COL",  split="all",  attrs={"layer": "COLUMN"})
BEAM = m.define("BEAM", split="none", attrs={"layer": "BEAM"})

for x in X:
    for y in Y:
        COL.add((x, y, 0), (x, y, 5000))          # 柱：沿 Z 竖直
for z in ZL:
    for y in Y:
        for i in range(len(X) - 1):
            BEAM.add((X[i], y, z), (X[i + 1], y, z))

print(m.report())                       # 体检报告
m.export_dxf("out/rack.dxf", layers={"COLUMN": 2, "BEAM": 4})
m.export_fea("out/nodes.csv", "out/members.csv")
```

完整例子：`python examples/rack_demo.py`
真实规模回归：`python examples/lsp_regression.py`（13 跨 × 8 立柱线 × 30 层，9458 构件）

## 目录

```
strutkit/           ← 包本体（__init__.py 直接在这一层）
├── geometry.py / model.py / report.py / export.py
├── tests/          79 个测试
├── examples/       三个示例：货架、多层框架（带次梁）、真实规模回归
└── tools/          dxf2svg.py：DXF → 轴测图（PNG/SVG）
```

项目根目录（上一级）放资料：`货架体系文字描述.md`、`计算原则.md`、
`规范对比_28576与39681计算条文.md`、`结构描述.md`、`牛腿库.lsp`（旧实现），
以及 `.sisyph/notes/` 下的设计规划。

**库目录只放代码，不放生成物**。示例的输出（DXF、轴测图）统一写到项目根的 `out/`。

命令都在**项目根**下执行：

```bash
cd F:\工作区\货架体系
python -m pytest strutkit/tests/ -q                            # 跑测试
python strutkit/examples/rack_demo.py                          # 货架：大 X 背拉
python strutkit/examples/frame_demo.py                         # 框架：主梁刚接 + 次梁铰接
python strutkit/examples/lsp_regression.py                     # 真实规模回归（9458 构件）
python strutkit/tools/dxf2svg.py out/frame.dxf                # DXF → 轴测图
```

## 三条核心规则

1. **打断双向维持不变式**：新增构件时，新节点切旧杆、旧节点切新杆，所以书写顺序无关。
2. **`split` 默认 `"none"`**：打断会把一根杆变成两根、改变力学模型，属于破坏性操作，必须显式开启。
3. **库不做力学判断**：铰接/刚接/半刚接、只受拉、转动刚度，全部是用户填的属性，库只原样搬运并在报告里暴露问题。

## 文档

- 设计规划全书：`.sisyph/notes/2026-10-30-货架几何库-设计规划.md`
- 体系构成与计算假定：`docs/货架体系文字描述.md`
- 计算原则：`docs/计算原则.md`