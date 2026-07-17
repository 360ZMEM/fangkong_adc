# SK2301 FFT/Lock-in 数学正确性与丢包计划

## Summary

本计划的目标是把当前采集与 DSP 架构收敛到“严格依赖硬件采样率、固定长度滚动窗口、可检测丢包并进行补点”的形态，以保证 `FFT`、`Lock-in` 和波形时间轴的数学定义一致且可审计。

本计划同时覆盖两条数据模式：

1. 主机主动读寄存器 `19` 的透明以太网模式。
2. 设备自动上传波形数据包模式。

用户已明确的决策：

- 计划需同时覆盖上述两条模式。
- 丢包补点默认采用 `零阶保持 (Zero-order hold)`。

本计划不会再以本地系统时间作为 `Δt` 的来源；系统时间最多只允许用于日志打点、线程调度和性能观测，不能参与任何波形横轴、FFT 频率轴或锁相参考相位的数学定义。

## Current State Analysis

### 当前已满足的部分

- 当前 `FFT` 与 `Lock-in` 的实现本身使用 `np.arange(n) / sample_rate_hz` 构造频率/参考波，代码位于 [dsp.py](file:///Users/auv_user/coding/fangkong_adc/core/dsp.py) 和 [lockin.py](file:///Users/auv_user/coding/fangkong_adc/core/lockin.py)。
- 当前波形绘制也使用“样本点数 / sample_rate_hz”构造 X 轴，而不是直接拿 `time.time()` 做点间隔，代码位于 [plot_widgets.py](file:///Users/auv_user/coding/fangkong_adc/gui/plot_widgets.py)。
- 当前存在滑动缓冲和环形缓存基础设施：[stream_parser.py](file:///Users/auv_user/coding/fangkong_adc/protocol/stream_parser.py)、[ring_buffer.py](file:///Users/auv_user/coding/fangkong_adc/core/ring_buffer.py)。

### 当前不满足用户要求的部分

#### 1. 仍然存在“基于本地时间反推有效采样率”的路径

当前 [pipeline.py](file:///Users/auv_user/coding/fangkong_adc/core/pipeline.py) 中：

- 使用 `time.monotonic()` 统计单位时间内解码样本数；
- 通过 `_effective_sample_rate_hz` 动态更新 `snapshot.sample_rate_hz`；
- 后续波形 X 轴、FFT、Lock-in 都使用这个“本地时间估算出来的有效采样率”。

这与本次目标冲突，因为它仍然让“本地时间”参与了 `Δt` 的定义。

#### 2. DSP 不是“固定窗口 + 固定步长触发”

当前 [pipeline.py](file:///Users/auv_user/coding/fangkong_adc/core/pipeline.py) 中：

- 每来一批数据就调用 `_publish_snapshot()`；
- `waveform` / `dsp_window` 使用 `latest(min(size, ...))` 现取；
- FFT 与 Lock-in 的触发不是“每推进固定 N 点触发一次”，而是“收到多少算多少”。

这不满足“固定长度滚动窗口 + 固定 hop size”的架构约束。

#### 3. 当前协议解析器没有 `pack_num` 能力

当前 [constants.py](file:///Users/auv_user/coding/fangkong_adc/protocol/constants.py)、[frames.py](file:///Users/auv_user/coding/fangkong_adc/protocol/frames.py)、[stream_parser.py](file:///Users/auv_user/coding/fangkong_adc/protocol/stream_parser.py) 只支持当前项目使用的 `16` 字节 FkPro 主动读应答头。

根据文档：

- 主动读寄存器 `19` 的读帧/应答头是当前实现的 `16` 字节寄存器风格。
- `pack_num` 出现在自动上传波形数据包的 `52` 字节包头中，见 [SK2301与FKPro技术契约总结.md](file:///Users/auv_user/coding/fangkong_adc/参考文档/SK2301与FKPro技术契约总结.md) 和 `MinerU_markdown_FKPro通讯协议及编程说明书...md`。

因此：

- 当前主动读模式下，代码里**没有可用的 `pack_num` 来源**。
- 若要严格基于 `pack_num` 做丢包检测，必须引入“自动上传包头解析能力”。

#### 4. 当前 README 中的“有效采样率自适应收敛”描述将与本次目标冲突

当前 [README.md](file:///Users/auv_user/coding/fangkong_adc/README.md) 已记录了“使用本地时间估计有效采样率以修复时间漂移”的结论。执行本计划后，这部分需要改写为：

- 数学主链路只信任硬件采样率；
- 本地时间只能做诊断，不参与算法时间基准。

## Assumptions & Decisions

### 核心决策

1. `FFT`、`Lock-in`、波形 X 轴统一采用“样本序号 / Fs”的时间定义。
2. `Fs` 的合法来源只有两个：
   - 主动读模式：信任配置/下发给设备的 `device.sample_rate_hz`。
   - 自动上传模式：优先信任上传包头中的 `ad_fre`，并对异常变化进行告警。
3. 本地 `time.time()` / `time.monotonic()` 不再参与任何样本间隔估计，不再更新 `snapshot.sample_rate_hz`。
4. DSP 使用“固定窗口长度 + 固定 hop size”的滚动处理模型。
5. 丢包补点默认使用 `零阶保持`，同时保留扩展为“零填充”的接口/配置位。
6. `pack_num` 严格校验只对“自动上传波形包”作为一等能力实现。
7. 主动读模式单独保留，但其“严格 `pack_num` 丢包检测”能力取决于是否能从该模式下拿到序号字段；若拿不到，则需在文档和日志中明确说明“主动读模式无法做到协议级 `pack_num` 校验”。

### 范围决策

本次计划内：

- 重构 DSP 时间基准与滚动窗口。
- 为协议层增加自动上传波形包头解析。
- 为自动上传模式加入 `pack_num` 丢包检测和补点。
- 为主动读模式保留现有链路，但把时间基准改为固定 `Fs`。

本次计划外：

- 不在计划阶段承诺改动设备端协议行为。
- 不在没有证据的情况下捏造“主动读模式的 `pack_num` 字段位置”。
- 不在本次计划里重新设计全部 GUI，仅修改必要的波形时间轴来源。

## Proposed Changes

### A. 配置与数据模型

#### 目标

把 DSP 的窗口、步长、显示时基和丢包补点策略显式配置化，并从“秒”迁移到“样本点”优先。

#### 变更文件

- [config/settings.py](file:///Users/auv_user/coding/fangkong_adc/config/settings.py)
- [config/default_config.yaml](file:///Users/auv_user/coding/fangkong_adc/config/default_config.yaml)
- [core/models.py](file:///Users/auv_user/coding/fangkong_adc/core/models.py)

#### 计划内容

1. 在 `DspConfig` 中新增样本级参数，例如：
   - `window_size_samples`
   - `hop_size_samples`
   - `packet_loss_fill_mode`
2. 在 `Runtime` 或 `GUI` 相关配置中新增示波器显示参数，例如：
   - `scope_total_window_ms`
   - `scope_div_ms`
3. 在配置中新增传输模式枚举，例如：
   - `transport_mode: poll | auto_upload`
4. 在 `ProcessingStats` 中区分：
   - `configured_sample_rate_hz`
   - `packet_loss_count`
   - `filled_sample_count`
5. 删除或弃用“驱动数学链路”的 `effective_sample_rate_hz`；如果保留，也只能作为纯诊断字段，不允许参与 DSP/波形时间轴。

### B. 固定窗口滚动 DSP 架构

#### 目标

从“来一批算一批”改为“环形缓冲 + 固定窗口 + 固定步长”。

#### 变更文件

- [core/ring_buffer.py](file:///Users/auv_user/coding/fangkong_adc/core/ring_buffer.py)
- [core/pipeline.py](file:///Users/auv_user/coding/fangkong_adc/core/pipeline.py)
- [core/dsp.py](file:///Users/auv_user/coding/fangkong_adc/core/dsp.py)
- [core/lockin.py](file:///Users/auv_user/coding/fangkong_adc/core/lockin.py)

#### 计划内容

1. 将当前 `RingBuffer` 扩展或替换为更明确的“固定窗口滚动缓存”语义：
   - 容量至少覆盖 `window_size_samples`
   - 提供 `append(samples)` 和 `latest_window(window_size)` 能力
2. 在 `PipelineWorker` 中维护一个 `pending_since_last_dsp` 计数器。
3. 只有当新写入样本数累计达到 `hop_size_samples` 时，才触发一次 FFT 和 Lock-in。
4. FFT 和 Lock-in 计算时只取固定长度 `window_size_samples` 的数组。
5. 参考时间轴与参考正弦波统一使用：

```python
t = np.arange(window_size_samples) / Fs
```

6. `Fs` 的来源：
   - 主动读模式：`config.device.sample_rate_hz`
   - 自动上传模式：优先包头 `ad_fre`
7. 移除 `pipeline.py` 中任何通过本地时间估计采样率、再反向喂给 DSP 的逻辑。

### C. 波形时间轴改造

#### 目标

波形显示也必须遵守“样本序号 / Fs”，不使用本地时间来拉伸/压缩 X 轴。

#### 变更文件

- [gui/plot_widgets.py](file:///Users/auv_user/coding/fangkong_adc/gui/plot_widgets.py)
- [gui/main_window.py](file:///Users/auv_user/coding/fangkong_adc/gui/main_window.py)

#### 计划内容

1. `WaveformPlot.update()` 的 X 轴只使用：

```python
x = np.arange(point_count) / Fs
```

再映射为毫秒显示。

2. GUI 拉取频率 `QTimer` 只控制“多久刷新一次屏幕”，不能控制波形数学时间轴。
3. 示波器显示默认改为：
   - 总窗宽 `200ms`
   - 每格 `20ms`
   - 栅格固定
4. 若后续需要多档时基，则扩展为配置项或 GUI 可选项，但第一版先固定 `20ms/格`。

### D. 主动读模式的严格数学收敛

#### 目标

在不切换传输模式的情况下，先保证主动读链路的 FFT/Lock-in/波形都数学自洽。

#### 变更文件

- [core/acquisition_controller.py](file:///Users/auv_user/coding/fangkong_adc/core/acquisition_controller.py)
- [protocol/adc_decoder.py](file:///Users/auv_user/coding/fangkong_adc/protocol/adc_decoder.py)
- [core/pipeline.py](file:///Users/auv_user/coding/fangkong_adc/core/pipeline.py)

#### 计划内容

1. 保留当前“读寄存器 `19`”链路。
2. 保留当前按激活通道重组的 [adc_decoder.py](file:///Users/auv_user/coding/fangkong_adc/protocol/adc_decoder.py) 能力。
3. 对主动读模式：
   - 时间基准严格固定为配置 `Fs`
   - 不再根据运行时吞吐去调整 `sample_rate_hz`
4. 读流泵仍可使用本地时钟做“请求发送调度”，但该时钟不参与 DSP 或显示时间基准。
5. 若主动读模式确实拿不到 `pack_num`，则：
   - 在日志里提示“当前模式无协议级包序号，无法执行严格 `pack_num` 丢包检测”
   - 计划保留接口，为后续协议确认后再接入

### E. 自动上传模式与 `pack_num` 丢包检测

#### 目标

为严格满足第 3 条要求，新增自动上传波形包解析能力，并在该模式下实施 `pack_num` 校验与补点。

#### 变更文件

- [protocol/constants.py](file:///Users/auv_user/coding/fangkong_adc/protocol/constants.py)
- [protocol/frames.py](file:///Users/auv_user/coding/fangkong_adc/protocol/frames.py)
- [protocol/stream_parser.py](file:///Users/auv_user/coding/fangkong_adc/protocol/stream_parser.py)
- 新增建议文件：`protocol/upload_frames.py` 或并入 `frames.py`
- [core/pipeline.py](file:///Users/auv_user/coding/fangkong_adc/core/pipeline.py)
- [core/acquisition_controller.py](file:///Users/auv_user/coding/fangkong_adc/core/acquisition_controller.py)

#### 计划内容

1. 引入自动上传波形包 `52` 字节头的数据结构：
   - `pack_type`
   - `pack_code`
   - `pack_num`
   - `event_num`
   - `time`
   - `ad_fre`
   - `channel_en`
   - `sec_sync`
   - `data_type`
   - `data_num`
2. 在解析器中增加“自动上传包头模式”的切包逻辑，与当前 `16` 字节寄存器应答解析并存，不互相破坏。
3. 为自动上传模式维护 `last_pack_num`。
4. 若检测到 `pack_num` 不连续：
   - 记录 `warning`
   - 计算缺失包数/缺失样本数
   - 依据 `packet_loss_fill_mode` 执行补点
5. 默认补点策略为 `零阶保持`：
   - 缺失段用上一个样本值复制
   - 保持 `FFT/Lock-in` 窗口长度和相位推进连续
6. 预留 `zero_padding` 分支，但默认不启用。

### F. 文档与测试收敛

#### 目标

使 README、技术契约和测试与新架构一致，避免再次引入“用本地时间估计采样率”的路径。

#### 变更文件

- [README.md](file:///Users/auv_user/coding/fangkong_adc/README.md)
- [tests/test_dsp_lockin.py](file:///Users/auv_user/coding/fangkong_adc/tests/test_dsp_lockin.py)
- [tests/test_adc_decoder.py](file:///Users/auv_user/coding/fangkong_adc/tests/test_adc_decoder.py)
- 新增建议文件：
  - `tests/test_pipeline_windowing.py`
  - `tests/test_packet_loss_fill.py`
  - `tests/test_upload_header_parser.py`

#### 计划内容

1. 更新 README 中“有效采样率自适应收敛”的表述，改为：
   - 数学链路信任硬件 `Fs`
   - 本地时间只做调度和诊断
2. 新增测试覆盖：
   - 固定窗口/固定 hop 触发
   - `np.arange(window_size) / Fs` 的参考时间基准
   - `pack_num` 连续与断裂场景
   - `零阶保持` 补点后的窗口长度与样本连续性
3. 若主动读模式无 `pack_num`，在 README 明确说明其限制。

## Verification Steps

### 1. 静态验证

1. 检查代码中 `FFT`、`Lock-in`、`WaveformPlot` 是否完全不再使用本地时间推导 `Fs`。
2. 搜索关键字确认不存在以下违规路径：
   - `time.time()` / `time.monotonic()` 参与 `sample_rate_hz` 更新
   - “单位时间样本数 -> 有效采样率 -> 喂给 DSP/波形”

### 2. 单元测试

需要至少覆盖以下场景：

1. 固定 `Fs=2000`、窗口 `4000`、步长 `200` 时：
   - 每推进 `200` 点触发一次 FFT/Lock-in
   - 未满窗口前不触发正式结果
2. 丢包补点：
   - `pack_num` 连续时不告警
   - `pack_num` 跳变时产生 warning
   - `零阶保持` 后窗口长度保持正确
3. GUI 波形轴：
   - `20ms/格`
   - 总窗宽 `200ms`
   - X 轴完全由样本序号和 `Fs` 生成

### 3. 真机/联调验证

#### 主动读模式

1. 配置 `Fs=2000`
2. 连续运行 60 秒
3. 人为改变输入信号，观察波形响应延迟是否仅受窗口显示与 UI 刷新影响，而不再累计漂移
4. FFT 主峰是否稳定锁定在实际信号频率附近
5. Lock-in 幅值/相位在稳定输入下是否连续

#### 自动上传模式

1. 打开 `Ad_Mode=3`
2. 解析上传波形包头
3. 验证 `pack_num` 连续性
4. 人为制造丢包或跳号样例，确认：
   - warning 正确输出
   - `零阶保持` 补点生效
   - FFT/Lock-in 不因窗口长度破坏而崩溃

## Implementation Order

建议按以下顺序实施：

1. 先重构 `pipeline.py`，移除“本地时间估计采样率”对 DSP 与波形的影响。
2. 再把滚动窗口与固定 hop 架构落地。
3. 然后调整 GUI 波形时间轴到严格 `Fs` 模式与 `20ms/格`。
4. 再新增自动上传包头解析与 `pack_num` 丢包检测。
5. 最后统一补测试和 README。

## Success Criteria

满足以下条件时，视为本次架构调整完成：

1. `FFT`、`Lock-in`、波形 X 轴的 `Δt` 完全由硬件 `Fs` 决定。
2. 代码中不存在任何“用本地时间估算采样率再驱动算法”的路径。
3. DSP 使用固定长度滚动窗口和固定 hop size。
4. 自动上传模式可以解析 `pack_num` 并执行丢包检测。
5. 丢包默认使用 `零阶保持` 补点。
6. 主动读模式与自动上传模式的能力边界在代码和 README 中都被明确写清楚。
