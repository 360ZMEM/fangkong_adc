# SK2301 以太网 ADC 采集与实时处理软件

基于 `PySide6 + pyqtgraph` 的跨平台以太网数据采集与实时处理上位机，用于连接 `SK2301` 硬件 ADC，完成多通道磁传感器交流信号采集、实时波形显示、FFT 频谱分析和 `50Hz` 数字锁相放大特征提取。

本文档是当前仓库的统一入口，覆盖以下内容：

- 仓库目标与当前状态
- 目录结构与模块职责
- 环境准备与运行命令
- 配置文件规则
- 联调命令与真机诊断结论
- 当前已知行为、调试历史和注意事项

## 1. 项目目标

本项目面向 `SK2301` 一体化信号采集控制模块，通过其透明以太网协议实现：

- 连接设备并配置采样参数
- 按激活通道持续读取 ADC 数据
- 实时显示波形和频谱
- 对 `50Hz` 目标频率执行数字锁相放大
- 在后台保存原始数据与特征结果

当前重点场景：

- 默认启用 `CH0 / CH1 / CH2`
- 默认采样率 `2000Hz`
- 当前量程按现场要求固定为 `±10V`，软件不主动修改量程
- 优先保证“不断流、不积压、界面不卡死”

## 2. 当前状态

当前仓库已经具备一个可运行、可测试、可联调的首版系统，包含：

- `PySide6` 图形界面
- `pyqtgraph` 实时波形与频谱绘制
- `TCP` 协议收发与粘包/半包处理
- 生产者-消费者线程模型
- `FFT` 与 `50Hz Lock-in`
- 本地 `Mock SK2301` 模拟服务器
- 单元测试与真机探测脚本

当前默认真机地址：

- `192.168.1.198:1600`

当前默认九参数标定：

- `calibration_profiles/20260705T144937_magnetometer_9param.json`

## 3. 仓库结构

```text
fangkong_adc/
├── config/        配置模型、读写与默认配置
├── core/          采集控制、队列、DSP、存储、状态模型
├── gui/           PySide6 界面与 pyqtgraph 绘图
├── network/       TCP 客户端、网络线程、重连状态机、Mock 设备
├── protocol/      FKPro 协议封包、滑动缓冲、ADC 解码
├── scripts/       联调辅助脚本
├── tests/         单元测试与无真机验证
├── 参考文档/       协议/设备手册、协议截图转写、技术契约总结
├── main.py        GUI 程序入口
└── README.md      当前文档
```

## 4. 模块职责

### `config/`

- `settings.py`
  - 定义 `AppConfig` 及各配置段数据结构
  - 对采样率、通道范围、队列策略等做基础校验
- `config_manager.py`
  - 负责 `default_config.yaml` 与 `user_config.yaml` 的加载、合并与保存

### `protocol/`

- `constants.py`
  - 存放报文头、命令码、寄存器地址常量
- `frames.py`
  - 只负责 FKPro 报文打包/解析
- `stream_parser.py`
  - 负责 TCP 连续字节流的滑动缓冲切包
- `adc_decoder.py`
  - 包含两种解码方式：
  - `decode_24bit_samples()`：旧的固定通道整帧解释
  - `ActiveChannelDecoder`：当前正式使用，按激活通道序列跨包重组样本

### `network/`

- `tcp_client.py`
  - 基础 TCP 连接、发送、接收
- `network_worker.py`
  - 生产者线程，只做 `recv()` 和入队
- `reconnect_state.py`
  - 状态枚举
- `mock_sk2301_server.py`
  - 无真机时的本地模拟设备

### `core/`

- `acquisition_controller.py`
  - 系统主控制器
  - 负责连接、设参、启动、停止、自动模式、请求-响应同步、读流泵
- `pipeline.py`
  - 消费者线程
  - 从原始队列取数据，切包、解码、FFT、Lock-in、产出快照
- `ring_buffer.py`
  - 波形缓存
- `dsp.py`
  - FFT
- `lockin.py`
  - 软件参考数字锁相放大
- `storage.py`
  - 保存 `NPZ` 和 `CSV`
- `models.py`
  - 运行时快照与状态模型

### `gui/`

- `main_window.py`
  - 主窗口与定时刷新
- `plot_widgets.py`
  - 波形图与频谱图
- `control_panel.py`
  - 连接、设参、启动、停止、保存配置
- `channel_panel.py`
  - 动态通道选择
- `status_panel.py`
  - 状态、速率、丢包、解析错误、告警、Lock-in 信息

### `scripts/`

- `live_probe.py`
  - 真机联调用探测脚本
  - 用于抓取 `read_stream` 响应、分析通道序列、核对每包样本数与节奏

### `tests/`

- 协议封包测试
- 滑动缓冲测试
- ADC 解码测试
- DSP/Lock-in 测试
- 队列策略测试
- 配置系统测试
- Mock 服务器端到端测试
- 读流字节对齐测试

## 5. 核心架构

本项目严格采用“网络接收”和“解析处理”分离的生产者-消费者模型：

```text
SK2301 TCP Stream
    ↓
TcpClient.recv()
    ↓
NetworkWorker
    ↓ raw_queue (queue.Queue, drop_oldest)
PipelineWorker
    ↓
SlidingByteBuffer
    ↓
ActiveChannelDecoder
    ↓
RingBuffer / FFT / Lock-in / Storage
    ↓
LatestSnapshot
    ↓
QTimer (主线程 30Hz)
    ↓
PySide6 + pyqtgraph GUI
```

关键设计原则：

- 网络线程只做 `recv()`，不做重计算
- 消费线程负责切包、解码、DSP
- GUI 主线程只拉取快照，不直接参与采集解析
- 队列满时执行 `drop_oldest`
- 数学时间轴只使用“样本序号 / 硬件 `Fs`”，不使用本地时间反推 `Δt`

### 5.1 数学时间基准

当前实现中需要严格区分两类时间：

- 数学时间
  - 用于波形 X 轴、`FFT` 频率轴、`Lock-in` 参考相位
  - 唯一合法来源是 `sample_index / sample_rate_hz`
- 诊断时间
  - 用于日志时间戳、文件命名、网络调度、速率统计和延迟观测
  - 可以使用 `time.time()` 或 `time.monotonic()`

重要约束：

- `QTimer` 只决定 GUI 多久刷新一次，不决定波形时间轴
- `time.time()` / `time.monotonic()` 不能参与 `FFT`、`Lock-in`、波形 X 轴的 `Δt` 定义

### 5.2 传输模式能力边界

- `poll`
  - 主机主动读寄存器 `19`
  - 数学主链路同样严格信任配置采样率 `device.sample_rate_hz`
  - 当前响应头不含 `pack_num`，因此无法做协议级丢包检测
- `auto_upload`
  - 设备发送 `52` 字节波形包头
  - `sample_rate_hz` 优先取上传头中的硬件上报值
  - 支持 `pack_num` 连续性校验与补点
  - 默认补点策略为 `zero_order_hold`

## 6. 已确认的真机结论

以下结论来自对 `192.168.1.198` 的实际联调，不是推测：

### 6.1 当前真机返回的是激活通道，不是固定 16 通道全回

在默认 `CH0 / CH1 / CH2` 模式下，`read_stream` 返回的 `channel_id` 只有：

```text
[0, 1, 2]
```

这意味着当前设备工作在“只回激活通道”的模式下。

### 6.2 旧版时间轴变慢的根因

旧逻辑错误地把当前数据按 `16` 通道整帧解释，导致：

- 每包 `1408` 字节只被解释成 `21~22` 个时间点
- 真实应为 `3` 通道，每包应还原约 `117` 个时间点
- 结果表现为：1 秒真实时间，图上只移动约 `0.3` 秒

### 6.3 `1408` 不适合当前 3 通道模式

每个样本点占 `4` 字节，每个时间点包含 `3` 个激活通道，因此：

- 单时间点字节数 = `3 * 4 = 12`
- `1408 % 12 != 0`

这会导致跨包边界发生通道相位轮转，增加对齐复杂度。

因此当前默认值已改为：

- `read_bytes_per_request: 1404`

因为：

- `1404 = 117 * 12`

### 6.4 当前链路不是以太网带宽瓶颈

真机探测结果大致为：

- 单包周期约 `58ms`
- 包速率约 `15.4 Hz`
- 每包 `1404` 字节
- 吞吐量约 `21.6 KB/s`

这远低于 `USB2.0 转以太网` 的极限能力，因此当前问题不是链路带宽不够，而是数据解释与请求节奏不匹配。

## 7. 已完成的关键修复

### UI / 可视化

- 波形图固定 `200ms` 时间窗，默认 `20ms/格`，便于直接观察 `50Hz`
- 频谱图固定 `X` 轴范围
- 三通道显式指定不同颜色
- 左侧状态区宽度固定，避免 `Lock-in` 文本长度变化引发布局抖动

### 协议 / 解码

- 增加 `ActiveChannelDecoder`
- 支持激活通道顺序重组
- 支持跨包残样本保留
- 避免在 3 通道模式下仍按 16 通道整帧解释

### 读流策略

- 默认 `read_bytes_per_request` 改为 `1404`
- 启动采集时自动按激活通道字节数对齐请求长度
- 读流泵从“每 `1ms` 狂发一次”改为按样本产生速率节流

### DSP / 数学时间基准

- `FFT`、`Lock-in`、波形 X 轴统一按硬件 `Fs` 定义时间基准
- `PipelineWorker` 使用固定长度环形缓冲区
- 默认 DSP 窗口为 `4000` 点，默认 hop 为 `200` 点
- 自动上传模式支持 `pack_num` 丢包检测
- 协议级缺包默认使用 `zero_order_hold` 补点

## 8. 环境准备

推荐 Python 版本：

- `Python 3.9+`

安装依赖：

```bash
python3 -m pip install -r requirements.txt
```

依赖清单见：

- [requirements.txt](file:///Users/auv_user/coding/fangkong_adc/requirements.txt)

## 9. 常用运行命令

### 9.1 启动 GUI 上位机

```bash
python3 main.py
```

### 9.2 运行单元测试

```bash
python3 -m pytest tests
```

### 9.3 真机探测脚本

该脚本默认读取 `config/default_config.yaml + config/user_config.yaml` 中的地址，
也可以通过命令行临时覆盖 `--host/--port`：

```bash
PYTHONPATH=. python3 scripts/live_probe.py
PYTHONPATH=. python3 scripts/live_probe.py --host 192.168.1.198 --port 1600
```

### 9.4 只安装依赖

```bash
python3 -m pip install -r requirements.txt
```

### 9.5 在无真机环境下验证

主要依靠测试：

```bash
python3 -m pytest tests
```

如需进一步使用本地模拟设备，可参考：

- [mock_sk2301_server.py](file:///Users/auv_user/coding/fangkong_adc/network/mock_sk2301_server.py)

## 10. GUI 操作流程

### Debug 交互模式

启动 GUI 后按以下顺序操作：

1. 点击“连接”
2. 点击“设参”
3. 点击“启动采集”
4. 观察状态栏、波形、频谱、Lock-in
5. 结束时点击“停止采集”

### AUV 自动化模式

配置文件中设置：

```yaml
runtime:
  auto_start: true
```

启动后程序会：

- 自动重试连接设备
- 自动设参
- 自动启动采集
- 持续进行处理与本地存盘

如果还希望窗口隐藏/最小化，可继续配置：

```yaml
runtime:
  auto_start: true
  hide_window_on_auto_start: true
```

## 11. 配置系统

程序启动时按如下顺序加载配置：

1. `config/default_config.yaml`
2. `config/user_config.yaml`，如果存在则覆盖默认配置

其中：

- 默认设备地址仍保持 `192.168.1.198`
- 默认会自动加载 `calibration_profiles/20260705T144937_magnetometer_9param.json`
- 相对路径按本 submodule 根目录解析，不依赖 GUI 当前工作目录

保存配置时由 GUI “保存配置”按钮写入：

- `config/user_config.yaml`

配置加载入口见：

- [config_manager.py](file:///Users/auv_user/coding/fangkong_adc/config/config_manager.py)

## 12. 默认配置说明

当前默认配置文件：

- [default_config.yaml](file:///Users/auv_user/coding/fangkong_adc/config/default_config.yaml)

关键字段如下：

```yaml
network:
  host: "192.168.1.198"
  port: 1600

calibration:
  enabled: true
  profile_path: "calibration_profiles/20260705T144937_magnetometer_9param.json"

device:
  sample_rate_hz: 2000
  active_channels: [0, 1, 2]
  total_channels: 16
  adc_bits: 24
  voltage_range: "+/-10V"
  configure_voltage_range: false
  read_bytes_per_request: 1404

runtime:
  auto_start: false
  hide_window_on_auto_start: false
  ui_refresh_hz: 30
  transport_mode: "poll"
  scope_total_window_ms: 200
  scope_div_ms: 20

dsp:
  window_size_samples: 4000
  hop_size_samples: 200
  lockin_frequency_hz: 50.0
  packet_loss_fill_mode: "zero_order_hold"
```

### 字段解释

- `network.host`
  - 设备 IP
- `network.port`
  - 设备 TCP 端口，当前为 `1600`
- `device.sample_rate_hz`
  - 采样率，当前建议保持 `2000`
- `device.active_channels`
  - 当前启用通道列表
- `device.total_channels`
  - 设备物理总通道数，当前固定 `16`
- `device.voltage_range`
  - 当前仅作为记录值，默认 `±10V`
- `device.configure_voltage_range`
  - 是否由软件主动改变量程
  - 当前推荐保持 `false`
- `device.read_bytes_per_request`
  - 单次读流请求的目标字节数
  - 当前 3 通道模式推荐 `1404`
- `runtime.auto_start`
  - 是否自动启动后台模式
- `runtime.ui_refresh_hz`
  - GUI 刷新率，当前默认 `30Hz`
- `runtime.transport_mode`
  - 传输模式，当前支持 `poll` 与 `auto_upload`
- `runtime.scope_total_window_ms`
  - 示波器总窗宽，默认 `200ms`
- `runtime.scope_div_ms`
  - 示波器每格时间，默认 `20ms`
- `dsp.window_size_samples`
  - FFT / Lock-in 固定滚动窗口长度
- `dsp.hop_size_samples`
  - 每累计多少新样本触发一次 DSP
- `dsp.packet_loss_fill_mode`
  - 自动上传模式下的协议级缺包补点策略

## 13. 当前推荐现场参数

对于目前的真实硬件联调，建议使用：

```yaml
device:
  sample_rate_hz: 2000
  active_channels: [0, 1, 2]
  configure_voltage_range: false
  read_bytes_per_request: 1404
```

不建议当前现场配置：

- `sample_rate_hz: 10000`
  - 过高，容易制造数据积压并降低整体稳定性
- `read_bytes_per_request: 1408`
  - 对 3 通道模式不整除，会增加跨包对齐复杂度

## 14. 数据与存储

程序运行时可将数据写入：

- `data/raw/.../*.npz`
- `data/features/.../*.csv`

相关配置：

```yaml
storage:
  enabled: true
  root_dir: "data"
  raw_npz_enabled: true
  feature_csv_enabled: true
  flush_interval_sec: 5.0
```

## 15. 状态栏指标说明

当前 GUI 状态栏包含：

- 模式
- 当前连接/采集状态
- 原始队列长度
- 丢包数量
- 解析错误数
- 通道错位数
- 接收速率
- DSP 延迟
- 告警信息
- Lock-in 结果

当前“丢包”相关指标分为两层：

- 网络层
  - `dropped_chunks`
  - 表示原始队列满后执行了 `drop_oldest`
- 协议层
  - `packet_loss_count`
  - 仅在 `auto_upload` 模式下依据 `pack_num` 检测
  - 当前默认用 `zero_order_hold` 补点，并统计 `filled_sample_count`

如果出现以下情况，优先怀疑采集链路：

- 队列持续上涨
- `dropped_chunks` 增加
- `channel_mismatch_count` 增加
- 接收速率明显低于预期

## 16. 已知限制

- 当前锁相参考为 `software`，尚未接入硬件参考源
- 当前主联调对象是 `CH0 / CH1 / CH2`
- GUI 运行在 `PySide6`
- 绘图固定使用 `pyqtgraph`，禁止切回 `matplotlib`
- `poll` 模式当前没有协议级 `pack_num` 字段，因此无法执行严格的协议级丢包检测
- `auto_upload` 模式具备协议级缺包检测能力，但仍需以设备端真实包头为最终协议依据

## 17. 常见问题

### 17.1 为什么时间轴会变慢？

如果再次出现此问题，优先检查：

1. 是否误把当前流按 16 通道解释
2. `read_bytes_per_request` 是否被改回 `1408`
3. 激活通道是否仍是 `[0, 1, 2]`
4. 队列是否持续积压
5. `auto_upload` 模式下是否出现了 `pack_num` 缺包或补点告警

当前实现不会再用本地系统时间去反推“有效采样率”；数学主链路默认严格信任硬件 `Fs`。

### 17.2 为什么三通道颜色看起来一样？

当前代码已显式设置不同颜色；如果再次出现，请检查：

- 是否运行了旧进程
- 是否没有重启 GUI

### 17.3 为什么连接成功但状态显示“设备初始化中”？

这是因为寄存器 `Init_Status(0)` 返回 `0`。当前程序会继续连接，但该状态说明设备未报告“初始化完成”。

### 17.4 为什么采集中不能切换通道？

这是当前有意限制。为保证数据链路稳定，采集中禁止切换通道，需先停止采集再切换。

## 18. 参考文档

仓库内已经整理了与本项目强相关的文档：

- [FKPro协议示例转写与校正.md](file:///Users/auv_user/coding/fangkong_adc/参考文档/FKPro协议示例转写与校正.md)
- [SK2301与FKPro技术契约总结.md](file:///Users/auv_user/coding/fangkong_adc/参考文档/SK2301与FKPro技术契约总结.md)
- `参考文档/FKPro通讯协议及编程说明书_V1.2.pdf`
- `参考文档/SK2301一体化信号采集控制模块产品说明书_V2.0.pdf`

建议后续开发优先以这两份 Markdown 契约为准，再结合原始 PDF 交叉核对。

## 19. 当前建议的开发/联调顺序

1. 安装依赖
2. 检查 `config/default_config.yaml`
3. 启动 GUI 并连接真机
4. 先做 `连接 -> 设参 -> 启动`
5. 观察时间轴、队列、解析错误、Lock-in
6. 如有异常，运行 `scripts/live_probe.py`
7. 修改后运行测试，确保不回归

## 20. 快速命令总表

```bash
# 安装依赖
python3 -m pip install -r requirements.txt

# 启动 GUI
python3 main.py

# 运行测试
python3 -m pytest tests

# 真机探测
PYTHONPATH=. python3 scripts/live_probe.py
```

## 21. 维护说明

以后如果继续联调或修改协议层，请优先同步更新本 README 中以下部分：

- “已确认的真机结论”
- “已完成的关键修复”
- “默认配置说明”
- “当前推荐现场参数”
- “常见问题”

这样即使后续在不同路径、不同对话或不同执行代理之间切换，也能快速恢复完整上下文。
