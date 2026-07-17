# 九参数磁传感器标定 · 小白指引

> 目标读者：从来没有做过磁力计标定、甚至现在还没接入 TMR 传感器、只想搞清楚
> "从 0 开始要点哪几个按钮 / 敲哪几行命令、才能拿到一份可用的九参数标定档"
> 的同学。
>
> 全文分为两条路径：
>
> - **路径 A：不接入 TMR 纯模拟**（推荐第一次跑）— 用仿真脚本造一份带椭球畸变
>   的电压数据，完整走一遍"生成录制 → 拟合标定 → 加载启用 → 验证"。所有命令
>   可以在**任何电脑**上、**不需要任何硬件**就跑通。
> - **路径 B：接入 TMR 实机**（正式采集）— 真正拿传感器、旋转八字姿态、
>   在上位机里录制、离线拟合、加载启用。
>
> 两条路径**目录结构和文件契约完全一致**，路径 A 跑通之后再上真机不会踩坑。

---

## 0. 前置概念（30 秒版）

**九参数是啥？** — 磁力计的输出通常有 3 个问题：
1. **硬铁偏置（bias）**：三轴各有一个直流偏移（3 参数）。
2. **软铁畸变（尺度差异）**：三轴对同一 μT 的响应幅度不同（3 参数）。
3. **轴间投影**：三个感应轴装配后不完全正交，一个方向的磁场会串到另一个轴
   （3 参数）。

**标定就是求解这 9 个数**，得到一个 3×1 偏置向量 `b` 与一个对称 3×3 矩阵 `M`，
之后每次采样都执行：
```
B_cal = M · (B_raw − b)
```
理想情况下 `|B_cal|` 应该等于当地地磁模值，无论传感器怎么转。

**为什么要"旋转八字"？** — 拟合椭球需要样本尽量均匀覆盖三维方向球面。
八字轨迹是一种廉价的、能在几十秒内让传感器姿态覆盖球面大部分区域的手势。
静止不动或只绕一个轴转，样本会退化到一条线/一个平面上，求解会失败或者不
稳定。

**采集时环境要求：**
- 远离电脑机箱、大电缆、金属桌面、手机、钥匙；
- 手不要戴金属手表、金属戒指；
- 传感器附近 1 米内不要有铁磁物；
- 缓慢、均匀地转，30~60 秒足够。

---

## 路径 A：不接入 TMR 纯模拟

用途：验证上位机、脚本、`core/calibration.py` 的完整闭环，先跑通再面对真机。

### A.0 前置检查（一次性）

```bash
cd /Users/auv_user/coding/fangkong_adc
python -c "import scipy, numpy, matplotlib; print('deps ok')"
```
如果打印 `deps ok`，可以开始。缺依赖用 `pip install scipy numpy matplotlib`。

### A.1 生成一份"带畸变"的仿真录制

仿真脚本会构造 30 秒 / 2000 Hz / 3 通道的电压数据，内嵌 7% 左右的椭球畸变、
±3 μT 硬铁偏置和 3° 左右的轴间耦合，并落盘为一份和真机录制**字段完全一致**
的 `.npz` 文件。

```bash
python scripts/simulate_calibration_recording.py
```

期望输出（关键部分）：
```
============================================================
仿真录制文件已生成
============================================================
  路径:        raw_data/1780000000_123456.npz
  样本数:      60000
  采样率:      2000 Hz
  时长:        30 s
  真实 |B|:    50.00 μT
  畸变前 RMS: 7.31 % (体现椭球扭曲程度)

下一步：
  python scripts/calibrate_magnetometer.py raw_data/1780000000_123456.npz
```

> **想改仿真参数？** 打开
> [simulate_calibration_recording.py](file:///Users/auv_user/coding/fangkong_adc/scripts/simulate_calibration_recording.py)
> 文件顶端的"用户可修改变量"区，可调项包括：
> - `DURATION_SEC`：采集时长，改成 60 会得到 120000 样本；
> - `TRUE_FIELD_MAGNITUDE_UT`：模拟当地磁场模值（默认 50 μT）；
> - `SCALE_XYZ / CROSS_COUPLING / BIAS_UT`：仿真的椭球畸变真值；
> - `POSE_COVERAGE`：设 0.4 可模拟"只转了半圈"的欠采样情形，观察拟合恶化；
> - `NOISE_STD_V`：加大后可测试算法在噪声下的鲁棒性。

### A.2 拟合九参数标定档

```bash
python scripts/calibrate_magnetometer.py raw_data/1780000000_123456.npz
```

期望输出：
```
加载录制文件: raw_data/1780000000_123456.npz
样本数: 60000, 拟合样本数: 60000
通道: [0, 1, 2]
灵敏度: [20.02, 19.98, 19.96] mV/μT
标定前 |B| RMS 残差: 3.6538 μT (7.12%)
标定后 |B| RMS 残差: 0.0026 μT (0.00%)
标定文件已保存: calibration_profiles/20260701T115318_magnetometer_9param.json
验证图已保存: calibration_profiles/figures
────────────────────────────────────────────────────────────
[健康度] 总分 100.0 / 100  ·  等级: 健康 ✓
    样本数量          60000    得分 100.0
    姿态球面覆盖率    99.5%   得分 100.0
    |B| 残差比例      0.00%   得分 100.0
    矩阵条件数         1.22    得分 100.0
[健康度] 判定: 健康度良好，可直接加载使用。
────────────────────────────────────────────────────────────
```

**通过标准：**
- 拟合后 `RMS 残差` 应从 ~7% 降到 **< 0.5%**；
- **健康度总分 ≥ 80（healthy 档）**，四个分项得分都应接近 100；
- `calibration_profiles/` 下生成一份 `*_magnetometer_9param.json`；
- `calibration_profiles/figures/` 下会看到两张图：
  - `calibration_cloud.png` — 3D 点云"椭球 → 球"的前后对比；
  - `calibration_magnitude.png` — `|B|` 在整段时间上的一致性对比。

**演练"健康度不足"的场景**：把 A.1 的 `POSE_COVERAGE` 改成 `0.1`、`DURATION_SEC`
改成 `2`，再跑一次，可以看到脚本打印 `不足 ✗` 并以退出码 `2` 结束，用来验证
poor 分支。

如果残差不达标或健康度落到 acceptable/poor，回到 A.1 把 `POSE_COVERAGE` 调回
1.0、`NOISE_STD_V` 调小、`DURATION_SEC` 加大，再来一次。

> **无图形界面的 Linux/CI 环境**：在命令前面加 `MPLBACKEND=Agg` 即可跳过弹窗：
> ```bash
> MPLBACKEND=Agg python scripts/calibrate_magnetometer.py raw_data/1780000000_123456.npz
> ```

### A.3 在上位机加载并启用标定

即使数据是仿真的，加载流程和真机一模一样，练手用。

1. `python main.py` 启动上位机。
2. 点击右侧**"加载九参数标定"**按钮。
3. 在弹出的文件对话框里，选择 A.2 生成的
   `calibration_profiles/20260701T115318_magnetometer_9param.json`。
4. 勾选**"启用标定"**复选框。此时波形单位切到"磁场 (μT)"后就是标定后的量。
5. `calibration_label` 会显示例如 `启用: magnetometer_9param, RMS=0.00%`。

### A.4 用离线分析脚本再验证一次

```bash
python scripts/analyze_recording.py raw_data/1780000000_123456.npz
```

打开
[analyze_recording.py](file:///Users/auv_user/coding/fangkong_adc/scripts/analyze_recording.py)
顶端把 `APPLY_CALIBRATION = True`、
`CALIBRATION_PROFILE_PATH = "calibration_profiles/20260701T115318_magnetometer_9param.json"`。
再跑一遍，会看到 `|B|` 时域曲线由抖动的椭球带变成近乎水平的一条线。

### A.5 清理演练产物（可选）

```bash
rm raw_data/1780000000_123456.npz
rm -rf calibration_profiles/20260701T115318_magnetometer_9param.json calibration_profiles/figures
```

真机采集时会自动生成新的时间戳文件，不受影响。

---

## 路径 B：接入 TMR 实机

前提：SK2301 已经通电、传感器已挂在 CH1~CH3、上位机已经能看到实时波形。

### B.1 环境准备

1. 找一张**无金属**的桌面（塑料/木质最好），或直接手持传感器远离桌面。
2. 摘掉戒指、手表、钥匙串。
3. 关闭手机放到 2 米外。
4. 传感器和 SK2301 主机之间的连接线尽量顺直，不要盘绕在传感器附近。
5. 在上位机右侧确认：
   - **波形 Y 轴单位**：任意（录制存的是原始电压，与单位显示无关）；
   - **启用标定**：**不要勾**（我们正是要拟合出来的东西，不能带旧标定录）；
   - **锁相频率**：无所谓，录制会存原始电压。

### B.2 检查基线噪声

启动采集，静置传感器 10 秒，观察 `|B|`（切到"磁场 (μT)"单位）应该基本平稳。
如果看到明显方波、周期扰动，先排查环境（附近的开关电源、日光灯、电脑风扇），
排干净再进 B.3。

### B.3 开始录制并旋转八字

1. 点击**"信号录制"**按钮，按钮文字变为**"停止录制"**。
2. 手持传感器（或固定在旋转平台上），做以下姿态覆盖动作，**总时长 30~60 秒**：
   - 手腕先画一个横 8 字（Y-Z 平面）；
   - 再翻转 90°，做立 8 字（X-Y 平面）；
   - 最后做几次绕对角线的轻微翻转，让 Z 轴指向也覆盖上下。
3. 动作要**慢**（每个 8 字约 3~5 秒），避免高速运动引入运动学假信号。
4. 点击**"停止录制"**。上位机会打印一行类似：
   ```
   [Recorder] saved raw_data/1723456789_012345.npz
   ```
   记下这个路径，等下用。

> **旋转技巧**：想象你在把传感器"擦一个足球的整个表面"。如果只擦到球的
> 上半部分，或者只擦到赤道一圈，都是欠采样，标定会失败。

### B.4 拟合标定档

回到终端：
```bash
python scripts/calibrate_magnetometer.py raw_data/1723456789_012345.npz
```

**通过标准（真实数据）：**
- 拟合前 RMS 残差通常在 3%~15%（视传感器/环境而定）；
- 拟合后 RMS 残差应 < 1%，理想是 < 0.3%；
- **健康度必须落在 `健康 ✓` 或至少 `合格 ~` 档**；如果打印 `不足 ✗`（退出码 2），
  说明本次采集数据不够，重录！
- 生成
  [calibration_profiles/*.json](file:///Users/auv_user/coding/fangkong_adc/calibration_profiles)；
- `figures/` 下的点云前后对比图肉眼可见"椭球 → 球"。

如果拟合后残差仍然很大或健康度不足，往往是**姿态覆盖不足**（八字没画完整）
或**采集过程中路过铁磁物**。换个环境、重新录制即可，不需要修改脚本。

### B.5 上位机加载并启用

1. 点击**"加载九参数标定"** → 选择 B.4 生成的 JSON。
2. 勾选**"启用标定"**。此时切换 Y 轴单位到"磁场 (μT)"，`|B|` 应该在你缓慢
   转动传感器时**几乎保持不变**。
3. 想让下次开机自动加载？点击**"保存配置"**按钮，`config/user_config.yaml`
   会持久化 `calibration.profile_path` 和 `calibration.enabled`。

### B.6 常规维护

- 传感器搬到明显不同的电磁环境（例如从实验室换到户外），建议**重录**。
- 更换固定支架、导线路由变了、附近来了个新的直流磁体：**重录**。
- 常温状态下、位置未变的话，标定档可以复用几周到几月。

---

## 健康度指标（重点章节）

拟合脚本每次结束都会输出一份四维打分卡，用来判断**本次录制到的数据是否足以
支撑一份可靠的标定**。核心思想是：算法在数据不充分时也能"给出一份 profile"，
但那份 profile 不一定可信；健康度正是量化"可不可信"的门槛，避免用户被漂亮
的 RMS 残差数字骗到。

### 四个维度

| 维度 | 反映的问题 | 满分线 | 及格线 |
|------|-----------|--------|--------|
| 样本数量 | 采集时长够不够 | ≥ 40000 (~20s @ 2000Hz) | ≥ 6000 (~3s) |
| 姿态球面覆盖率 | 八字画得全不全 | ≥ 75% 网格被踩过 | ≥ 35% |
| \|B\| 残差比例 | 标定收敛得好不好 | ≤ 0.5% | ≤ 3% |
| 矩阵条件数 | 标定矩阵是否退化 | ≤ 2 | ≤ 8 |

四项加权（20% + 35% + 30% + 15%）得到 0~100 分总分，映射到三档：

| 等级 | 分数 | 退出码 | 含义 |
|------|------|--------|------|
| 健康 ✓ (healthy) | ≥ 80 | 0 | 数据充分，可直接加载启用 |
| 合格 ~ (acceptable) | 60 ~ 80 | 1 | 可用但不理想，关键场景建议重采 |
| 不足 ✗ (poor) | < 60 | 2 | **数据不够，请重采**，别用这份 profile |

### 健康度是怎么算出来的？

（源码：[compute_calibration_health()](file:///Users/auv_user/coding/fangkong_adc/core/calibration.py#L163-L253)）

**第 1 步 · 采集四个原始量**

- $N$ = 拟合用到的样本数（等于 npz 的行数）；
- $C$ = 姿态球面覆盖率。做法：把每个校正后的向量 $\mathbf{B}_i^{cal}$ 归一化到
  单位球面 $\hat{\mathbf{u}}_i = \mathbf{B}_i^{cal} / |\mathbf{B}_i^{cal}|$，
  用 $(\theta,\phi)$ 落入 24×24 的等经纬网格（共 576 格），
  $C = \#\{\text{被踩过的格子}\} / 576$；
- $R$ = 残差比例（%），来自 `evaluate_calibration()`：
  $R = 100 \cdot \mathrm{RMS}(|\mathbf{B}^{cal}| - \overline{|\mathbf{B}^{cal}|}) / \overline{|\mathbf{B}^{cal}|}$；
- $\kappa$ = 标定矩阵条件数 $\kappa(M) = \sigma_{\max}(M) / \sigma_{\min}(M)$，
  其中 $M$ 就是 profile 里的 3×3 校正矩阵。$\kappa\!=\!1$ 表示完全正交，
  越大越接近奇异。

**第 2 步 · 线性映射到分项得分 $s_j \in [0,100]$**

每个维度都用同一个"差—好"两端截断线性打分函数：
$$s_j = 100 \cdot \frac{\mathrm{clip}(v - v_{\text{worst}}, 0, v_{\text{best}} - v_{\text{worst}})}{v_{\text{best}} - v_{\text{worst}}}$$
（$R,\kappa$ 这两个"越低越好"的量取相反符号，逻辑等价。）

代入本项目的门槛：

| $j$ | 变量 | $v_{\text{worst}}$ | $v_{\text{best}}$ |
|-----|------|-----|-----|
| 样本 | $N$ | 6000 | 40000 |
| 覆盖 | $C$ | 0.35 | 0.75 |
| 残差 | $R$ | 3.0% | 0.5% |
| 条件 | $\kappa$ | 8.0 | 2.0 |

即：达到 best 得 100，达到 worst 得 0，中间线性插值。

**第 3 步 · 加权求和**

$$\text{score} = 0.20\,s_{\text{样本}} + 0.35\,s_{\text{覆盖}} + 0.30\,s_{\text{残差}} + 0.15\,s_{\text{条件}}$$

权重设计逻辑：**姿态覆盖 (0.35)** 是数据是否够用的根本，权重最高；
**残差 (0.30)** 是拟合是否收敛的直接产物；**样本 (0.20)** 是时长上的下界，
主要防止 3 秒就停手的极端场景；**条件数 (0.15)** 反映矩阵退化，
通常与覆盖不足高相关，权重较低作为兜底。

**第 4 步 · 分档 + 生成建议**

- $\text{score} \geq 80$ → healthy，退出码 0；
- $60 \leq \text{score} < 80$ → acceptable，退出码 1；
- $\text{score} < 60$ → poor，退出码 2。

同时对每一个 $s_j < 80$ 的维度生成对应 `issues` 与 `suggestions`，直接指导
用户"下次录制该怎么改进"，无需人肉解读原始数值。

**为什么用"截断线性"而不是加权 RMS 或 sigmoid？** — 门槛应当**语义可读**：
"覆盖率 75% 及以上算满分"这句话，等价于图上的一条水平线，用户能直接对照自己
录制到的覆盖率去看差多远。指数/S 型函数虽然平滑，但门槛不直观、调参门槛
高，与"小白指南"的定位不符。

### 落地位置

- 每份 profile 的 `calibration_profiles/*.json` 内新增 `health` 字段，
  保存分数、四维分项、issues、suggestions；
- 上位机 `calibration_label` 会显示例如 `启用: xxx, RMS=0.05%, 健康度=92(healthy)`；
- 拟合脚本 poor 时以**非零退出码 2** 结束，方便脚本/CI 自动拦截。

### 收到 `不足 ✗` 怎么办？

按 issues 里指出的项目逐条修：
- "样本数偏少" → 采集时间延长到 30~60 秒；
- "姿态球面覆盖率偏低" → 八字画得再完整些（横 8 字 + 立 8 字 + 对角翻转）；
- "|B| 残差偏大" → 检查铁磁物、导线路由，换个环境；
- "矩阵条件数偏大" → 增加姿态多样性，避免只沿单一轴旋转。

然后**重新录制**（路径 B）或**重新仿真**（路径 A），把新 npz 再跑一次拟合。

---

## 常见问题（FAQ）

**Q1. 标定过程中我可以让传感器自动动态更新九参数吗？**  
不建议。九参数一旦无约束在线更新，本地铁磁扰动会被算法当成"传感器偏差"
拟合掉，产生长期漂移。**规程**：离线拟合 → 加载 → 启用，中途不动。

**Q2. 我的采集设备只有 2 通道 / 或者装了 4 个磁力计怎么办？**  
本项目九参数标定**仅针对 3 轴磁力计**。多传感器需要每个 3 轴组各录一段、
各生成一个 JSON。目前上位机只支持一次加载一份。

**Q3. `.npz` 里都有什么？**  
参见
[core/recorder.py](file:///Users/auv_user/coding/fangkong_adc/core/recorder.py#L91-L99) 
中 `np.savez_compressed` 的字段清单。仿真脚本的 npz 字段与之逐字段一致。

**Q4. 拟合脚本可以不弹图吗？**  
可以，命令前加 `MPLBACKEND=Agg` 即可。

**Q5. 想把标定 profile 分享给同事的电脑？**  
只需要拷贝那一份 `calibration_profiles/*.json`。灵敏度、通道信息、标定矩阵、
偏置都在里面自成一体，与本地录制文件无关。

**Q6. 什么情况下要重跑一次仿真流程？**  
- 修改了 `core/calibration.py` 里的拟合算法后（想跑回归）；
- 想演示不同畸变强度下算法能收敛到什么精度；
- 教新人熟悉工具链。

---

## 相关文件索引

- 仿真脚本：[scripts/simulate_calibration_recording.py](file:///Users/auv_user/coding/fangkong_adc/scripts/simulate_calibration_recording.py)
- 拟合脚本：[scripts/calibrate_magnetometer.py](file:///Users/auv_user/coding/fangkong_adc/scripts/calibrate_magnetometer.py)
- 离线分析：[scripts/analyze_recording.py](file:///Users/auv_user/coding/fangkong_adc/scripts/analyze_recording.py)
- 标定核心 API：[core/calibration.py](file:///Users/auv_user/coding/fangkong_adc/core/calibration.py)
- 录制器契约：[core/recorder.py](file:///Users/auv_user/coding/fangkong_adc/core/recorder.py)
- 上位机入口按钮：[gui/control_panel.py](file:///Users/auv_user/coding/fangkong_adc/gui/control_panel.py#L64-L67)
