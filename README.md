# strutkit

通用杆系几何建模库。把任意结构离散成「有限个节点 + 有限根杆件」，让**几何精确、属性原样、问题可见**。

不涉及任何力学计算——荷载、截面、铰接/刚接、支座上拔，全部作为属性原样搬运。

库的词汇表里没有「柱」「梁」「货架」：只有 `Axis`（坐标轴 + 语义标签）、`PointSet`（点阵）、`Node`（节点）、`Member`（构件）、`Group`（组）。柱、梁、斜撑、桁架、网架、塔架、货架……都只是**你给组起的名字**，库不认、也不查。

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

**坐标约定**：X 纵向、Y 横向（宽度/进深）、**Z 竖直（重力方向 −Z）**。库本身与轴名无关，这个约定只影响脚本习惯和 DXF 在 CAD 里的朝向。

## 安装

仓库是标准 Python 项目（`pyproject.toml` + `strutkit/` 包），两种用法挑一个。

### ① 装进当前 Python 环境（推荐）

```bash
cd <仓库根>
pip install -e .
```

之后**任何目录**都能 `import strutkit`。`-e`（editable）只在 site-packages 里放一个指向本仓库的指针，不复制源码——所以改了代码立刻生效，不用重装。

**卸载：**

```bash
pip uninstall strutkit
```

先卸载、再删仓库目录。反过来（先删目录）会在 site-packages 里留下悬空指针，之后 `import strutkit` 报的错会莫名其妙。

> 想要标准 R2000 DXF 和 PNG 预览，一次装好可选依赖：`pip install -e ".[dxf,plot]"`（即 `ezdxf` + `Pillow`；不装也能跑，DXF 自动回退到手写 R12，`dxf2svg` 只出 SVG）。

### ② 不安装，用路径（零安装）

把**仓库根**（`strutkit/` 这一层）加进搜索路径即可，三种写法任选：

```python
import sys
sys.path.insert(0, r"<仓库根>")        # 指向 strutkit/ 这一层
from strutkit import Axis, Model
```

```cmd
set PYTHONPATH=<仓库根>               :: 当前窗口临时生效，或写进系统环境变量
```

好处是换机器拷目录就能用、没有安装残留；代价是每个脚本开头多两行。

> ⚠ **别在仓库的上一级目录里跑脚本。** 如果本仓库所在的那一层（比如 `Note/`）里有个同名目录 `strutkit/`（就是本仓库自己，没有 `__init__.py`），Python 会把它当成**空的命名空间包**，报 `cannot import name 'Axis' from 'strutkit' (unknown location)`——**装了包也一样**，因为当前目录排在搜索路径最前面。三个办法任选：① 换到别的目录跑；② 按上面 ② 把**仓库根**加进 `sys.path` / `PYTHONPATH`（顺序上会先命中真正的包，实测可行）；③ 把仓库目录改个名（如 `strutkit-repo/`），从根上没有同名目录。

## 快速开始
## 快速开始

```python
from strutkit import Axis, Model

X  = Axis.spans([3000, 3000, 3000], axis="x")                  # 0, 3000, 6000, 9000
Y  = Axis.spans([800], axis="y", role=["A", "B"])                # 0, 800
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
m.export_dxf("out/model.dxf", layers={"COLUMN": 2, "BEAM": 4})
m.export_fea("out/nodes.csv", "out/members.csv")
```

最小完整例：`python examples/frame_demo.py`（多层框架 + 次梁）
应用例（某货架项目）：`python examples/rack_demo.py`
真实规模回归：`python examples/lsp_regression.py`（13 跨 × 8 立柱线 × 30 层，9458 构件）

## 目录

仓库根**就是包目录**，`__init__.py` 在这一层：

```
strutkit/                ← 仓库根
├── pyproject.toml       安装与工具配置
├── README.md
├── strutkit/            ← 包本体
│   ├── __init__.py / geometry.py / model.py / diagnostics.py / export.py
│   └── tools/           dxf2svg.py：DXF → 轴测图（PNG/SVG）
├── docs/                入门教程：learn-strutkit.md
├── tests/               117 个测试（含 hypothesis 性质测试）
├── examples/            三个示例：多层框架（通用最小例）、货架项目（应用例）、真实规模回归
└── out/                 示例与导出的生成物（gitignore，不入库）
```

生成物一律写到 `out/`，代码目录保持干净。货架项目的资料（`货架体系文字描述.md`、`牛腿库.lsp` 等）留在 `货架体系` 仓库，不属于本库。

命令都在**仓库根**下执行：

```bash
cd <仓库根>
pip install -e .                                               # 可选：装进当前环境
python -m pytest tests -q                                      # 跑测试
python examples/frame_demo.py                                  # 通用最小例：多层框架 + 次梁
python examples/rack_demo.py                                   # 应用例：货架（大 X 背拉）
python examples/lsp_regression.py                              # 真实规模回归（9458 构件）
python -m strutkit.tools.dxf2svg out/frame.dxf                 # DXF → 轴测图
```

## 三条核心规则

1. **打断双向维持不变式**：新增构件时，新节点切旧杆、旧节点切新杆，所以书写顺序无关。
2. **`split` 默认 `"none"`**：打断会把一根杆变成两根、改变力学模型，属于破坏性操作，必须显式开启。
3. **库不做力学判断**：铰接/刚接/半刚接、只受拉、转动刚度，全部是用户填的属性，库只原样搬运并在报告里暴露问题。

## 精度：一个旋钮

坐标在入口处量化到 `set_quantum()` 指定的网格（默认 0.1mm），之后只存 μm 整数。所有几何判定也以这个步长为单位，**不存在第二个精度参数**。

| 判定 | 依据 |
|---|---|
| 两个坐标是否同一位置 | **落在同一个网格格子**（不是距离小于某个值） |
| 节点是否落在构件上 | 到直线的**垂直距离 ≤ 1 个量化步长** |

### 为什么是格子，不是距离

`(0.0499, 0)` 与 `(0.0501, 0)` 相距 0.0002mm，但跨在网格边界两侧 → **不合并**；而 `(0.051, 0)` 与 `(0.149, 0)` 相距 0.098mm → **合并**。

这不是缺陷。格子判定是一个**划分**：幂等、与顺序无关、可哈希。换成「距离小于 X 就合并」会得到一个不传递的关系（A≈B、B≈C 但 A≉C），合并结果将取决于处理的先后顺序。

### 为什么共线需要容差

共线是精确的代数条件（叉积 = 0），而量化不是线性映射 —— 本应共线的点会被挤出直线，最大偏离 `(q/2)·√3 ≈ 0.87q`。所以节点到构件的判定必须带容差，容差取 `1q` 正好覆盖。

例：3-4-5 斜杆的 1/3 处，理想标高 1333.333mm，量化后 1333.3mm —— 偏出直线 0.02mm。没有容差时这根杆不会被切，表现为「图上看着连上、计算里断开」。

容差用整数平方比较实现（`|cross|² ≤ tol²·|d|²`），不开方、不浮点，结果确定可复现。

**两条边界**：
- 容差只放宽「到直线的距离」，不放宽「落在两端之间」；且与两端各留一个容差，避免切出微段。
- 容差**只用于「点—线段」判定，不用于「点—点」合并**。合并一旦带上容差，就会退化成一个不传递的关系，顺序无关性随之崩塌。

### 推论：轴对齐杆与斜杆不对称

轴对齐构件垂直投影只改一个坐标，投影点仍落在网格上 —— 吸附是**无损**的。斜杆做不到：把节点吸到斜杆上的最近网格点，间距可达

```
网格点间距 = q · |d'|      （d' = 方向向量除以三轴 gcd）
```

实测某斜杆方向 `(600, 1033)` 的间距是 **119mm**，意味着「吸到线上最近的网格点」会挪动节点最多 60mm，不可用。所以斜杆只做容差判定，不做吸附。

## 文档

- 入门教程：`docs/learn-strutkit.md`
- 设计规划全书：`.sisyph/notes/2026-10-30-strutkit-设计规划.md`（在 货架体系 仓库）
- 一个真实项目的体系构成与计算假定：`货架体系文字描述.md`（项目根）
- 计算原则：`计算原则.md`（项目根）