# strutkit 建模文档（入门）

> **一句话**：把脑子里的结构，翻译成「有限个节点 + 有限根杆件」，再导出成 CAD 图或有限元表格。
> 库不做力学计算，也不认构件类型：柱、梁、斜撑、桁架、网架……都只是**你给构件的组名**。

阅读顺序：§1 建立心智模型 → §2 认数据结构 → §3 记流程 → §4 跟着做一遍 → §5 按需查菜谱 → §6 补 Python 语法 → §7/§8 出事时查。

配套入口：`../README.md`（安装与定位）、`../examples/`（三个可运行实例）。设计取舍的完整记录在 货架体系 仓库的 `.sisyph/notes/2026-10-30-strutkit-设计规划.md`（不在本库内）。

---

## 0. 边界：它做什么、不做什么

| 做 | 不做 |
|---|---|
| 坐标离散与量化（μm 整数，判定零浮点） | 任何力学计算：内力、位移、稳定、截面验算 |
| 构件两端的连接关系（谁和谁共节点） | 判断铰接还是刚接——只搬运你填的值 |
| 打断、合并、去重、体检 | 荷载、荷载组合、支座刚度 |
| 导出 DXF / 有限元节点表与单元表 | 定了规则之外的建模逻辑（哪根柱该有支撑） |

判断标准只有一条：**这件事要不要看坐标、要不要看连接关系？** 要 → 归库；不要 → 归你的脚本或计算软件。

---

## 1. 整体理解

### 1.1 只有三个动作

```
① 造坐标     Axis / PointSet          数列 → 离散坐标 → 点阵
② 挂构件      Group.add                一端 + 另一端 + 属性
③ 取结果      report / export_*        体检报告 / DXF / 节点表 + 单元表
```

三者之外没有第四件事。力学、规范、选型都不在库里。

### 1.2 唯一不可违背的规矩

库里的 `Member`（构件）就是有限元里的「单元」。所以：

> **一根构件内部不允许有节点。**

节点落在杆件中间，必须先切开，这个动作叫**打断**。库在你每次 `add()` 时自动做，并且是**双向**的：

- **新节点切旧杆**：后加的梁端落在先建的柱身上 → 柱被切成两段；
- **旧节点切新杆**：柱子先建、梁后建，梁会撞上柱子已有的节点 → 梁被切成两段。

两个方向都做，结果才**与书写顺序无关**：先柱后梁、先梁后柱，节点表与单元表完全一致（`tests/test_order_independence.py` 用 4 类构件的 24 种顺序锁死这条）。

打断不是免费的：一根杆变两根，力学模型就变了（连续梁 vs 两根铰接梁）。所以控制打断的开关必须显式表达——

### 1.3 三个开关，划出打断的边界

| 开关 | 写在哪 | 管什么 | 默认 |
|---|---|---|---|
| `split` | `m.define(..., split=...)` | **哪些节点允许切我** | `"none"`（谁都不许切） |
| `ends` | `m.define(..., ends={...})` | 构件两端的连接条件 | 空（不猜） |
| `split_ends` | `m.define(..., split_ends=...)` | **被打断处**新接缝填什么端部条件 | 空（不猜） |

`split` 有四种取值：

```python
split="none"                                   # 谁都别切我（斜撑、大 X 拉杆常用）
split="all"                                    # 任何节点落在我身上都切（柱常用）
split=["SEC"]                                  # 只有 SEC 组带来的节点才切我（主梁常用）
split=("whitelist", {(3000.0, 0.0, 4000.0)})   # 只在这几个点坐标上才切我（少见，见 §5.6）
```

白名单写错不会抛异常，但会把证据留在报告里——见 §5.6 的两种白名单与反例。

---

## 2. 数据结构

### 2.1 全景

```
Axis ─┐
      ├── * ──→ PointSet ──┐
Axis ─┘                     │ 坐标
                            ↓
Model ─┬─ Group ── add() ──┬─→ Node    节点：一个位置 + 属性
       │                   └─→ Member  构件：两个节点 + 属性 + 端部条件
       └─ node() ───────────→ Node
```

| 名字 | 是什么 | 一句话记住 |
|---|---|---|
| `Axis` | 一维坐标表（严格递增）+ 每点的语义标签 | 「一条轴线上的所有柱位 / 标高」 |
| `PointSet` | 多维笛卡尔积的子集 | 「点阵，能切片、打洞、平移镜像」 |
| `Model` | 容器 | 「整个模型，唯一发 id 的地方」 |
| `Group` | 一组构件的模板：属性、端部条件、打断策略 | 「构件类型 + 它的规矩」 |
| `Node` | 位置（μm 整数）+ `attrs` + `sources`（谁引用我） | 「节点」 |
| `Member` | `i, j` 两个节点 + `group` + `attrs` + `ends` + `origin` | 「单元」 |

再分一层，这六个名字其实是两类东西：

- **值对象**（`Axis`、`PointSet`）：不可变、没有身份。基数相同就是「相等」，任何变换返回新对象。
- **实体对象**（`Model`、`Group`、`Node`、`Member`）：可变、有身份。`Node` / `Member` 靠 `id` 认身份，改了就是改了。

由此得到一条贯穿全库的规则——**看返回值就知道原对象有没有被动过**：

| 你手上是 | 变换类操作（`shift` / `mirror` / `mask` / `\|` / `+` …） | 原对象 |
|---|---|---|
| **值对象** `Axis`、`PointSet` | **返回一个新对象** | 一个字节都不变 |
| **实体对象** `Model`、`Group`、`Node`、`Member` | **原位修改**，返回句柄或数量 | 真的被改了 |

记法：**值对象像数字**（`x + 1` 不改 `x`），**实体对象像数据库**（`insert` 就是写进去了）。本书后续每个 API 都标了它属于哪一类，见 §8 速查表。

下面每个类都给出**源码里的字段骨架**，看清「里面到底存了什么」，后面用起来才不会靠猜。

### 2.2 单位与量化：只有一个旋钮

对外一律 **mm（float）**，对内一律 **μm（int）**。进库时量化一次，此后所有几何判定都在整数上做，不存在第二个精度参数。

```python
from strutkit import set_quantum, get_quantum, step_um

get_quantum()      # 0.1   默认网格 0.1 mm
step_um()          # 100   折算成 μm，是判定的容差单位
set_quantum(0.5)   # 改成 0.5 mm 网格；必须在建任何 Axis 之前调用
```

「同一位置」的判据是**落在同一个网格格子**，不是「距离小于某个值」：

```python
(0.0499, 0) 与 (0.0501, 0)   相距 0.0002mm → 不同格 → 两个节点
(0.051,  0) 与 (0.149,  0)   相距 0.098mm  → 同 一格 → 一个节点
```

这是刻意选的：格子判定是一个**划分**（幂等、与顺序无关、可哈希）。换成「距离小于 X 就合并」，得到的关系不传递（A≈B、B≈C 但 A≉C），合并结果会依赖处理顺序。

副作用要提前知道：轴坐标严格递增，两个输入值量化到同一格时 `Axis` 会直接报错，而不是悄悄合并：

```python
Axis.points([0.3, 0.7], axis="x")     # quantum=0.5 时两者都落到 0.5
# ValueError: Axis 坐标必须严格递增：0.5 → 0.5
```

### 2.3 Axis：一条轴线上的坐标表

**先破一个误解**：`Axis` 看起来像「带标签的数组」，但两者有四处实质区别，正是这四处让它好用：

| | 普通 list | `Axis` |
|---|---|---|
| 存什么 | 任意 float | 内部是 **μm 整数**（按 0.1mm 网格量化），读出来才变成 mm |
| 顺序 | 随意 | **必须严格递增**：不能重复、不能为空 |
| 能否改 | 可增删改 | **不可变**：`shift` / `mirror` / 集合运算都返回**新轴**，原轴不动 |
| 额外信息 | 无 | 知道自己是哪根空间轴（x/y/z），每个点可带一个名字（`role`） |

它只回答一个问题：**「这条轴线上，坐标是哪些值？」** 它不是容器——不能 append，想加点只能用 `|`（并集）或 `+`（拼接）造一根新轴。

四个字段：

| 字段 | 例子 | 作用 |
|---|---|---|
| `axis` | `"x"` | 属于哪个空间方向。**决定它拼进点阵时填哪一列**（见下） |
| `um` | `(0, 6000000, 12000000)` | 坐标本体，μm 整数、严格递增 |
| `role` | `("A", "B", "C")` | 每个点的名字，长度必须等于点数；可不填 |
| `name` | `"柱网"` | 纯装饰，只出现在报错信息和 `repr` 里 |

#### 内部结构：一个 frozen dataclass，四个字段

```python
@dataclass(frozen=True)
class Axis:
    axis: str                              # 'x' / 'y' / 'z'
    um: tuple[int, ...]                    # 坐标本体：μm 整数，严格递增
    role: tuple[str, ...] | None = None    # 每个点的名字，长度 = 点数
    name: str = ""                         # 显示名
```

四个字段就是全部，没有隐藏状态。两个选择值得知道为什么：

- **`um` 用 `tuple` 不用 `list`**：tuple 不可变、可哈希，配合 `frozen=True`，整个轴才能当字典键、放心在函数间共享。
- **坐标存 μm 整数**：几何判定全在整数上做，避开浮点误差（见 §2.2）。

#### 三个构造器：给坐标、给间距、给等距点

| 构造器 | 你给它什么 | 它给你什么 | 典型场景 |
|---|---|---|---|
| `Axis.points([...])` | **绝对坐标**（必须严格递增） | 原样 | 不规则柱位、从别处读来的标高 |
| `Axis.spans([...])` | **相邻间距**（库替你累加） | 累加后的坐标 | 等跨柱网、等层层高，混合跨长也行 |
| `Axis.step(d, n)` | 间距 + **点数 n** | n 个点 | 规则网格、等分点 |

```python
Axis.points([0, 6000, 12000], axis="x")     # 直接给坐标 → 0, 6000, 12000
Axis.spans([6000, 6000], axis="x")          # 给间距累加 → 0, 6000, 12000
Axis.step(6000, 3, axis="x")                # 等距 3 个点 → 0, 6000, 12000
```

三者结果可以完全相同，区别只在**你手上是哪种数据**。最容易差一位的地方：`step` 的 `n` 是**点数**，`spans` 数的是**间距数**：

```python
Axis.spans([6000] * 3, axis="x")   # 3 个间距 → 4 个点：0, 6000, 12000, 18000
Axis.step(6000, 4, axis="x")       # 4 个点   → 同上
```

三个构造器都能带 `role` 和 `name`（下一节细说）：

```python
Axis.spans([6000, 6000], axis="x", role=["柱1", "柱2", "柱3"])   # 3 个点 → 3 个名字
Axis.points([0, 6000], axis="x", role=["A", "B"])
Axis.step(6000, 3, axis="x", role=["柱1", "柱2", "柱3"])
```

`spans` 的参数逐个说清：

```python
Axis.spans(deltas, axis, base=0.0, include_base=True, role=None, name="")
```

| 参数 | 含义 | 说明 |
|---|---|---|
| `deltas` | **相邻两点的间距**（不是坐标） | `[6000, 6000]` 读作「每隔 6000 一段，共两段」 |
| `axis` | 空间方向，只能是 `"x"/"y"/"z"` | 不改数值，只声明归属（下文细说） |
| `base` | 起点坐标，默认 0 | `base=1000` → 整根轴从 1000 起算 |
| `include_base` | **起点本身算不算一个点** | `True` → n 个间距得 **n+1** 个点；`False` → n 个点 |
| `role` | 每个点的名字 | 长度必须等于点数，否则报错 |
| `name` | 显示名 | 只用于报错和 `repr` |

四种组合，对着看就懂：

```python
Axis.spans([6000, 6000], axis="x")                                  # 0, 6000, 12000    两跨 → 三个柱位
Axis.spans([4000, 3500], axis="z", include_base=False)              # 4000, 7500        两个层高 → 两个楼面标高
Axis.spans([3000, 3000], axis="x", base=1000)                       # 1000, 4000, 7000  从 1000 起算
Axis.spans([3000, 3000], axis="x", base=1000, include_base=False)   # 4000, 7000        从 1000 起算又不含 1000
```

> 判断口诀：**「地面算不算一个标高？」** 算 → `include_base=True`（柱位、跨度）；不算 → `False`（楼面、层）。

#### `axis=` 到底管什么

这是最容易糊过去的参数。它**不改变数值**，只声明「这串数属于哪个方向」，而这句话决定了三件事：

```python
X = Axis.points([0, 6000], axis="x")
Y = Axis.points([0, 3000], axis="y")

list((X * Y).points())   # [(0,0,0), (0,3000,0), (6000,0,0), (6000,3000,0)]
#                          ↑ x 落在第 1 列     ↑ y 落在第 2 列
list((Y * X).points())   # 交换相乘顺序：坐标完全一样，只是遍历顺序变了
```

1. **填哪一列**：`PointSet` 拼坐标时按轴名定位，不按书写顺序；
2. **能不能合**：`X + Y` 要求方向相同，`Axis("x") * Axis("x")` 直接报错（`PointSet 的轴方向重复：['x', 'x']`）；
3. **报错说人话**：`role_of` / `index_of` 的提示里会带上轴名。

#### `role=` 有什么用

给每个点起名字，之后按名字取坐标，替代 `Z[-1]`、`X[2]` 这类魔法下标：

```python
Z = Axis.spans([4000, 3500], axis="z", include_base=False, role=["一层楼面", "二层楼面"])
Z.role_of("二层楼面")     # 7500.0
Z.role_of("三层楼面")     # KeyError: 轴 'z' 中没有角色 '三层楼面'；已有角色：['一层楼面', '二层楼面']

Z[0:1].role               # ('一层楼面',)        子轴带走对应位置的 role
Z.mirror(0).role          # ('二层楼面', '一层楼面')   镜像后 role 顺序反转，名字跟着点走
(Z | Axis.points([0], axis="z")).role   # None    集合运算后 role 一律丢弃，避免错位
```

批量造标签的写法（A、B……X，A1、A2）见 §6.4。标签和点是一一对应的，数量必须等于**点数**：

```python
Axis.spans([6000, 6000], axis="x", role=["柱1", "柱2"])   # 3 个点只给 2 个名
# ValueError: role 长度 2 与点数 3 不一致
```

`with_role()` 换一套名字（比如同一根轴，按用途起两套标签）：

```python
X = Axis.points([0, 6000], axis="x", role=["A", "B"])
X.with_role(["首层", "二层"]).role     # ('首层', '二层')
X.role                               # ('A', 'B')  原轴不变
```

**建好之后还能补 role 吗？** 不能「原地补」——`Axis` 不可变，字段直接赋值会报错；只能造一根新轴再赋回同一个变量：

```python
X = Axis.points([0, 6000], axis="x")

X.role = ("A", "B")               # ✗ FrozenInstanceError: cannot assign to field 'role'
X = X.with_role(["A", "B"])       # ✓ 造新轴并赋回同一个变量名
P = X.with_role(["A", "B"])       # ✓ 也可以另存一个变量，原轴不受影响

# 等价的另一条路：重新造一根同坐标的轴（别忘 name 要自己带上）
Y = Axis.points(list(X), axis=X.axis, role=["甲", "乙"], name=X.name)

X.with_role(None)                 # 反向操作：把名字清空
```

**哪些操作会动 role、哪些不会**——这决定了你什么时候需要重贴一次：

| 操作 | role 的去向 | 要补吗 |
|---|---|---|
| `shift`（平移） | 原样保留 | 否 |
| 子轴 `Z[1:]`、`where(...)` | 保留对应位置的名字 | 否 |
| `mirror`（镜像） | 顺序自动反转（名字跟着点走） | 否，除非你要名字固定 |
| `A + B`（拼接） | 两边都有才保留，缺一边就变 `None` | 缺一边就要补 |
| `A \| B` / `&` / `-` | 一律变 `None`（防止错位） | 要名字就补 |
| 造轴时没写 `role` | 就是 `None` | 想要就补 |

所以最常需要"重新定义 role"的场景是**合并**：用 `|` 把两根轴并起来后 role 会清空，得再贴一次。

```python
Z = Axis.points([0, 3000, 6000], axis="x", role=["A", "B", "C"])
merged = Z | Axis.points([9000], axis="x")
list(merged), merged.role          # [0, 3000, 6000, 9000]  None   ← 名字没了
merged.with_role(["A", "B", "C", "D"]).role    # ('A', 'B', 'C', 'D')
```

而 `shift` 出来的轴**自带名字**，不用重贴：

```python
Z.shift(1000).role     # ('A', 'B', 'C')   平移后名字还在
```

#### 查询：轴上有哪些点、它们在哪儿

`X = Axis.points([0, 3000, 6000], axis="x")` 为例，全部读取方式（**这一节全是只读查询，不新建轴**，只有 `X[a:b]` / `where` 会顺带造一个子轴）：

| 写法 | 返回 | 干什么 | 本例的结果 |
|---|---|---|---|
| `len(X)` | int | 点有几个 | `3` |
| `list(X)` / `for x in X` | 迭代 mm 浮点 | 挨个拿出坐标 | `[0.0, 3000.0, 6000.0]` |
| `X[i]` / `X[-1]` | float | 按下标取一个点 | `X[-1]` → `6000.0` |
| `X[a:b]` / `X[[0, 2]]` | **Axis** | 取子轴（还是轴，不是 list） | `X[0:2]` → `Axis(x, [0, 3000], n=2)` |
| `X.cells` | 元组 | 相邻点对（n-1 个） | `((0.0, 3000.0), (3000.0, 6000.0))` |
| `X.idx` | `range` | **下标本身**：0, 1, 2 | `range(0, 3)` |
| `X.index_of(值)` | int | **反查**：这个坐标是第几个点 | `X.index_of(3000)` → `1` |
| `X.role_of("名")` | float | 按名字取坐标 | 见上一节 |
| `X.where(fn)` | Axis | 按条件过滤，返回子轴 | `X.where(lambda i, v: v > 0)` → `[3000, 6000]` |
| `X.with_role([...])` | Axis | 换一套名字 | 见上一节 |
| `X.um_at(i)` | int | 第 i 个点的 μm 整数（库内部用，日常用不到） | `3000000` |

**`idx` 和 `index_of` 是互为反向的两件事**，都跟「第几个」有关：

```python
X.idx                  # range(0, 3)  ← 就是 0,1,2 这三个下标本身
for i in X.idx:
    print(i, X[i])     # 0 0.0 / 1 3000.0 / 2 6000.0

X.index_of(3000)       # 1             ← 反过来问：3000 是第几号？
X[X.index_of(3000)]    # 3000.0        ← 查到的下标再取回来，还是原值（自反）
X.index_of(5000)       # ValueError: 5000 mm 不在轴 'x' 上  ← 不返回"最近的"
```

用在哪：你手上有一张「柱编号 / 外部数据表 → 坐标」的对应表时，用 `index_of` 把坐标换成下标，才能去索引别的列表；或者用它校验「这个坐标确实在我这根轴上」。`idx` 则是你想按下标遍历时的写法，等价于 `range(len(X))`。

#### 变换与集合运算：一律返回新轴

```python
X = Axis.points([0, 3000, 6000], axis="x")

X.shift(1000)     # → 新轴 [1000, 4000, 7000]      X 不变
X.mirror(6000)    # → 新轴 [6000, 9000, 12000]      X 不变
```

**原轴一个字节都不变。** `Axis` 是不可变的（frozen dataclass）：

```python
X2 = X.shift(1000)
list(X), list(X2)    # [0.0, 3000.0, 6000.0]   [1000.0, 4000.0, 7000.0]
X is X2              # False —— 两个不同的对象
X.um = (1, 2)        # FrozenInstanceError —— 连字段都不给改
```

好处：轴可以多处共享、当字典键、放心传进函数，不存在「谁把它偷偷改了」。反过来要注意：`X.shift(1000)` **不赋值就等于什么都没做**。

集合运算四个运算符：

```python
A = Axis.points([0, 3000], axis="x")
B = Axis.points([6000, 9000], axis="x")
list(A + B)          # [0, 3000, 6000, 9000]   拼接：A 的尾巴必须小于 B 的头

A2 = Axis.points([0, 3000, 6000], axis="x")
B2 = Axis.points([6000, 9000], axis="x")
A2 + B2              # ValueError：拼接后的轴不再严格递增…（提示改用 |）
list(A2 | B2)        # [0, 3000, 6000, 9000]   并集：去重 + 排序
list(A2 & B2)        # [6000]                  交集
list(A2 - B2)        # [0, 3000]               差集
```

| 运算 | 语义 | 要求 | `role` 怎么处理 |
|---|---|---|---|
| `A + B` | 拼接（接一段） | A 的最大值 **<** B 的最小值 | 两边都有才保留 |
| `A \| B` | 并集 | 同方向 | 丢弃 |
| `A & B` | 交集 | 同方向 | 丢弃 |
| `A - B` | 差集 | 同方向 | 丢弃 |

一句话选：**想「接一段」用 `+`，想「合并去重」用 `|`。** 而 `X * Y` 不是集合运算，是张成点阵（见 §2.4）。

### 2.4 PointSet：点阵

**`Axis * Axis` 出来的就是 `PointSet`。** `*` 在几何对象上有三种形态：

| 写法 | 结果 | 例 |
|---|---|---|
| `Axis * Axis` | 2 维 `PointSet` | `X * Y` → shape `(3, 2)` |
| `PointSet * Axis` | 在**后面**加一维 | `(X * Y) * Z` → `(3, 2, 3)` |
| `Axis * PointSet` | 在**前面**加一维 | `X * (Y * Z)` → `(3, 2, 3)` |

所以 `X * Y * Z` 就是左结合地连续相乘。同一方向不能乘两次（`(X * Y) * (X * Y)` → `ValueError: PointSet 的轴方向重复`）。

```python
P = X * Y            # 2 维，shape (3, 2)，count 6
P = X * Y * Z        # 3 维，18 个点
P.shape, P.count(), len(P)
list(P.points())     # [(0.0, 0.0, 0.0), ...]  元素永远是 (x, y, z)，与轴的书写顺序无关
```

#### 内部结构：axes / keep / offset 三件套

```python
@dataclass(frozen=True)
class PointSet:
    axes: tuple[Axis, ...]                      # 每一维的坐标表
    keep: tuple[int, ...] | None = None         # 保留哪些点（线性索引），None = 全选
    offset: tuple[int, int, int] = (0, 0, 0)    # 整体平移，μm
```

一个点的坐标 = 各维取值 + offset。「打洞」**不动轴、也不重排轴**，只记 `keep`：

```python
P = X * Y * Z                         # axes 三根轴，keep=None（全选）→ 3×2×3 = 18 个点
P.shape, P.keep                       # (3, 2, 3)  None

H = P.mask(lambda p: p[0] > 0)        # 轴原封不动，keep 里只剩 12 个索引
H.count(), H.axes[0] is P.axes[0]     # 12  True —— 轴是共享的，只有 keep 变了

P.shift(z=1000).offset                # (0, 0, 1000000) —— 平移只改 offset，轴也不动
```

这就是为什么切片、打洞、平移都很便宜：**轴只读共享，变化全落在 `keep` 和 `offset` 这两个小字段上**。

**下面每一个操作都返回新点阵，`P` 本身不变**（`PointSet` 同样是 frozen dataclass）：

```python
P.at(z=1)                     # → 新点阵：固定索引（int = 索引）
P.at(z=[4000])                # → 新点阵：按坐标值挑（list = 坐标值）
P[:, 1, :]                    # → 新点阵：第 2 维取索引 1
P[[0, 2]]                     # → 新点阵：按索引列表挑
P.mask(lambda p: p[0] > 0)                    # → 新点阵：按坐标过滤
P.where(lambda idx, p: (idx[0] + idx[1]) % 2 == 0)   # → 新点阵：按 (索引, 坐标) 过滤

P.shift(z=4000)                  # → 新点阵：平移（只改 offset）
P.mirror("x", about=0)           # → 新点阵：关于 x=0 镜像
P | P2, P & P2, P - P2           # → 新点阵：集合运算（要求维度、方向、offset 一致）
PointSet.of([(0, 0, 0), (6000, 0, 0)])   # → 新点阵：一堆散点，退化成显式点表
```

反例（会踩的坑）：`P.mask(...)` 不赋值等于什么都没做。

```python
P.mask(lambda p: p[0] > 0)        # 白写一行
H = P.mask(lambda p: p[0] > 0)    # 正确写法
```

### 2.5 Node 与 Member：真正被存下来的两个对象

```python
@dataclass
class Node:
    id: int                                   # 节点号，模型内唯一
    xyz: tuple[int, int, int]                 # μm 整数
    sources: set[int] = set()                 # 谁引用我（构件 id 的集合）
    attrs: dict = {}                          # 支座、主从、附加质量…
    # 另有只读属性 point → (mm, mm, mm)

@dataclass
class Member:
    id: int                                   # 构件号
    i: int                                    # 起始节点号
    j: int                                    # 终止节点号
    group: str | None                         # 属于哪个组
    attrs: dict = {}                          # 截面、图层、只受拉…
    ends: dict = {}                           # {"i": 端部条件, "j": 端部条件}
    origin: tuple | None = None               # 打断前身份 (组名, 序号)
```

四个「不显眼但很关键」的字段：

| 字段 | 谁在用 | 为什么存在 |
|---|---|---|
| `Node.sources` | 报告的「端点」「孤立断点」、白名单打断判断 | **反向引用**：不遍历全模型就知道谁连着这个节点 |
| `Node.attrs` | 支座 | 节点上的自由属性，不参与任何几何判断 |
| `Member.origin` | `merge_orphans` / `merge` / 报告「切点来源」 | 识别「这几段本来是同一根」的**唯一**依据 |
| `Member.ends` | 导出 FEA、报告「端部未指定」 | 库不解释「刚接」是什么意思，只原样搬运 |

两者都是**可变**对象（与 `Axis` 相反）：

```python
mb.attrs["section"] = "H500"     # 立刻生效（Group.set() 干的就是这件事）
m.nodes[0].attrs["支座"] = "固接"
```

### 2.6 Model 与 Group：管理结构

`Model` 里没有一个列表，全是字典加两个索引：

```python
class Model:
    _nodes:   dict[int, Node]        # 节点号 → 节点
    _node_at: dict[tuple, int]       # 坐标 → 节点号                       ← 节点去重靠它
    _members: dict[int, Member]      # 构件号 → 构件
    _poskey:  dict[tuple, int]       # (组, 小端节点, 大端节点) → 构件号     ← 防重复靠它
    _groups:  dict[str, Group]       # 组名 → 组
    _virtual: dict[int, str]         # 显式节点的来源组（as_group）
    _next_node, _next_member         # 编号计数器，只增不减
```

#### 看一眼真实的对象

建一个最小模型：两根柱、一根梁，梁的两端撞在柱身上，所以两根柱各被切成两段。

```python
m = Model()
COL  = m.define("COL",  split="all",  attrs={"layer": "COL"})
BEAM = m.define("BEAM", split="none", attrs={"layer": "BEAM"})

COL.add((0, 0, 0), (0, 0, 4000))
COL.add((6000, 0, 0), (6000, 0, 4000))
BEAM.add((0, 0, 2000), (6000, 0, 2000))

len(m.nodes), len(m.members)          # (6, 5)   6 个节点、5 根构件
```

`m.nodes` / `m.members` 就是内部字典本身（不是副本），直接打出来能看见全貌：

```python
print(m.nodes)
# {0: Node(id=0, xyz=(0, 0, 0),             sources={3},        attrs={}),
#  1: Node(id=1, xyz=(0, 0, 4000000),       sources={4},        attrs={}),
#  2: Node(id=2, xyz=(6000000, 0, 0),       sources={5},        attrs={}),
#  3: Node(id=3, xyz=(6000000, 0, 4000000), sources={6},        attrs={}),
#  4: Node(id=4, xyz=(0, 0, 2000000),       sources={2, 3, 4},  attrs={}),
#  5: Node(id=5, xyz=(6000000, 0, 2000000), sources={2, 5, 6},  attrs={})}

print(m.members)
# {2: Member(id=2, i=4, j=5, group='BEAM', attrs={'layer': 'BEAM'}, ends={}, origin=('BEAM', 1)),
#  3: Member(id=3, i=0, j=4, group='COL',  attrs={'layer': 'COL'},
#            ends={'i': None, 'j': None}, origin=('COL', 1)),
#  4: Member(id=4, i=4, j=1, group='COL',  ...  origin=('COL', 1)),
#  5: Member(id=5, i=2, j=5, group='COL',  ...  origin=('COL', 2)),
#  6: Member(id=6, i=5, j=3, group='COL',  ...  origin=('COL', 2))}
```

三个立刻能读出来的事实：

1. **构件号从 2 开始，不是从 0**。原先两根柱是 0、1 号，被梁打断时「删旧建新」，四段新构件拿到 3~6 号；0 和 1 永远空着。**编号只增不复用**，看日志不会串。
2. **节点 4 的 `sources` 是 `{2, 3, 4}`**：梁 + 上面那段柱 + 下面那段柱，三根构件共用这一个节点。报告里的「端点」「孤立断点」全靠这个反向引用直接数，不用遍历全模型。
3. **`ends={'i': None, 'j': None}`**：柱没声明端部条件，被打断后接缝也填 `None`。报告里「端部未指定」数的就是这些 `None`——库不猜。

内部两个索引长这样（调试时很有用）：

```python
m._node_at   # {(0,0,0): 0, (0,0,4000000): 1, (6000000,0,0): 2,
             #  (6000000,0,4000000): 3, (0,0,2000000): 4, (6000000,0,2000000): 5}
m._poskey    # {('BEAM', 4, 5): 2, ('COL', 0, 4): 3, ('COL', 1, 4): 4,
             #  ('COL', 2, 5): 5, ('COL', 3, 5): 6}
```

同坐标不会重复建节点（`_node_at` 的作用）。单独验一次：

```python
m2 = Model()
G = m2.define("G")

G.add((0, 0, 0), (0, 0, 4000))
G.add((0, 0, 4000), (3000, 0, 4000))   # 起点正好是上一根的终点

len(m2.nodes)      # 3，不是 4 —— 第二个起点复用了已有节点
```

#### Group 到底是什么：一类构件的标签 + 规则

一句话：**`m.define()` 不产生任何构件，它定义的是一「类」构件的名字和规矩**。

```python
mm = Model()                   # 另起一个干净的模型，免得和上面混淆
G1 = mm.define("G1")           # 只登记一个组
len(mm.members)                # 0      ← 一个构件都还没有

mb = G1.add((0, 0, 0), (0, 0, 1000))
mb.group                       # 'G1'   ← 构件身上存的是**字符串**，不是 Group 对象
mm.group(mb.group) is G1       # True   ← 按名字把组对象取回来

mm.remove(G1.all())            # 构件删光
G1.count(), mm.group("G1") is G1    # (0, True)   ← 组还在
```

| 由此得到 | 说明 |
|---|---|
| 组可以一直是空的 | 「先定义组、后按条件加构件」是常态写法 |
| 删光构件，组不消失 | 组的生命周期跟着 `Model`，不跟着构件 |
| 组名参与重复判定 | `_poskey` 的键里含组名，所以**不同组在同一位置各放一根是被允许的** |
| 组名写错是静默的 | `m.by(group="COL1")` 返回空列表，不报错——组名要自己核 |

组对象里的全部内容，`vars()` 一次看干净：

```python
vars(COL)
# {'name': 'COL', 'split': 'all', 'attrs': {'layer': 'COL'}, 'keys': None,
#  'ends': {}, 'split_ends': None, '_seq': 2}
```

| 字段 | 含义 | 谁在用 |
|---|---|---|
| `name` | 组名（构件上的 `group` 存的就是这个字符串） | 查、筛选、报告分组 |
| `split` / `split_ends` | 打断策略 | 每次 `add` 时判断 |
| `attrs` / `ends` | 新构件的默认属性 / 默认端部条件 | `add` 时拷进每个新构件 |
| `keys` | 属性白名单（`None` = 不检查） | 防止属性名拼错 |
| `_seq` | 自增序号，`add` 一次加一 | 构成 `origin = (组名, 序号)` |

`_seq` 和 `origin` 的对应关系直接看得见：

```python
[(mb.id, mb.origin) for mb in COL.all()]
# [(3, ('COL', 1)), (4, ('COL', 1)), (5, ('COL', 2)), (6, ('COL', 2))]
#   ↑ 两次 COL.add 各产生一个序号；被打断的两段共享同一个 origin
```

`_poskey` 的键是 **`(组名, 两个节点号排好序)`**，所以 `A→B` 与 `B→A` 是同一个键。同一组里反向再画一遍会被拦下：

```python
COL.add((0, 0, 2000), (0, 0, 0))     # 与已有段 (0,0,0)→(0,0,2000) 反向重合
# ConflictError: 构件已存在：组='COL' (0.0, 0.0, 2000.0) → (0.0, 0.0, 0.0)
```

> 顺带一个可观察的副作用：失败的 `add` 也会让 `_seq` 加一，所以 `origin` 里的序号**可能不连续**（跳号不代表出过错，只能说明有人尝试过）。

`grp.all()` **不是查表**，是每次扫一遍全模型筛出来的：

```python
grp.all()      # 等价于 [mb for mb in m.members.values() if mb.group == grp.name]
```

所以大模型里反复调它是 O(构件数)。循环里要用就先存一份：

```python
segs = COL.all()             # 一次
for mb in segs:              # 不要再 COL.all()
    ...
```

#### 查：`m.group()` / `m.by()` / `grp.where()`

三个入口，粒度从粗到细：

```python
m.group("COL")                       # 按组名取回组对象（就是 COL 本身：m.group("COL") is COL → True）
m.by(group="COL")                    # 按组筛构件
# [Member 3, Member 4, Member 5, Member 6]

m.by(layer="BEAM")                   # 按任意 attrs 键筛
# [Member 2]                         （attrs 里 layer == "BEAM" 的那根）

m.by(origin=("COL", 1))              # 按「打断前是哪一根」筛
# [Member 3, Member 4]               ← 同 origin 的两段，一根柱的上下两截

COL.where(lambda mb: m.nodes[mb.i].point[2] == 0)    # 组内再筛：柱脚那两段
# [Member 3, Member 5]
```

`m.by()` 接受三类键：`group=`（组名）、`origin=`（原身份二元组）、其余一律当 `attrs` 的键。返回的是**新列表**，但里面装的就是模型里那些 `Member` 对象。

重复定义同名组会直接报错，不会静默覆盖：

```python
m.define("COL")
# ValueError: 组 'COL' 已定义
```

#### 改：`set` / `set_ends` 是原位修改

```python
seg = COL.all()[0]

COL.set(section="H400")            # 给组内所有构件补一个属性
seg.attrs                          # {'layer': 'COL', 'section': 'H400'}
COL.all()[0] is seg                # True —— 同一个对象，没有新建

COL.set_ends(i="刚接")             # 只改 i 端
seg.ends                           # {'i': '刚接', 'j': None}
```

这也解释了为什么 `g.all()` 拿到的东西**不能随便改**：它给你的就是模型里那个对象，改了模型就变了。想批量改，用 `set()` / `set_ends()` 表达意图，比手写循环清楚。

#### 删与合并

删不会自动合并——这是刻意的，自动合并可能悄悄把两根铰接杆变成一根连续杆：

```python
COL.count()                 # 4
m.remove(BEAM.all())        # 删掉那根梁
COL.count()                 # 4    ← 还是 4 段，断点留着
```

断点留着不是废料，它记录了「这里本来有东西」。确定要合回去时再显式调用：

```python
m.merge_orphans()           # 合并「同 origin + 相接 + 该节点没别的构件」的段
# 2                         ← 合并了 2 处
COL.count()                 # 2    ← 两根柱各恢复成一整根
[mb.id for mb in COL.all()] # [7, 8]   ← 合并同样是「删旧建新」，id 继续只增
```

只想合并指定的两根，用 `m.merge(a, b, attrs="a")`：`attrs` 冲突时用 `'a'` 还是 `'b'` 的那一份，必须明说。

#### 哪些操作会改模型

`Model` 建好之后，只有下面这些动作会改动它的内部状态（其余都是只读）：

| 操作 | 干了什么 | 返回 |
|---|---|---|
| `m.define(name, ...)` | 登记一个组 | `Group` |
| `m.node(xyz, ...)` | 建节点（可能**立刻切断**已有构件） | `Node` |
| `g.add(...)` / `add_pairs` / `add_chain` / `add_X` / `add_zigzag` | 建节点 + 建构件 + **切断别人的构件** | `Member` 或 `list[Member]` |
| `g.set(**attrs)` / `g.set_ends(i=, j=)` | **原位改**已有构件的 `attrs` / `ends` | 改动的根数 |
| `m.remove(...)` / `g.remove()` / `g.clear()` | 删构件（不自动合并回来） | 删掉的根数 |
| `m.merge(a, b)` / `m.merge_orphans()` | 合并构件的分段 | `Member` / 合并的根数 |

只读的操作：`m.report()`（返回字符串）、`m.by(...)` / `g.all()` / `g.where()`（返回**新列表**，元素还是原来那些 `Member`）、`g.count()`、`m.nodes` / `m.members`（返回内部字典本身——能读，但别去改）。`m.export_dxf()` / `m.export_fea()` 只写文件，不动模型。

`Group.add()` 的返回值也要记牢：没被打断给一个 `Member`，被打断给一个 `list[Member]`。

```python
mb  = COL.add(p, q)     # 1 根 → Member
mbs = COL.add(p, q)     # 被旧节点切成 3 段 → list[Member]，长度 3
```

---

## 3. 建模流程

```
① 定坐标    Axis.spans / Axis.points        哪几条轴线、哪些标高
      │
      ├─（可选）张点阵   X * Y * Z → PointSet   把 2~3 根轴变成空间里的点
      ↓
② 定组      Model.define(name, split, attrs, ends, split_ends)   一类构件的规矩
③ 放杆      Group.add / add_chain / add_X / add_zigzag / add_pairs
④ 体检      Model.report()                  每加完一批就看，不要只看一次
⑤ 出口      export_dxf / export_fea / strutkit.tools.dxf2svg
```

**点阵（`PointSet`）不是独立的一步，它是 ① 和 ③ 之间的中间产物**，作用有三个：

1. **批量投料**：`add_chain` / `add_X` / `add_zigzag` / `add_pairs` 的入参都是点阵，一个点阵一次生成一批构件；而 `add()` 只吃两个点。
2. **先变形再放杆**：`mask` / `at` / `shift` / `mirror` / 集合运算都在「产生构件之前」生效，于是「只在外侧布置」「中间挖洞」「双排对称」这类规则写在点阵上，而不是写在循环里的 `if` 里。
3. **同一批位置复用给多个组**：柱、支撑、支座节点往往落在同一批点上，张一次点阵，三个组各取所需。

**它不进模型。** 点阵是脚本里的中间值（草稿纸），模型里只有 `Node`（有编号、有 `sources`）和 `Member`。同一位置在点阵里出现多少次，进模型时都会被 `_node_at` 合并成一个节点。

也可以完全不用点阵——`for` 循环 + `Group.add(p, q)` 拿标量坐标逐根放，两者等价（下面两段沿用 §4 的 `X` / `Y` / `Z` / `H` 与 `COL` / `BEAM`）：

```python
for x in X:                          # 写法 A：标量循环
    for y in Y:
        COL.add((x, y, 0), (x, y, H))

for p in X * Y:                      # 写法 B：点阵
    COL.add((p[0], p[1], 0), (p[0], p[1], H))
```

两种写法都是 6 根柱、12 个节点。**规则重复（矩阵式布置）就用点阵，几何不规则就用循环**——点阵真正的收益在维数一多就显现：

```python
for z in Z:                          # 三重循环：2 层 × 2 条 y 线 × 2 跨 = 8 根
    for y in Y:
        for i in range(len(X) - 1):
            BEAM.add((X[i], y, z), (X[i + 1], y, z))

for z in Z:                          # 点阵版：同样 8 根
    BEAM.add_chain((X * Y).shift(z=z), along="x")
```

每一步都有可验证的产出：

| 步 | 要验证什么 | 怎么验 |
|---|---|---|
| ① | 坐标是不是你要的那几个；点阵张出来的点数对不对 | `print(list(X))`、`print(P.shape, P.count())` |
| ② | 能不能被打断、端部条件填没填 | `print(COL.split, COL.ends)` |
| ③ | 构件数、打断次数对不对 | `report()` 首段的分组统计 |
| ④ | `INV: OK` / 连通分量 / 端点 / 短段 | 逐行读，见 §4 Step 7 |
| ⑤ | 图对不对、表格对不对 | 打开 DXF、看 CSV 前两行 |

---

## 4. 一步一步：一栋两层小框架

贯穿示例：X 向两跨（0 / 6000 / 12000）、Y 向一跨（0 / 6000）、两层（±0 / 4000 / 7500）。构件四类：柱、X 向主梁、Y 向主梁、次梁。

> 前置：先按 `../README.md`「安装」二选一——`pip install -e .`（推荐），或把**仓库根**加进 `sys.path`。搞定后下面只写 `from strutkit import ...`。

### Step 1 造轴

```python
from strutkit import Axis, Model

X = Axis.spans([6000, 6000], axis="x")      # 0 / 6000 / 12000
Y = Axis.spans([6000], axis="y")            # 0 / 6000
Z = Axis.spans([4000, 3500], axis="z")      # 0 / 4000 / 7500（含 ±0）

print(list(X), list(Y), list(Z))
# [0.0, 6000.0, 12000.0] [0.0, 6000.0] [0.0, 4000.0, 7500.0]
```

### Step 2 定义组

```python
m = Model()

COL = m.define("COL", split="all",
               attrs={"layer": "COL", "section": "H400"},
               ends={"i": "刚接", "j": "刚接"}, split_ends="刚接")

MBX = m.define("MBX", split=["SEC"],                 # 只允许次梁切我
               attrs={"layer": "MBX", "section": "HN300"},
               ends={"i": "刚接", "j": "刚接"}, split_ends="刚接")

MBY = m.define("MBY", split="none",                  # 不允许被任何东西切
               attrs={"layer": "MBY", "section": "HN300"},
               ends={"i": "刚接", "j": "刚接"}, split_ends="刚接")

SEC = m.define("SEC", split="none",
               attrs={"layer": "SEC", "section": "HN200"},
               ends={"i": "铰接", "j": "铰接"})
```

一个组一次说清三件事：**属性**（`attrs`，会原样带到 DXF 图层与 FEA 表格）、**端部条件**（`ends`）、**打断策略**（`split` / `split_ends`）。

### Step 3 放柱

```python
for p in X * Y:                              # 3 × 2 = 6 个柱位，点阵直接扫
    COL.add((p[0], p[1], 0), (p[0], p[1], Z[-1]))

print(m.report())
```

```
Nodes: 12    Members: 6
  COL            6

INV: OK
内部有节点但未打断：0
端点（度=1 且无节点属性，可能漏连或未标支座）：12
...

连通分量：6
```

**报告第一次有用**：6 根柱、12 个端点、6 个连通分量——因为柱子之间还没有任何连接。这不算错，只是「模型还没建完」。

### Step 4 加主梁

```python
PXY = X * Y
for z in Z[1:]:                                # 跳过 ±0
    MBX.add_chain(PXY.shift(z=z), along="x")    # 沿 x 连相邻点
    MBY.add_chain(PXY.shift(z=z), along="y")
```

```
Nodes: 18    Members: 26
  COL           12（6 根被切成多段）
  MBX            8
  MBY            6

INV: OK
端点：6
连通分量：1
```

三件事同时发生：

1. 柱被梁端**自动切成 2 段**（6 根 → 12 段），因为 `COL` 的 `split="all"`；
2. `add_chain` 按「其余维」分桶，一个点阵一次连出所有平行梁，不用写三重循环；
3. 连通分量 6 → 1：梁把柱子连成了一体。

`origin` 记下了「这 2 段本来是同一根柱」，报告里写作 `COL origin=('COL', 1): 1 根 → 2 段`。

### Step 5 加次梁（白名单生效）

```python
for z in Z[1:]:
    for i in range(len(X) - 1):
        xc = (X[i] + X[i + 1]) / 2              # 每跨中点 3000 / 9000
        SEC.add((xc, Y[0], z), (xc, Y[1], z))
```

```
Nodes: 26    Members: 38
  COL           12（6 根被切成多段）
  MBX           16（8 根被切成多段）
  MBY            6
  SEC            4
```

`MBX` 从 8 段变 16 段：次梁两端落在 X 向主梁身上，而 `MBX` 的 `split=["SEC"]` 允许被次梁切。`MBY` 一根没被切——次梁是从它上方跨过去的（`split="none"`）。主次关系只有这一个方向，不能反过来。

### Step 6 加支座

```python
for p in X * Y:
    m.node((p[0], p[1], 0), attrs={"支座": "固接"})
```

```
端点（度=1 且无节点属性）：0
```

节点可以单独存在、单独带属性。支座就是「一个节点 + 一个 attrs」：库不解释「固接」的含义，只负责让这条信息活到出口。

注意 `m.node()` **默认不打断任何构件**（不带 `as_group`）。要让显式节点也参与打断，写 `m.node(p, as_group="COL")`——意思是「这个节点等价于 COL 组构件产生的节点」。

### Step 7 读报告

完整报告（上例的真实输出）：

```
Nodes: 26    Members: 38
  COL           12（6 根被切成多段）
  MBX           16（8 根被切成多段）
  MBY            6
  SEC            4

INV: OK

内部有节点但未打断：0

端点（度=1 且无节点属性）：0

端部未指定：0

短段（< 150 mm）：0

最低标高 z=±0.000 处无水平构件：OK

连通分量：1

孤立断点：0

量化近似点：0

切点来源（被打断的构件）：
  COL origin=('COL', 1): 1 根 → 2 段
  COL origin=('COL', 3): 1 根 → 2 段
  ...（共 6 行 COL、4 行 MBX）
  MBX origin=('MBX', 1): 1 根 → 2 段
```

逐行读法：

| 行 | 含义 | 出问题时说明什么 |
|---|---|---|
| `Nodes / Members` + 分组 | 规模与分组统计 | 数量对不上 → 漏放或多放 |
| `INV: OK` | 没有「内部有节点却没打断」的杆 | 违反 = 断链，力学模型错 |
| 内部有节点但未打断 | 该杆 `split="none"`，本可以连接却没连 | 白名单写错；或故意的大 X（正常） |
| 端点（度=1 且无属性） | 只连一根杆、又没标支座的节点 | 漏连，或漏标支座 |
| 端部未指定 | `ends` 里空着的端 | 铰接 / 刚接还没填 |
| 短段（< 150mm） | 打断切出来的碎段 | 容差附近有两个近重合节点 |
| 最低标高处有水平构件 | ±0 上的水平杆 | 把梁放到地面了 |
| 连通分量 | 节点—构件图的连通块数 | > 1 = 结构分家 |
| 孤立断点 | 打断后没别的构件连着的段 | 可用 `merge_orphans` 合并 |
| 量化近似点 | 距离 < 1 个步长却没合并的点 | 两个本该重合的点没重合 |
| 切点来源 | 每根被切构件切成几段 | 切多了 / 切少了 |

`report(short_mm=...)` 调短段阈值，`report(show_cuts=False)` 关掉最后一节。

### Step 8 导出

```python
m.export_dxf("out/frame.dxf", layers={"COL": 2, "MBX": 4, "MBY": 5, "SEC": 3})
m.export_fea("out/nodes.csv", "out/members.csv")
```

**DXF**：一根构件一条 LINE，图层取 `attrs["layer"]`，颜色按 `layers` 参数。装了 ezdxf 出标准 R2000，没装则回退到手写 R12（不引第三方依赖）。

**FEA** 两张表：

```
nodes.csv     id, x_mm, y_mm, z_mm, attrs
members.csv   id, node_i, node_j, group, length_mm, attrs, ends_i, ends_j, origin
```

真实前两行：

```csv
id,x_mm,y_mm,z_mm,attrs
0,0.000000,0.000000,0.000000,"{""支座"": ""固接""}"

id,node_i,node_j,group,length_mm,attrs,ends_i,ends_j,origin
7,0,12,COL,4000.000000,"{""layer"": ""COL"", ""section"": ""H400""}","""刚接""","""刚接""","[""COL"", 1]"
```

CSV 用 `utf-8-sig` 编码，Excel 直接双击不乱码。

**看图**：

```bash
python -m strutkit.tools.dxf2svg out/frame.dxf                        # 出 out/frame_iso.png
python -m strutkit.tools.dxf2svg out/frame.dxf --views front,side,top,iso
python -m strutkit.tools.dxf2svg out/frame.dxf --only-y 0             # 只看 y=0 这一片

（装了包就在任何目录都能跑；没装就在**仓库根**执行。）
```

---

## 5. 不同的用法（菜谱）

> 本节沿用 §4 的 `X` / `Y` / `Z`。除 5.2 / 5.3 / 5.4 只在点阵上操作外，其余片段都把 `m` 当作**新建的空模型**（5.5 里的 `BEAM` / `BR` / `TIE` / `COL` 等也各自新建）；
> 要接到 §4 的模型上，请避开已定义的组名（`COL` / `MBX` / `MBY` / `SEC`）。

### 5.1 坐标从哪来：三种写法

```python
X = Axis.spans([7000, 7000, 6000], axis="x")      # ① 间距累加：规则结构
X = Axis.points([0, 2640, 3706, 6346], axis="x")  # ② 直接给值：不规则 / 从别处读来
X = Axis.step(1500, 9, axis="x")                  # ③ 等距：0, 1500, … 12000
```

### 5.2 复制：shift 与 mirror

```python
plane = X * Z                     # y = 0 的立面点阵
back  = plane.shift(y=2200)       # 往前挪 2200，得到第二排
X.mirror(12000)                   # 关于 x=12000 镜像：0 / 6000 / 12000 → 12000 / 18000 / 24000
```

`shift` 只改 `offset`，不动轴：同一个点阵可以多次平移复用，不会互相污染。

### 5.3 双排配对：add_pairs

两个**形状完全一致**的点阵，逐点连成杆：

```python
left  = X * Z                    # shape (3, 3)：3 条 x 线 × 3 个标高
right = left.shift(y=10000)      # 形状必须相同
TIE.add_pairs(left, right)       # 第 i 个点连第 i 个点，共 9 根
```

整批是原子的：任何一根与已有构件重合，整批拒绝，不会留下半批。

### 5.4 从点阵里挑点

「只有外圈有支撑」「中间留洞」这类需求，不需要写 if 循环：

```python
P = X * Y * Z                                   # shape (3, 2, 3)

P.at(z=[0, 4000])                               # 只取这两个标高（list = 坐标值）
P[:, 1, :]                                      # Y 维取索引 1
P.mask(lambda p: p[0] in (X[0], X[-1]))         # 只要最外两排
P.where(lambda idx, p: (idx[0] + idx[1]) % 2 == 0)   # 棋盘格

hole = Axis.points([6000], axis="x") * Y * Axis.points([4000], axis="z")
P - hole                                        # 挖掉一格：18 → 16
P - PointSet.of([(12000, 6000, 7500)])          # 也能直接减散点
```

### 5.5 从点阵到构件：五个放法 + 十个招式

#### 五个放法，各自的输入长什么样

| 方法 | 吃什么 | 产出 | 典型用途 |
|---|---|---|---|
| `g.add(p, q)` | 两个点（标量坐标） | 1 根 | 不规则、要逐根判断 |
| `g.add_chain(P, along=)` | 2 或 3 维点阵 | 沿某方向的**相邻点**连成杆 | 梁、柱、弦杆 |
| `g.add_X(P)` | **2 维**点阵 | 每个矩形格两根对角线 | 交叉支撑 |
| `g.add_zigzag(P, along=)` | **2 维**点阵 | 每格一根、方向交替 | 之字撑 |
| `g.add_pairs(P1, P2)` | 两个**形状相同**的点阵 | 逐点对拉 | 双排之间的横撑 |

下面十个招式都是同一个套路：**张点阵 → 变形（shift / mask / 切片）→ 一个方法放一批**。

#### 招式 1：每层沿 X 连梁（最常用的一行）

```python
for z in Z[1:]:                                   # 跳过 ±0
    BEAM.add_chain((X * Y).shift(z=z), along="x")     # 8 根
```

`(X * Y)` 是一个平面点阵（z=0），`shift(z=z)` 把它整体抬到楼层标高——**轴不动，只改 offset**，所以同一个点阵可以反复抬、反复用。

#### 招式 2：同一批点，换个 `along` 就连另一个方向

```python
for z in Z[1:]:
    BEAM.add_chain((X * Y).shift(z=z), along="y")     # 6 根
```

点阵完全一样，`along="x"` 连出 8 根 X 向梁，`along="y"` 连出 6 根 Y 向梁。

#### 招式 3：三维点阵竖向连成柱

```python
COL.add_chain(X * Y * Z, along="z")           # 12 根：6 个柱位 × 每层一段
```

`add_chain` 连的是**相邻两点**，所以给出来的是「按楼层分段」的柱，不是一根通长柱。想要通长再由梁去切，写 `COL.add((x, y, 0), (x, y, H))`。

#### 招式 4：立面点阵 → 之字 / 大 X，再 shift 到任意一排

```python
BR.add_zigzag((X * Z).shift(y=2200), along="x")   # 4 根之字
BR.add_X(X * Z)                                   # 8 根（每格两根对角线）
```

`X * Z` 是**没有 Y 轴**的立面点阵（全部落在 y=0），`shift(y=2200)` 就把它整片挪到 y=2200 那个立面上——不用重新张一次点阵。

#### 招式 5：双排对拉（add_pairs）

```python
left = X * Z
TIE.add_pairs(left, left.shift(y=2200))           # 9 根
```

两个点阵形状必须一致（这里都是 `(3, 3)`），然后逐点配对：第 1 个点连第 1 个点、第 2 个连第 2 个……

#### 招式 6：只在外圈布置

```python
Y3 = Axis.spans([6000, 6000], axis="y")           # 0 / 6000 / 12000（要 3 条线才有里外）
ring = (X * Y3).mask(lambda p: p[0] in (X[0], X[-1]) or p[1] in (Y3[0], Y3[-1]))
ring.count()                                       # 8（3×3 = 9 个点，挖掉正中一个）

for p in ring:
    COL.add((p[0], p[1], 0), (p[0], p[1], 4000))
```

#### 招式 7：只在某一跨 / 隔跨布置

```python
XL = Axis.spans([6000] * 4, axis="x")      # 0 / 6000 / 12000 / 18000 / 24000

BR.add_X(XL[0:2] * Z)                      # 4 根：只在第一跨（0–6000）
BR.add_X(XL[::2] * Z)                      # 8 根：格宽变成两跨（0–12000、12000–24000）
```

`XL[::2]` 取偶数位的点，格子自然变宽——这是「隔跨布置」最省事的写法。但切片到底取到了哪几个点，要自己看清：`list(XL[1::2])` 是 `[6000, 18000]`，格子成了 6000–18000（跳过了 12000 这个柱位）；如果只剩一个点（比如 3 点轴上的 `X[1::2]`），凑不成格子，`add_X` 直接返回 `[]`，**不报错**。

#### 招式 8：挖洞之后连——会跨过洞口

```python
P = X * Axis.points([0], axis="z")
hole = Axis.points([6000], axis="x") * Axis.points([0], axis="z")
BEAM.add_chain(P - hole, along="x")        # 1 根：0 → 12000，跨过被挖掉的 6000
```

`add_chain` 连的是「相邻的两个**留下的**点」，所以洞口两侧会直接连成一根 12000mm 的梁。要么这正是你要的大跨梁，要么就得改用 `add()` 逐根放。

#### 招式 9：点阵直接当节点位置表

```python
for p in X * Y:
    m.node(p, attrs={"支座": "固接"})       # 6 个支座节点
```

节点不需要构件：支座、主从节点、附加质量点，都可以直接铺在点阵上，还能共用同一批坐标。

#### 招式 10：对称结构只画一半

```python
half  = Axis.points([0, 6000], axis="x") * Y          # 左半区：x = 0 / 6000
right = half.mirror("x", about=12000)                 # 关于 x=12000 反射 → 18000 / 24000
```

`about=` 直接给对称轴的位置，坐标变成 `2×12000 − x`；带 offset 的点阵也一样（`shift(x=500)` 后再镜像 → 17500 / 23500）。两步写法 `mirror(about=0).shift(x=24000)` 结果相同，留作备选。

### 5.6 打断白名单：谁能切我

`split` 的前三种写法按「组」判断，第四种按「点」判断。

#### 组名白名单

```python
MBX = m.define("MBX", split=["SEC"])     # 只有 SEC 组带来的节点才切我
```

判断依据是「节点从哪来」：节点的 `sources` 里只要有一个构件属于白名单组，就允许切。

**写错的后果**——把白名单写成 `["MBY"]`（次梁根本不属于这个组）：

```
内部有节点但未打断（2）：
  MBX (0, 0, 4000)→(6000, 0, 4000)   内部 (3000, 0, 4000)  节点来源: ['SEC']
  → 符合 split="none" 的声明；若需连接请改用 split="all"
```

不抛异常，但证据一定留在报告里。

#### 坐标白名单

```python
COL = m.define("COL", split=("whitelist", {(0.0, 0.0, 2000.0), (0.0, 0.0, 4000.0)}))
```

读作：**只有正好落在这些三维坐标上的节点，才允许切我**。别的组带来的节点也不行，除非它正好在这个坐标上。

同一根柱（0 → 6000），三根梁的节点落在 1000 / 2000 / 4000，六种写法的实测结果：

| `split` 写法 | 含义 | 切在哪 | 柱段数 |
|---|---|---|---|
| `"none"` | 谁都不许切 | — | 1 |
| `"all"` | 任何节点都切 | 1000 / 2000 / 4000 | 4 |
| `["B"]` | 只让 B 组带来的节点切 | 三个节点都来自 B | 4 |
| `("whitelist", {(0, 0, 2000)})` | 只有这一个点能切 | 2000 | 2 |
| `("whitelist", {(0, 0, 2000), (0, 0, 4000)})` | 这两个点能切 | 2000 / 4000 | 3 |
| `("whitelist", {(0, 0, 2000.5)})` | 这个坐标上没有节点 | — | 1（静默不切） |

什么时候用它：**你要的断点在某个特定位置上，而那个位置又不是「某个组的构件」带来的**；或者不想因为一个组，把该组所有节点都放开。

两个坑：

- **精确匹配，不是范围**。比的是量化之后的坐标：`(3000, 0, 4000)` 与 `(3000.5, 0, 4000)` 是两个点。写 `2000` 和 `2000.0` 等价（Python 里相等），但写成网格外的值（如 2000.5，而实际坐标是 2000）永远匹配不上。
- **写错不报错**。匹配不上就是「不切」，只能靠报告里的 `内部有节点但未打断` 发现——库不猜你的意图，但一定留下证据。

### 5.7 大 X 不被切断

一根只受拉的斜杆，跨 2 跨 2 层，中点正好撞在中间柱与梁的交点上（一个真节点）。它**不能**被打断——一旦打断，拉杆中点被约束，力学模型完全变了。

```python
BR = m.define("BR", split="none")        # 关键就是这一行
BR.add((0, 0, 0), (12000, 0, 8000))
BR.add((0, 0, 8000), (12000, 0, 0))
```

```
INV: OK
内部有节点但未打断（2）：
  BR (0, 0, 0)→(12000, 0, 8000)   内部 (6000, 0, 4000)  节点来源: ['COL', 'BEAM']
```

此刻这一条是**正确状态**，不是错误。把 `split` 改成 `"all"`，两根斜杆会被切成 4 根——那是另一个（错误的）力学模型。

### 5.8 端部条件：三个层次

```python
# ① 构件两端（定义组时）
COL = m.define("COL", ends={"i": "刚接", "j": "刚接"})

# ② 打断处的新接缝
COL = m.define("COL", split="all", split_ends="刚接")
COL = m.define("COL", split="all", split_ends=("刚接", "铰接"))   # (左段 j 端, 右段 i 端)

# ③ 事后批量改
COL.set_ends(i="铰接")
COL.set(section="H500")          # 改 attrs
```

模型级也能给默认值，各组不写就继承：

```python
m = Model(default_split_ends="刚接")
```

没填就是 `None`，报告里的「端部未指定」会如实计数——不猜。

### 5.9 删除与合并：增删不对称

```python
m.remove(lambda mb: mb.group == "SEC")   # 也可传单个 Member 或 Member 列表
```

删除**不会**自动把因此断开的构件合并回去，这是刻意的：自动合并可能悄悄把两根铰接杆变成一根连续杆。

```python
COL.add((0, 0, 0), (0, 0, 8000))          # 1 段
BEAM.add((0, 0, 4000), (3000, 0, 4000))   # 柱被切成 2 段
m.remove(BEAM.all())                       # 删梁 → 柱仍是 2 段，留一个断点
m.merge_orphans()                          # 合并「同 origin + 相接 + 该节点无其他构件」→ 1 段
```

只合并指定的两根：

```python
m.merge(seg_a, seg_b, attrs="a")    # attrs 冲突时保留谁：'a' 或 'b'
```

### 5.10 查询与批量改

```python
m.by(group="COL")                 # 按组
m.by(layer="COL")                 # 按任意 attrs 键
m.by(origin=("COL", 1))           # 按「打断前是哪一根」
COL.where(lambda mb: m.nodes[mb.i].point[2] == 0)    # 组内再筛
COL.set(grade="Q355")             # 组内批量改属性
```

### 5.11 属性白名单：keys

组定义时声明允许哪些属性键，之后写错键名立刻报错，而不是默默存一个错键：

```python
K = m.define("K", keys=["section", "layer"], attrs={"section": "H400", "layer": "K"})
K.add((0, 0, 0), (1000, 0, 0), sectoin="H500")
# KeyError: 组 'K' 不认识属性 ['sectoin']；已声明：['layer', 'section']
```

---

## 6. 建模脚本里常用的 Python 语法

库只包办「坐标、构件、出口」三件事，**布置规则本身全部落回 Python**。所以写建模脚本，真正天天用的是这一章的东西。每一条都是「一句话 + 建模里的样子 + 实际输出」。

### 6.1 `[值] * n`：把同一个数重复 n 份

```python
SPAN_X = 6000

[SPAN_X] * 3             # [6000, 6000, 6000]      三跨等跨
[SPAN_X] * 2 + [4000]    # [6000, 6000, 4000]      混着不同跨长

Axis.spans([SPAN_X] * 3, axis="x")     # 0, 6000, 12000, 18000
```

最后一行要留意：`spans` 数的是**间距**，3 个间距 → **4** 个柱位。想得到 3 个柱位就写 `[SPAN_X] * 2`。新手最常在这里差一位。

### 6.2 `range`：其实只有三种形状

```python
range(len(X) - 1)          # 0, 1            相邻两点的「对数」
range(1, len(Z))           # 1, 2            跳过第 0 个（跳过 ±0 那层）
range(0, 12, 3)            # 0, 3, 6, 9      每 3 跨取一个（隔跨布置）
```

### 6.3 `zip(X, X[1:])`：相邻点对成捆取

```python
X = Axis.spans([6000, 6000], axis="x")

for a, b in zip(X, X[1:]):
    BEAM.add((a, 0, 4000), (b, 0, 4000))     # 一跨一根梁
```

`Axis` 可以直接迭代（拿到 mm 浮点），`X[1:]` 是**子轴**（还是 Axis）。`zip` 起来就是「每一对相邻点」，比 `for i in range(len(X) - 1): X[i], X[i + 1]` 干净一档。

两个轴也能 zip（按索引配对，长度取短的那个）：

```python
list(zip(X, Axis.points([0, 1000, 2000], axis="y")))
# [(0.0, 0.0), (6000.0, 1000.0), (12000.0, 2000.0)]
```

### 6.4 列表推导式：一条式子生成一批坐标或标签

```python
[x + 500 for x in X]           # 每个柱位偏移 500
[x for x in X if x > 0]        # 去掉 ±0
```

嵌套写法——每跨内插两个等分点（次梁位置）：

```python
[X[i] + (X[i + 1] - X[i]) * k / 3
 for i in range(len(X) - 1)
 for k in (1, 2)]
# [2000.0, 4000.0, 8000.0, 10000.0]
```

同一个需求往往有三种写法：三重 `for`、推导式、`add_chain`。**选读起来最不费劲的那个**，不必追求短。

#### 造标签：A…X、A1、A2

坐标是数字、标签是字符串，但**生成它们的语法完全一样**，只是元素来源不同。

```python
n = 24
list(range(1, n + 1))                      # [1, 2, 3, …, 24]          数字
[chr(ord("A") + i) for i in range(n)]      # ['A', 'B', …, 'X']        「从 A 起数 i 个」
list("ABCDEFGHIJKLMNOPQRSTUVWX")           # 同上，最省事的写法
list(string.ascii_uppercase[:n])           # 同上（import string）

[f"A{i}" for i in range(1, 6)]             # ['A1', 'A2', 'A3', 'A4', 'A5']
[f"{row}{i}" for row in "AB" for i in range(1, 4)]
# ['A1', 'A2', 'A3', 'B1', 'B2', 'B3']     ← 两排轴号：外层 row、内层 i
[f"{r}{i}" for i in range(1, 4) for r in "AB"]
# ['A1', 'B1', 'A2', 'B2', 'A3', 'B3']   ← 同样的两个循环，换顺序就是按排交错
[f"Z{i:02d}" for i in range(1, 4)]         # ['Z01', 'Z02', 'Z03']     补零，排序不出错
```

> 生成器表达式要 `list()` 包一下才是数组：`(chr(...) for i in range(n))` 是生成器，`list(...)` 才是 list。

这些标签直接喂给 `Axis` 的 `role`，图纸上的轴号就变成了代码里的名字：

```python
XL = Axis.spans([6000] * 4, axis="x", role=[f"A{i}" for i in range(1, 6)])
list(XL)            # [0.0, 6000.0, 12000.0, 18000.0, 24000.0]   5 条轴线
XL.role_of("A3")    # 12000.0                按轴号取坐标，不用数下标

YT = Axis.spans([6000], axis="y", role=["A排", "B排"])
YT.role_of("B排")   # 6000.0
```

| 想要的标签 | 写法 |
|---|---|
| A B C … X | `[chr(ord("A") + i) for i in range(24)]` |
| A1 A2 … A5 | `[f"A{i}" for i in range(1, 6)]` |
| A1 A2 A3 B1 B2 B3 | `[f"{row}{i}" for row in "AB" for i in range(1, 4)]` |
| A1 B1 A2 B2（按排交错） | `[f"{r}{i}" for i in range(1, 4) for r in "AB"]` |
| A01 A02（排序友好） | `[f"A{i:02d}" for i in range(1, n + 1)]` |


### 6.5 `enumerate` 与解包

```python
for i, x in enumerate(X):
    print(i, x)          # 既要第几根，也要坐标

p = (6000.0, 0.0, 4000.0)
x, y, z = p              # 点本来就是三元组，直接解包
```

### 6.6 `accumulate` / `sum`：间距与坐标的换算

`Axis.spans` 内部干的就是累加，但你自己算总长、半跨、节点标高时要用：

```python
from itertools import accumulate

list(accumulate([6000, 6000]))            # [6000, 12000]
[0] + list(accumulate([6000, 6000]))      # [0, 6000, 12000]   补上起点才等于 spans
sum([6000, 6000])                         # 12000              总长
```

### 6.7 字典当参数表

参数集中在一处，改一个数就能重跑：

```python
PARAMS = {"span": 6000, "bays": 3, "floor_h": 4000}
X = Axis.spans([PARAMS["span"]] * PARAMS["bays"], axis="x")
```

「构件规格表」驱动建组，加一类构件只加一行：

```python
SPEC = {"COL": "H400", "MBX": "HN300", "SEC": "HN200"}
for name, section in SPEC.items():
    m.define(name, attrs={"section": section, "layer": name})
```

`**` 把一个字典摊成关键字参数：

```python
opts = {"split": "all", "ends": {"i": "刚接", "j": "刚接"}}
m.define("G", **opts)      # 等价于 m.define("G", split="all", ends={"i": "刚接", "j": "刚接"})
```

### 6.8 三元表达式与 f-string

```python
"只受拉" if tension_only else "可受压"        # 端部条件二选一

f"COL_{i:02d}"        # COL_00、COL_01        补零，方便排序和做图层名
f"{4000 / 1000:.3f}m" # 4.000m                标高显示成米
```

### 6.9 函数封装：把布置规则收进口袋

规则一旦超过「填参数」，就写成函数——这是库刻意留的出口：

```python
def build_frame(n_bays=3, span=6000, n_floors=2, floor_h=4000):
    m = Model()
    X = Axis.spans([span] * n_bays, axis="x")
    Z = Axis.spans([floor_h] * n_floors, axis="z")

    COL  = m.define("COL",  split="all")
    BEAM = m.define("BEAM", split="none")

    for x in X:                              # 柱：每个柱位一根通高
        COL.add((x, 0, 0), (x, 0, Z[-1]))
    BEAM.add_chain(X * Z[1:], along="x")     # 梁：每层沿 X 连一遍

    return m, COL, BEAM


m, COL, BEAM = build_frame()
# 3 跨 × 2 层 → 柱 4 根切 8 段、梁 6 根、节点 12 个
```

末尾加一句，让脚本既能直接运行、又能被测试 import：

```python
if __name__ == "__main__":
    m, COL, BEAM = build_frame()
    print(m.report())
    m.export_dxf("out/frame.dxf")
```

`examples/frame_demo.py` 与 `tests/test_frame_example.py` 就是这个关系：示例里写 `build()`，测试 import 它。

### 6.10 六个坑

| 坑 | 现象 | 改法 |
|---|---|---|
| `[[0]] * 3` | 三行是**同一个** list，改一行动三行 | `[[0] for _ in range(3)]` |
| 拿浮点比坐标 | `0.1 + 0.2 == 0.3` 得 `False` | 用 `X.index_of()` / `role_of()` 查，或直接比整数 mm |
| `//` 与 `/` | `7000 // 3` 是 2333；`7000 / 3` 是 2333.333…（入模型后量化成 2333.3） | 要整除用 `//`；要真实值用 `/` 并接受量化 |
| `X[1:]` 的类型 | 以为拿到 list，其实是子轴 Axis | 真要 list 就 `list(X[1:])` |
| 遍历时删构件 | `for mb in grp.all(): m.remove(mb)` 会漏删 | 用 `m.remove(lambda mb: ...)`，库内部先收集再删 |
| 组名 / 属性名大小写 | `m.by(group="col")` 查不到东西 | 定名后保持一致；给组加 `keys=[...]`，拼错立刻报错 |

命名习惯（不是语法，但省事）：轴用大写 `X` / `Y` / `Z`，构件组用全大写 `COL` / `MBX`，参数常量用 `SPAN_X` / `FLOOR_H`——一眼能分出「这是坐标」「这是构件」「这是配置」。

---

## 7. 症状速查表

| 症状 | 原因 | 怎么办 |
|---|---|---|
| `Axis 坐标必须严格递增：X → X` | 两个输入值量化到同一格 | 检查输入，或调小 `set_quantum` |
| `ConflictError: 构件已存在` | 同组、同一对位置加了两根 | 去重，或换组 |
| `ValueError: 零长构件` | 两端点量化后重合 | 检查坐标 |
| `内部有节点但未打断（N）` | 该杆 `split="none"`，或白名单组名写错 | 改 `"all"` / 补白名单；确认是有意的大 X 就忽略 |
| `INV: × 违反` | 内部有节点、允许打断、却仍连成一根 | 属 bug 级，保留模型复现 |
| `端点（度=1…）` > 0 | 有构件没连上，或支座没标 | 按报告列出的坐标逐个查 |
| `连通分量` > 1 | 两个方向没连成整体 | 补另一方向的梁 |
| `短段告警` | 容差附近有两个近重合节点 | 看同一份报告的「量化近似点」 |
| `最低标高处有水平构件` | 梁放到了 ±0 | 标高轴用了 `include_base=True`，循环里要 `Z[1:]` |
| DXF 打开是空的 | 构件属性里没有 `layer` | 给组填 `layer`，或导出时补 `layers` |
| `'list' object has no attribute 'id'` | `add()` 被切成多段时返回 list | 用 `grp.all()`，或先判断类型 |

---

## 8. API 速查

标注约定：

- **→新**：返回一个新对象，原对象不变（`Axis` / `PointSet` 的全部变换）；
- **→改**：原位修改模型，返回句柄或数量（`Model` / `Group` 的写操作）；
- **只读**：不改任何东西。

```python
# ── Axis：全部是值对象 ──────────────────────────
Axis.spans(deltas, axis, base=0, include_base=True, role=None, name="")   # →新
Axis.points(values, axis, role=None, name="")                             # →新
Axis.step(step, n, axis, base=0)                                          # →新

X.shift(mm) / X.mirror(about) / X.with_role(roles) / X.where(fn)          # →新
X + Y / X | Y / X & Y / X - Y                                             # →新
X[i] / X[a:b] / X[[0, 2]]                                                 # →新（子轴）
X * Y                                                                     # →新（点阵）
X.cells / X.idx / X.role_of(v) / X.index_of(v) / X.um_at(i) / len(X)      # 只读

# ── PointSet：全部是值对象 ──────────────────────
PointSet.of(points)                                                       # →新
P.shift(x=, y=, z=) / P.mirror(axis, about) / P.mask(fn) / P.where(fn)    # →新
P.at(x=...) / P[...]                                                      # →新
P | P2 / P & P2 / P - P2 / P * Axis                                       # →新
P.shape / P.count() / P.points() / P.items()                              # 只读

# ── Model ──────────────────────────────────────
Model(default_split_ends=None)                                            # →新
m.define(name, split, attrs, keys, ends, split_ends)                      # →改（登记组），返回 Group
m.node(xyz, attrs=None, as_group=None)                                    # →改（可能切断构件），返回 Node
m.member(p, q, group=None, **attrs)                                       # →改，返回 Member 或 list
m.remove(pred) / m.merge(a, b) / m.merge_orphans()                        # →改
m.nodes / m.members / m.by(**query) / m.report(...)                       # 只读
m.export_dxf(path, layers={}) / m.export_fea(nodes_csv, members_csv)      # 只写文件

# ── Group ──────────────────────────────────────
g.add(p, q, **attrs) / g.add_pairs(P1, P2)                                # →改，返回 Member 或 list
g.add_chain(P, along="x") / g.add_X(P) / g.add_zigzag(P, along="y")       # →改，返回 list
g.set(**attrs) / g.set_ends(i=, j=)                                       # →改（原位改已有构件）
g.remove(pred) / g.clear()                                                # →改
g.all() / g.where(pred) / g.count()                                       # 只读（返回新列表）

# ── 顶层函数 ────────────────────────────────────
report(model, short_mm=150.0, show_cuts=True)                             # 只读
inv_violations(model) / unconnected_nodes(model)                          # 只读
export_dxf(model, path, layers={}) / export_fea(model, nodes_csv, members_csv)   # 只写文件
set_quantum(mm) / get_quantum() / step_um() / to_um(mm) / to_mm(um)       # 全局设置 / 换算
```

## 9. 设计边界：为什么是这样

| 选择 | 理由 |
|---|---|
| `split` 默认 `"none"` | 打断是破坏性操作（一根杆变两根，力学模型变），破坏性操作默认关 |
| 合并必须显式调用 | 自动合并可能悄悄改变力学模型 |
| 点—点合并不带容差 | 带容差的关系不传递，顺序无关性会崩塌 |
| 点—线段判定带 1 个步长容差 | 量化把本应共线的点挤出直线，最大偏离 ≈ 0.87 个步长 |
| 轴对齐杆可吸附，斜杆不吸附 | 斜杆上最近网格点间距可达上百 mm，吸附等于挪错位置 |
| 不判断铰接 / 刚接 | 那是力学判断，库只搬运；判断错了要能追到你填的那一行 |
| 不做 pip 包 | 自用库持续改，改完立即生效、拷目录即可 |
