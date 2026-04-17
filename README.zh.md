# Vicon DataStream MCP Server

[![MCP](https://img.shields.io/badge/MCP-Protocol-blue)](https://modelcontextprotocol.io/)
[![Python](https://img.shields.io/badge/Python-3.10+-green)](https://www.python.org/)
[![Vicon](https://img.shields.io/badge/Vicon-Tracker/Nexus/Evoke-orange)](https://www.vicon.com/)
[![SDK](https://img.shields.io/badge/SDK-1.12.145507h-red)](./docs/Vicon%20DataStream%20SDK%20Manual.pdf)

基于 [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) 的 **完整功能** Vicon 动作捕捉数据流服务器。

**📚 SDK 参考文档**: [Vicon DataStream SDK Manual.pdf](./docs/Vicon%20DataStream%20SDK%20Manual.pdf)  
**📦 基于 SDK**: Vicon DataStream SDK v1.12.145507h (Win64 Python)

**✨ 100% 功能完整**：实现 Vicon DataStream SDK 全部 47+ 个核心功能。

## 项目结构

```
vicon-datastream-mcp/
├── src/                    # MCP Server 源码
│   ├── __init__.py        # Python 包初始化
│   └── mcp_server.py      # 主入口 (Vicon DataStream MCP 完整实现)
├── prompts/               # 提示词模板
│   ├── system.txt         # 系统提示词
│   └── examples/          # 示例提示词
│       └── basic_usage.txt
├── docs/                  # 文档目录
│   ├── WINDOWS_SETUP.md   # Windows 安装指南
│   ├── CONFIG.md          # 配置详情
│   ├── ARCHITECTURE.md    # 架构说明
│   └── Vicon DataStream SDK Manual.pdf  # 📚 SDK v1.12.145507h 官方文档
├── config.json            # MCP 客户端配置
├── requirements.txt       # Python 依赖
└── README.zh.md           # 本文件
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 安装 Vicon SDK

```powershell
cd "D:\Program Files\Vicon\DataStream SDK\Win64\Python"
pip install -e vicon_dssdk
```

### 3. 运行 MCP Server

```bash
# stdio 模式（默认，用于 OpenClaw/Claude Desktop）
python -m src.mcp_server

# SSE 模式
python -m src.mcp_server --transport sse --port 8000
```

### 4. 配置 MCP 客户端

将 `config.json` 的内容合并到你的 MCP 客户端配置中：

- **Claude Desktop**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Cline**: VS Code 设置中的 MCP 配置

## 功能特性

### 连接管理
- ✅ TCP 直连（端口 801）
- ✅ Multicast 组播连接
- ✅ 可配置缓冲区大小

### 运动学数据
- **全局姿态**：位置 + 4种旋转格式（欧拉角/四元数/矩阵/螺旋角）
- **本地姿态**：相对父段变换
- **静态偏移**：PRE-POSITION/PRE-ORIENTATION
- **段层次结构**：父段、子段、根段

### 标记点追踪
- Labeled Markers（主体+父段+位置+遮挡）
- Unlabeled Markers（原始反射点）
- Marker Ray 追踪

### 生物力学设备
- **力板数据**：全局/本地坐标，力向量、力矩、压力中心
- **眼动仪**：眼睛位置 + 注视向量
- **通用设备**：EMG 等

### 相机数据
- 相机列表（ID、类型、分辨率）
- 相机标定参数（位姿 + 镜头参数）
- 质心数据

### 高级配置
- 3种流模式（ClientPull/ClientPullPreFetch/ServerPush）
- 主体过滤
- 坐标系映射（Unity/Unreal/ROS 兼容）
- 延迟分析

## 可用工具

### 连接管理 (5个)
| 工具 | 说明 |
|------|------|
| `vicon_connect` | TCP 连接 |
| `vicon_connect_multicast` | 组播连接 |
| `vicon_disconnect` | 断开连接 |
| `vicon_set_buffer_size` | 设置缓冲区 |

### 数据配置 (4个)
| 工具 | 说明 |
|------|------|
| `vicon_enable_data` | 启用数据类型 |
| `vicon_disable_data` | 禁用数据类型 |
| `vicon_set_stream_mode` | 设置流模式 |
| `vicon_get_frame` | 获取帧 |

### 主体和段 (5个)
| 工具 | 说明 |
|------|------|
| `vicon_get_subjects` | 主体列表 |
| `vicon_get_segment` | 单段数据 |
| `vicon_get_all_segments` | 所有段 |
| `vicon_add_subject_filter` | 添加过滤 |
| `vicon_clear_subject_filter` | 清除过滤 |

### 标记点 (2个)
| 工具 | 说明 |
|------|------|
| `vicon_get_markers` | 标记点数据 |
| `vicon_get_unlabeled_markers` | 未标记点 |

### 设备和力板 (4个)
| 工具 | 说明 |
|------|------|
| `vicon_get_devices` | 设备列表 |
| `vicon_get_force_plates` | 力板数据 |
| `vicon_get_analog_voltage` | 模拟电压 |
| `vicon_set_apex_feedback` | 触觉反馈 |

### 眼动仪 (2个)
| 工具 | 说明 |
|------|------|
| `vicon_get_eye_trackers` | 眼动仪列表 |
| `vicon_get_eye_tracker` | 位置+注视向量 |

### 相机 (3个)
| 工具 | 说明 |
|------|------|
| `vicon_get_cameras` | 相机列表 |
| `vicon_get_centroids` | 质心数据 |
| `vicon_get_camera_calibration` | 标定参数 |

### 坐标系 (3个)
| 工具 | 说明 |
|------|------|
| `vicon_set_axis_mapping` | 设置坐标系 |
| `vicon_get_axis_mapping` | 获取坐标系 |
| `vicon_get_server_orientation` | 服务器方向 |

## 坐标系快速参考

| 软件 | X | Y | Z | 调用 |
|-----|---|---|---|------|
| Vicon 默认 | Forward | Left | Up | (默认) |
| Unity | Forward | Up | Right | `vicon_set_axis_mapping("Forward", "Up", "Right")` |
| Unreal | Forward | Right | Up | `vicon_set_axis_mapping("Forward", "Right", "Up")` |
| ROS | Forward | Left | Up | `vicon_set_axis_mapping("Forward", "Left", "Up")` |

## 环境变量

- `VICON_HOST`: 默认 Vicon Server 地址 (默认: localhost:801)
- `VICON_SDK_PATH`: SDK 自定义路径

## SDK 版本信息

- **SDK 版本**: Vicon DataStream SDK v1.12.145507h
- **SDK 文档**: [docs/Vicon DataStream SDK Manual.pdf](./docs/Vicon%20DataStream%20SDK%20Manual.pdf)
- **支持平台**: Windows (Win64), Linux, macOS
- **Python 版本**: 3.10+

## 端口说明

| 端口 | 适用场景 |
|------|----------|
| 801 | DataStream Live/Offline（推荐） |
| 804 | DataStream Low Latency |
| 8802 | DataStream Live（旧版兼容） |

## 许可证

Apache License 2.0
