# 流式栅格拼接与面积归约设计（本轮仅设计，不实现）

本轮只交付本设计文档与可重跑观察证据，不实现目标流水线。source.py、
mosaic_ref.py、regrid_ref.py、pipeline.py 与原业务断言（checks.py）全部保留，
基线行为不变。下文所有"预测"字样均为拟议方案的推导结果，不是实际运行结果；
"实测"均指当前仓库里 `python3 checks.py` 与 `python3 observe.py all` 的真实输出。

## 1. 现有调用链与真实位置

当前基线是一次性全量物化的讨论用实现，调用链如下：

1. `pipeline.run(job)` 入口（pipeline.py:L7）。`pipeline.py:L8` 调
   `source.open_job(job)`，后者解析 target 与瓦片、校验名称/优先级唯一性
   （source.py:L69-L71）、校验行数（source.py:L73-L74），并为每块瓦片构造
   只能向前读的 `RowReader`（source.py:L78）。
2. `pipeline.py:L10-L19` 把每个 reader 循环读到耗尽（`reader.read()` 返回
   `None` 为止），把全部源行装进 `loaded`。`RowReader.read` 的向前读与轨迹
   追加在 source.py:L46-L58，读到末尾记 `["eof",name]`（source.py:L48-L50），
   `seek` 直接抛错（source.py:L60-L61）。**这一步保留了全部源行，是基线
   内存问题的第一部分。**
3. `pipeline.py:L20` 调 `mosaic_ref.compose(loaded)`。compose 收集所有瓦片的
   全部 x/y 边（mosaic_ref.py:L13-L18），对笛卡尔排列出的每个小矩形取中点
   （mosaic_ref.py:L22），逐瓦片比较优先级裁决胜出者（mosaic_ref.py:L24-L31），
   生成**整幅** patch 列表（mosaic_ref.py:L19-L33，Patch 定义在
   mosaic_ref.py:L5-L9）。这是基线内存问题的第二部分。
4. `pipeline.py:L21` 调 `regrid_ref.reduce_grid(target, patches)`。它对每个
   目标格遍历全部 patch，用 `overlap`（regrid_ref.py:L5-L7）累加有效面积与
   面积加权和（regrid_ref.py:L19-L24），再算覆盖率与均值
   （regrid_ref.py:L25-L27），并保留**整幅**目标结果（regrid_ref.py:L15、
   regrid_ref.py:L28）。这是基线内存问题的第三部分。
5. `pipeline.py:L22-L24` 返回 output、trace 与两个 materialized 计数。注意
   `loaded`、`patches`、`output` 在同一帧内同时存活，三者峰值叠加。
   契约已声明这两个 materialized 字段只报告基线规模，不是目标内存测量。

辅助事实：`Grid.rect` 给出半开单元矩形（source.py:L28-L30）；`q` 把有理数
字符串解析为 `Fraction`（source.py:L6-L7）；reader 夹具内部持有样例载荷，
但其背书存储"不是流水线工作内存"（source.py:L41 的 docstring），目标设计
只能经 `read()` 取载荷。行读取异常（如行宽不符，source.py:L53-L54）以异常
上抛，checks.py 的 test_bad_and_one_pass 覆盖了这些失败路径。

## 2. 设计须满足的契约不变量

- 每个空间位置先取覆盖它的最高优先级瓦片；高优先级 null 仍遮蔽低优先级值。
- 在胜出结果上逐目标格算：有效面积、覆盖率（有效面积/目标格面积）、面积
  加权均值；无有效面积时为 "0"、"0"、null（与 regrid_ref.py:L25-L27 的
  基线语义一致）。
- 全部精确有理数运算；源与目标边界允许错位；不得先逐瓦片聚合再合并。
- 源行只许向前读、每行至多一次；目标行按 y 递增逐行输出，已输出不改写。
- 工作内存按标量槽计 O(各源行宽之和 + 目标行宽 + 瓦片数)；源行、胜出区间、
  几何结构、部分面积、输出交接缓冲都计入；任意长容器按元素个数计槽。
- 不保留整幅拼接或目标结果，不转存全部载荷，不重开源；异常要向调用者报告
  失败，已交付行可保留。

## 3. mask_offset 独立手算（不依赖生产代码）

瓦片：old（优先级 1）覆盖 x∈[0,3)，行值 [2,4,8]，每格宽 1；new（优先级 2）
覆盖 x∈[1/2,3/2)，值为 null。目标单格 [0,3)×[0,1)，格面积 3。

把所有 x 边排序：0, 1/2, 1, 3/2, 2, 3，逐段裁决：

| x 段 | 覆盖瓦片 | 胜出者 | 值 | 有效面积 | 加权 |
|---|---|---|---|---|---|
| [0,1/2) | old | old | 2 | 1/2 | 1 |
| [1/2,1) | old,new | new | null（遮蔽 old 的 4） | 0 | 0 |
| [1,3/2) | old,new | new | null | 0 | 0 |
| [3/2,2) | old | old | 4 | 1/2 | 2 |
| [2,3) | old | old | 8 | 1 | 8 |

有效面积 = 1/2+1/2+1 = 2；加权和 = 1+2+8 = 11；均值 = 11/2；覆盖率 = 2/3。
与 checks.py 锚点断言（area "2"、coverage "2/3"、mean "11/2"）一致。

两点推论：new 的 null 不是透明区，而是把 [1/2,3/2) 上的旧值 4 整段遮蔽；
若先逐瓦片聚合（old 全幅均值 14/3、new 无有效值）再合并，无法恢复 11/2，
因为遮蔽是逐位置发生的——这正是契约禁止"先逐瓦片聚合再合并"的原因。

## 4. 基线实测观察

以下为 `python3 observe.py all` 的完整真实输出（重跑命令：
`python3 observe.py all`，回归命令：`python3 checks.py`）：

```observations
[
  {
    "name": "mask_offset",
    "output": [
      [
        {
          "area": "2",
          "coverage": "2/3",
          "mean": "11/2"
        }
      ]
    ],
    "trace": [
      [
        "read",
        "old",
        0
      ],
      [
        "eof",
        "old"
      ],
      [
        "read",
        "new",
        0
      ],
      [
        "eof",
        "new"
      ]
    ],
    "materialized_source_cells": 4,
    "materialized_patches": 5
  },
  {
    "name": "coarse_fine",
    "output": [
      [
        {
          "area": "1",
          "coverage": "1",
          "mean": "4"
        },
        {
          "area": "1",
          "coverage": "1",
          "mean": "4"
        }
      ],
      [
        {
          "area": "3/4",
          "coverage": "3/4",
          "mean": "10/3"
        },
        {
          "area": "1/2",
          "coverage": "1/2",
          "mean": "2"
        }
      ],
      [
        {
          "area": "1",
          "coverage": "1",
          "mean": "7/2"
        },
        {
          "area": "3/4",
          "coverage": "3/4",
          "mean": "2"
        }
      ]
    ],
    "trace": [
      [
        "read",
        "base",
        0
      ],
      [
        "eof",
        "base"
      ],
      [
        "read",
        "fine",
        0
      ],
      [
        "read",
        "fine",
        1
      ],
      [
        "read",
        "fine",
        2
      ],
      [
        "read",
        "fine",
        3
      ],
      [
        "eof",
        "fine"
      ],
      [
        "read",
        "top",
        0
      ],
      [
        "eof",
        "top"
      ]
    ],
    "materialized_source_cells": 6,
    "materialized_patches": 24
  },
  {
    "name": "outside_empty",
    "output": [
      [
        {
          "area": "0",
          "coverage": "0",
          "mean": null
        },
        {
          "area": "0",
          "coverage": "0",
          "mean": null
        }
      ]
    ],
    "trace": [],
    "materialized_source_cells": 0,
    "materialized_patches": 0
  },
  {
    "name": "fractional",
    "output": [
      [
        {
          "area": "2/9",
          "coverage": "2/9",
          "mean": "3/2"
        }
      ]
    ],
    "trace": [
      [
        "read",
        "a",
        0
      ],
      [
        "eof",
        "a"
      ]
    ],
    "materialized_source_cells": 1,
    "materialized_patches": 1
  }
]
```

由实测计数推算的基线峰值持有（标量槽，`loaded`+`patches`+`output` 同帧
共存，见 pipeline.py:L19-L21；每个 Patch 按 rect 4 标量 + owner + value =
6 槽计）：

| 样例 | 源行格数（实测） | patch 数（实测） | 推算峰值槽数 |
|---|---|---|---|
| mask_offset | 4 | 5 | 4 + 5×6 + 1×3 = 37 |
| coarse_fine | 6 | 24 | 6 + 24×6 + 6×3 = 168 |
| outside_empty | 0 | 0 | 0 + 0 + 2×3 = 6 |
| fractional | 1 | 1 | 1 + 6 + 3 = 10 |

基线峰值随整幅笛卡尔排列增长（mosaic_ref.py:L19-L33），不满足目标预算。

## 5. 流式设计总览

### 5.1 扫描不变量

所有网格轴对齐、共用同一坐标系。把 target 行边与所有瓦片的行边（裁剪到
目标 y 范围内）合并为 y 事件流，相邻事件构成**条带** [s0,s1)。条带内每块
瓦片至多一行与之相交，因此"当前行"在每块瓦片上最多一个，胜出函数在条带
内只随 x 变化。条带按 y 递增处理，与目标行输出顺序一致。

关键内存事实：y 事件**不物化全表**。瓦片行边是等差序列（y + i·dy），每块
瓦片只记"下一条边"一个标量，每步取 T+1 个候选边的最小值推进（T 为瓦片
数），状态 O(T)。若把全部行边列表物化，总量是 O(总行数)，超出来自
"各源行宽之和"的预算——1×N 的窄高瓦片就是反例。

### 5.2 源行懒读与释放条件

- 条带 [s0,s1) 需要瓦片 t 时，所需行号 n = floor((s0 − t.y)/t.dy)（精确
  有理数下取整，无浮点容差）。若 reader 的下一行号落后于 n，逐行 read
  并**立即丢弃**跳过的行（它们完全位于目标范围之下，对任何目标格无
  贡献），直到当前行为 n；读入的行作为 t 的当前行持有。
- **释放条件**：当扫描底边 s0 推进到 ≥ 当前行的顶边时，该行之后只会
  与已输出的目标行相交，立即释放，且因单向前读永不再次需要。
- 目标范围之外（更低或更高）的源行从不读入；活动性判断只用网格元数据，
  不靠读到 eof，因此预测轨迹中没有 eof 事件（与基线 pipeline.py:L11-L18
  把每个 reader 排空、source.py:L48-L50 记 eof 的行为不同）。
- 每块瓦片任意时刻至多持有一行：源行持有总量 ≤ 各源行宽之和。

### 5.3 胜出区间的交付接口

条带内把活动瓦片的列边（裁剪到目标 x 范围）与目标列边合并排序，得到基本
x 段；每段取中点（与 mosaic_ref.py:L22、checks.py 独立核验同一约定），在
活动瓦片中找覆盖中点的最高优先级者，查其当前行对应列取值。半开边界本身
面积为零，归属约定不影响面积/覆盖率/均值。相邻同（胜出者，值）的段可
合并为**胜出区间** (x0, x1, value)；value 为 null 表示"有胜出者但无数据"
（遮蔽），无瓦片覆盖的段不出现在区间表中。两种空态对面积贡献同为零，但
接口上区分，便于消费者审计。

### 5.4 消费者暂停时的持有划分

目标流水线对调用者暴露**拉式行迭代器**：每次 yield
(行号, 该行 W 个格子的 (area, coverage, mean) 三元组)，行号严格递增、每行
恰好一次、交出后不改写。消费者暂停时：

- 已 yield 的行归消费者所有；生产者（扫描循环）悬停在 yield 点，持有：
  各瓦片当前行（≤ Σ行宽）、当前目标行的部分面积累积器（2W）、每瓦片
  几何/行号状态（O(T)）。
- 尚未读入的源载荷仍留在 reader 夹具背书存储中（source.py:L41 声明其
  不计入流水线工作内存）；不存在任何额外暂存文件或整幅缓冲。
- 轨迹（trace）若调用者需要，按事件流出、由调用者持有，不计入流水线
  工作内存。

### 5.5 精确算术的数值位宽因素

设输入有理数分子分母位宽不超过 B。边坐标 x+i·dx 的分母位宽 ≤ b(x)+b(dx)、
分子多 log(i)；段面积是两条边差之积，位宽为两者之和；单格累积至多 S 段
求和，公分母位宽 O(S·B)、分子 O(S·B+log S)；均值最后一次除法，位宽仍是
操作数位宽之和。因此**每个标量槽**是位宽关于输入总位长多项式（近似线性）
的精确有理数；比特级内存 = 槽数 × 该位宽，报告复杂度时两者不可混为一谈。
Python `Fraction` 每次运算做 gcd 约分，单次精确运算成本随位宽增长（欧几
里得算法，多项式时间），如实计入精确运算成本。任何容器（行元组、区间表、
边列表）按元素个数计槽，不得把一个任意长容器算作一个标量槽。

## 6. 方案 A：目标行边切分的融合条带扫描（推荐）

### 6.1 状态

- 每瓦片：reader 引用、下一行号、当前行（或空）、网格元数据 —— O(T) 加
  当前行载荷 ≤ Σ行宽。
- y 事件：每瓦片下一条行边 + 目标下一条行边，O(T)。
- 当前条带的 x 边列表：≤ Σ活动(w_t+1) + (W+1) 槽。
- 当前目标行累积器：每列 (area, weighted) 两个精确有理数，2W 槽。
- 输出交接缓冲：正在构造/交出的一行，3W 槽。

### 6.2 关键伪代码

```text
def stream_rows(job):                     # 拉式迭代器，逐目标行 yield
    target, readers, trace = open_job(job)          # 复用 source.py:L64-L79
    ybot, ytop = target.y, target.y + target.height*target.dy
    next_edge[t] = 每块瓦片在 (ybot, ytop) 内的第一条行边   # O(T) 状态
    accum = [(0, 0)] * target.width                 # (area, weighted)
    row = 0
    s0 = ybot
    while s0 < ytop:
        s1 = min(所有 next_edge, target.y + (row+1)*target.dy)   # 条带顶
        active = [t : t.y <= s0 < t.y + t.height*t.dy]           # 元数据判断
        for t in active:
            ensure_current(t, s0)      # 懒读+丢弃跳过行；必要时释放旧行读新行
        xs = sort(活动瓦片列边 ∩ [tx0,tx1] ∪ 目标列边)            # O(Σw+W)
        for [e0,e1) in 相邻段:
            w = 覆盖中点 (e0+e1)/2 的最高优先级活动瓦片            # 重复裁决点
            if w 存在且值 v 非 null:
                c = 目标列号((e0+e1)/2)                          # 精确下取整
                a = (e1-e0)*(s1-s0)
                accum[c] = (accum[c].area + a, accum[c].weighted + a*v)
        if s1 == target.y + (row+1)*target.dy:    # 越过目标行顶边
            yield row, finalize(accum)   # coverage=area/(dx*dy); mean=weighted/area 或 null
            accum = [(0, 0)] * target.width; row += 1
        推进各 next_edge; s0 = s1
```

### 6.3 跨目标行面积归属与交接

y 事件包含目标行边，因此每个条带完整落在**唯一**目标行带内：部分面积在
产生的那一刻就归属确定，无需二次拆分；粗源行跨多个目标行时，其 x 结构在
每个条带**重新裁决**（如实计入重复裁决成本）。胜出区间不跨条带存活，交接
给调用者的只有完成的目标行（3W 槽）。

### 6.4 成本（如实报告）

- 扫描：条带数 ≤ 目标行数 + Σ(瓦片行数)；每条带一次 x 边排序
  O((Σw+W) log)；胜出判定为"段 × 活动瓦片"的线性扫描（可用按优先级
  排序+区间扣减优化，但此处不承诺时间目标）。
- 重复裁决：粗源行跨 k 个目标行 ⇒ 其 x 结构被裁决 k 次。
- 精确运算：每段两次有理数乘法、至多两次加法，位宽因素见 §5.5。
- 读/写：每源行恰好 read 一次；每目标行恰好 yield 一次；无临时文件。

## 7. 方案 B：源条带区间复用（两级生成器）

### 7.1 组织与状态

y 事件**只取瓦片行边**（加目标底/顶），条带内胜出区间只算一次，物化为
不可变记录交给第二级：

```text
def mosaic_stage(readers, target):        # 生成器 1：空间胜出
    for 每个源条带 [s0,s1):                # 事件仅来自瓦片行边
        ensure_current(...)               # 同方案 A 的懒读/释放
        intervals = 合并后的胜出区间表     # (x0,x1,value|None)，O(Σw+W)
        yield SlabRecord(s0, s1, intervals)

def regrid_stage(target, slabs):          # 生成器 2：面积归约
    accum = [(0,0)] * W; row = 0
    for rec in slabs:
        for rec 覆盖的每个目标行带 [b0,b1):       # 跨目标行归属在这里拆分
            h = min(rec.y1, b1) - max(rec.y0, b0)
            for (x0,x1,v) in rec.intervals if v 非 null:
                按目标列边切开，逐列加 (宽×h, 宽×h×v) 到 accum
            if rec.y1 >= b1: yield row, finalize(accum); 重置; row += 1
```

### 7.2 持有划分与成本

- 胜出区间的交付接口即 SlabRecord；消费者（regrid_stage）暂停时，当前
  记录由消费者的迭代变量持有（至多一份，O(Σw+W)），生产者悬停在 yield
  点持有各瓦片当前行。任一时刻至多一个目标行累积器处于"未闭合"状态
  （目标行带在 y 上连续且按序处理），累积器仍是 2W 槽。
- 省去方案 A 在粗源跨目标行时的重复裁决：每个源条带只裁决一次。
- 代价：区间表必须作为记录物化并跨内层循环存活（方案 A 中它只是瞬态）；
  每条区间还要在消费者侧按目标列边再切一次（额外一遍 O(区间数×W) 的
  行走）；归属逻辑（部分高度 h）明显更复杂。

## 8. 两种组织比较与推荐

| 维度 | 方案 A（融合，目标行边切分） | 方案 B（源条带复用，两级生成器） |
|---|---|---|
| 内存槽类 | Σ行宽 + O(Σw+W) 瞬态边/段 + 2W + 3W + O(T) | 同类；区间表作为记录跨行存活，同阶 |
| 裁决次数 | 源条带 × 其跨目标行数 | 每源条带一次（最少） |
| 归属逻辑 | 条带即行带，零拆分 | 区间 × 行带求交，部分高度 |
| 交接 | 仅目标行（3W） | 目标行 + 在途 SlabRecord |
| 正确性论证 | 每段归属唯一行，直接 | 需论证跨行拆分求和守恒 |
| 失败/暂停语义 | 相同（§5.4） | 相同，外加在途记录归属规则 |

小例核对（推导用，非实现）：单瓦片 g（x=0,y=0,dx=1,dy=3,1×1，值 5），
目标 1×3（dx=dy=1）。方案 A 切出 3 个条带、对同一 x 结构裁决 3 次；方案 B
只有 1 个条带 [0,3)，裁决 1 次，记录 (0,1,5) 以高度 1 复用于 3 个目标行，
每行得 area=1、coverage=1、mean=5——手算每格被值 5 全覆盖，结果一致。

**推荐方案 A**。业务场景是按面积**降采样**（目标比多数源粗），源行跨多个
目标行的情形少，A 的重复裁决近乎为零；A 的归属与输出逻辑最简单、交接缓冲
最小、正确性论证最直接，且内存阶与 B 相同。若未来目标比源更细（升采样）
或粗源极大跨域成为主流，B 的区间复用更省裁决，届时再切换；两者对外行
迭代接口一致，可替换。

## 9. 公开样例逐步推演（方案 A，预测）

### 9.1 mask_offset

y 事件 {0,1}，单条带 [0,1)。s0=0 时懒读 old#0、new#0（持有 3+1=4 格）。
x 边 {0,1/2,1,3/2,2,3}，胜出区间（合并后）：[0,1/2)→old 2；
[1/2,3/2)→new null（遮蔽 old 的 4 与 8 左侧）；[3/2,2)→old 4；
[2,3)→old 8。累积 (area,weighted) = (2,11)，s1=1 触线，交出
(area "2", coverage "2/3", mean "11/2")。与 §3 手算一致。

### 9.2 coarse_fine（粗细错位 + 三瓦片遮蔽）

y 事件：base{0,3} ∪ fine{1/2,1,3/2,2,5/2} ∪ top{3/2,5/2} ∪ 目标{0,1,2,3}
→ 6 个条带。逐条带（累积器记为 (面积, 加权和)，按目标行分列 c0/c1）：

| 条带 | 活动瓦片（当前行） | 读取 | 胜出区间（x） | 归属累积 | 释放 |
|---|---|---|---|---|---|
| [0,1/2) | base r0=2 | base#0 | [0,1)→2，[1,2)→2 | 行0: c0(1/2,1) c1(1/2,1) | — |
| [1/2,1) | base r0，fine r0=10 | fine#0 | [0,1/2)→2；[1/2,1)→10；[1,3/2)→10；[3/2,2)→2 | 行0: c0(1,4) c1(1,4)；s1=1 触线**交出行0**：(1,1,4),(1,1,4) | fine r0（顶边=1） |
| [1,3/2) | base r0，fine r1=null | fine#1 | [0,1/2)→2；[1/2,3/2)→null 遮蔽；[3/2,2)→2 | 行1: c0(1/4,1/2) c1(1/4,1/2) | fine r1 |
| [3/2,2) | base r0，fine r2=6，top r0=null | fine#2、top#0 | [0,1/2)→2；[1/2,1)→6；[1,3/2)→**top null 遮蔽 fine 6 与 base 2**；[3/2,2)→2 | 行1: c0(3/4,5/2) c1(1/2,1) | fine r2 |
| [2,5/2) | base r0，fine r3=8，top r0 | fine#3 | [0,1/2)→2；[1/2,1)→8；[1,3/2)→top null；[3/2,2)→2 | s0=2 前**交出行1**：(3/4,3/4,10/3),(1/2,1/2,2)；行2: c0(1/2,5/2) c1(1/4,1/2) | fine r3、top r0（顶边=5/2，于条带末） |
| [5/2,3) | base r0 | 无（元数据判定 fine/top 不活动，不尝试读、无 eof） | [0,1)→2；[1,2)→2 | 行2: c0(1,7/2) c1(3/4,3/2)；s1=3 **交出行2**：(1,1,7/2),(3/4,3/4,2) | base r0 |

三行结果与 checks.py 的 test_coarse_rows 逐格一致。持有峰值出现在
[3/2,2)、[2,5/2) 两个条带：base r0 + fine 当前行 + top r0 = 3 格源行；
base r0 跨越全部 6 个条带只读一次、持有到 y=3 才释放——这正是"粗源一行
跨三个目标行"的持有形态；fine 的 null 行与 top 的 null 都按胜出者遮蔽，
不贡献面积。

### 9.3 fractional

y 事件 {0,1/6,1/2,2/3} → 3 条带。[0,1/6)、[1/2,2/3) 无活动瓦片；
[1/6,1/2) 懒读 a#0，x 段 [1/3,1) 胜出值 3/2，面积 (2/3)×(1/3)=2/9，
加权 1/3。交出 (area "2/9", coverage "2/9", mean "3/2")（目标格面积
3/2×2/3=1）。源行在 s0=1/2 越过行顶后释放。

### 9.4 outside_empty（空覆盖）

零瓦片：y 事件只有目标行边 {0,1}，单条带，活动集为空，x 段仅目标列边，
无任何贡献。累积器保持 (0,0)，交出两格 (area "0", coverage "0",
mean null)——均值 null 严格由"有效面积为 0"触发，与 regrid_ref.py:L27
的基线语义一致。全程 0 次读取、0 格源行持有。

## 10. 峰值持有量核账（方案 A 预测 vs 基线实测推算）

类别：①源行当前值 ≤ Σ活动行宽；②x 边列表 ≤ Σ活动(w_t+1)+(W+1)；
③胜出区间 ≤ ②−1（方案 A 中瞬态，可再降为 O(T) 的 k 路归并，此处按
物化上限计）；④目标行累积器 2W；⑤输出交接行 3W；⑥瓦片状态 ≤ 10T
（名称、优先级、6 个网格标量、下一行号、当前行引用）。扫描峰 =
①+②+③+④+⑥；交接峰 = ①+④+⑤+⑥。

| 样例 | ① | ② | ③ | ④ | ⑤ | ⑥ | 扫描峰 | 交接峰 | 基线推算峰（§4） |
|---|---|---|---|---|---|---|---|---|---|
| mask_offset | 4 | 8 | 7 | 2 | 3 | 20 | 41 | 29 | 37 |
| coarse_fine | 3 | 9 | 8 | 4 | 6 | 30 | 54 | 43 | 168 |
| outside_empty | 0 | 3 | 2 | 4 | 6 | 0 | 9 | 10 | 6 |
| fractional | 1 | 4 | 3 | 2 | 3 | 10 | 20 | 16 | 10 |

两点如实说明：coarse_fine 从 168 降到 54，且方案 A 的各行类别都不随整幅
尺寸增长（只随行宽、目标行宽、瓦片数增长）；outside_empty 这类空/小任务
上，流式的固定累积与交接开销（10 槽）反而高于空基线（6 槽）——预算承诺
的是增长阶而非逐点更小。方案 B 在四个公开样例上条带数与 A 相同（目标行边
均与源边重合），峰值仅多一份在途区间记录，同阶。

## 11. 预测读取轨迹（推导结果，非实际运行）

方案 A 下每源行恰好读一次、按 y 序交错；活动性靠元数据判断，不读到末尾，
故无 eof 事件（基线实测轨迹含 eof，因其排空每个 reader，pipeline.py:L11-L18）：

- mask_offset：[["read","old",0],["read","new",0]]
- coarse_fine：[["read","base",0],["read","fine",0],["read","fine",1],
  ["read","fine",2],["read","top",0],["read","fine",3]]
- outside_empty：[]
- fractional：[["read","a",0]]

裁决/扫描成本（预测）：mask_offset 1 条带、5 段、10 次胜出判定；
coarse_fine 6 条带、20 段、44 次；outside_empty 1 条带、2 段、0 次；
fractional 3 条带、5 段、3 次。对照基线实测结构：compose 的中点判定
mask_offset 5×2=10、coarse_fine 24×3=72、fractional 1×1=1 次，
reduce_grid 的 overlap 求值 coarse_fine 达 6×24=144 次
（mosaic_ref.py:L20-L33、regrid_ref.py:L19-L24）。

## 12. 核验与演示的接通

- 原回归保留：`python3 checks.py`（5 项业务断言）不变。
- 文档核验：`python3 review.py DESIGN.md` 重放观察并比对本文唯一
  observations 块、抽查源码行号存在性；行号是否指向所述逻辑仍需人工复核
  （review.py 的 docstring 亦声明其不证明未实现设计的正确性）。
- 运行清单 .pointwise-runtime.json 的 verify 改为 `python3 verify.py`：
  该包装入口先跑 `python3 checks.py`，再跑 `python3 review.py DESIGN.md`，
  任一失败即整体失败；demo 仍为 `python3 observe.py all`，展示真实结果与
  读取轨迹。

## 13. 边界与限制

本设计不涉及投影、旋转网格、新文件格式、并发执行、进程恢复或远端存储；
消费者暂停仅为同步迭代边界。本文不实现目标流水线，所有方案侧数字为推导
预测；精确性最终仍须由实现后的逐格断言（如 checks.py 的 independent_cell
交叉核验）证明。
