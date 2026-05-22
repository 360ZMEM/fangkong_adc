# 计划：API 审计与文档化

## 摘要

审查当前上位机是否做到了「GUI 仅是显示前端、核心功能完全 API 化」，并输出一份完整的 API 参考文档，同时做少量重构使项目可以作为一个独立 Python 模块被外部代码或 headless 脚本直接导入使用。

---

## 当前状态分析

### 已实现的解耦

| 层级 | 模块 | 是否依赖 GUI | 是否可 headless |
|------|------|:---:|:---:|
| 配置 | `config/settings.py`, `config/config_manager.py` | 否 | 是 |
| 协议 | `protocol/constants.py`, `protocol/frames.py`, `protocol/stream_parser.py`, `protocol/adc_decoder.py` | 否 | 是 |
| 网络 | `network/tcp_client.py`, `network/network_worker.py`, `network/reconnect_state.py` | 否 | 是 |
| 核心 | `core/models.py`, `core/ring_buffer.py`, `core/dsp.py`, `core/lockin.py`, `core/storage.py`, `core/pipeline.py`, `core/acquisition_controller.py` | 否 | 是 |
| GUI | `gui/main_window.py`, `gui/plot_widgets.py`, `gui/control_panel.py`, `gui/channel_panel.py`, `gui/status_panel.py` | 是 | — |

**结论：核心功能已 100% 与 GUI 分离。** `AcquisitionController` 是对外的唯一门面（Facade），GUI 层仅通过 `controller.get_latest_snapshot()` 拉数据、通过 `controller.connect()` / `controller.configure_device()` / `controller.start_acquisition()` 等方法下发命令。

### 需要补充的内容

1. **包入口缺失**：项目根目录没有 `__init__.py`，无法通过 `import fangkong_adc` 作为包使用。
2. **缺少 headless 入口**：目前唯一入口 `main.py` 硬依赖 `PySide6`。需要一个不依赖 GUI 的入口/示例。
3. **缺少 API 参考文档**：各模块的对外接口没有集中文档描述。

---

## 计划内容

### 任务 1：添加顶层包入口

- 在项目根目录创建 `fangkong_adc/__init__.py`（或直接在根 `__init__.py`），将关键公开类和函数统一导出。
- **决定**：鉴于当前项目结构是"平铺子包"（`config/`、`core/`、`protocol/` 等直接在根目录），而不是嵌套在一个顶层包目录内，采用最小侵入方案：
  - 新建 `api.py`（根目录），作为"对外统一 API 入口文件"，负责 re-export 所有公开符号。
  - 不改变现有目录结构，避免破坏 `import config.xxx` 等已有路径。

**`api.py` 导出清单**（基于探索结果）：

```python
# --- 配置 ---
from config.config_manager import load_config, load_merged_config, save_config, validate_config
from config.settings import (
    AppConfig, NetworkConfig, DeviceConfig, RuntimeConfig,
    QueueConfig, DspConfig, StorageConfig, SUPPORTED_SAMPLE_RATES,
)

# --- 控制器 (Facade) ---
from core.acquisition_controller import AcquisitionController

# --- 数据模型 ---
from core.models import (
    LatestSnapshot, LockinResult, FftResult, ProcessingStats,
)
from network.reconnect_state import ConnectionState

# --- DSP 算法 (可独立调用) ---
from core.dsp import compute_fft
from core.lockin import compute_lockin

# --- 协议工具 (底层) ---
from protocol.constants import *
from protocol.frames import (
    build_read_registers, build_write_registers,
    build_read_stream, build_write_stream,
    parse_header, FkProHeader,
)
from protocol.stream_parser import SlidingByteBuffer
from protocol.adc_decoder import (
    ActiveChannelDecoder, decode_24bit_samples, DecodedAdcData, DecodeStats,
)

# --- 网络 ---
from network.tcp_client import TcpClient, TcpEndpoint, TcpClientError
from network.network_worker import NetworkWorker, NetworkWorkerStats

# --- 存储 ---
from core.storage import DataStorage
from core.ring_buffer import RingBuffer
```

### 任务 2：创建 headless 入口示例

新建 `headless.py`（根目录），示范在无 GUI 环境下完整使用采集 API：

```
加载配置 → 创建控制器 → 连接 → 设参 → 采集 N 秒 → 获取快照 → 停止 → 输出
```

这也作为 API 文档中 "Quick Start (Headless)" 的活代码引用。

### 任务 3：编写 `docs/api_reference.md`

完整 API 参考文档，结构：

```
1. 概述 & 架构图 (Mermaid)
2. Quick Start
   - GUI 模式
   - Headless 模式
3. 配置系统
   - AppConfig 各字段
   - 加载/保存/校验
4. AcquisitionController API (核心门面)
   - 生命周期方法
   - 状态查询
   - 参数修改
5. 数据模型
   - LatestSnapshot
   - LockinResult / FftResult / ProcessingStats
   - ConnectionState
6. DSP 算法
   - compute_fft
   - compute_lockin
7. 协议层
   - 帧构建 / 帧解析
   - SlidingByteBuffer
   - ActiveChannelDecoder
8. 网络层
   - TcpClient
   - NetworkWorker
9. 存储层
   - DataStorage
   - RingBuffer
10. 线程模型与数据流图
```

### 任务 4：验证 headless 可导入性

- `python -c "from api import AcquisitionController, load_merged_config"` 无需 PySide6 即可通过。
- 在 `tests/` 中补一个简单的 `test_headless_import.py` 确认。

---

## 假设与决定

| # | 决定 | 理由 |
|---|------|------|
| 1 | 不将项目改成单根包（如 `fangkong_adc/config/...`） | 当前平铺结构已稳定运行，且 `main.py`、`scripts/`、`tests/` 均依赖此路径；迁移风险高收益低 |
| 2 | 使用 `api.py` 作为统一导出入口 | 最小侵入，不影响已有导入路径；外部使用者只需 `from api import ...` |
| 3 | `headless.py` 作为示范入口 | 让用户直接看到"不依赖 GUI 如何使用"，并可作为 AUV 部署脚本模板 |
| 4 | 文档放 `docs/api_reference.md` | 保持 `参考文档/` 目录专门存放硬件协议参考，`docs/` 放软件 API 文档 |

---

## 验证步骤

1. `python -c "from api import AcquisitionController, load_merged_config, compute_fft, compute_lockin"` → 成功，无 PySide6 导入。
2. `python headless.py --help` → 显示用法（不需要真实设备即可验证导入链）。
3. `python -m pytest tests/test_headless_import.py` → 通过。
4. 查看 `docs/api_reference.md` 无空章节、无遗漏公开 API。

---

## 文件变更清单

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `api.py` | 统一 API 导出入口 |
| 新建 | `headless.py` | Headless 入口示例 |
| 新建 | `docs/api_reference.md` | 完整 API 参考文档 |
| 新建 | `tests/test_headless_import.py` | 导入链验证测试 |
| 不动 | `main.py`, `config/`, `core/`, `protocol/`, `network/`, `gui/` | 不需修改，已满足解耦 |
