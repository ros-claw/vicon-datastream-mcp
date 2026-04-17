# 架构详解

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              应用层 (AI 助手)                                 │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐                   │
│  │  Claude   │  │ OpenClaw  │  │ 其他 MCP  │  │ 自定义客户端 │                   │
│  │  Desktop  │  │           │  │   客户端  │  │           │                   │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘                   │
│        │              │              │              │                          │
│        └──────────────┴──────────────┴──────────────┘                          │
│                         │                                                     │
│                         ▼ stdio / SSE                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                              MCP 协议层                                       │
│                         JSON-RPC 2.0                                        │
│                                                                               │
│  Tools:              Resources:                                               │
│  - vicon_connect     - vicon://status                                       │
│  - vicon_get_frame   - vicon://subjects                                     │
│  - vicon_get_segment - vicon://markers/all                                   │
│  ...                                                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                         ▼                                                     │
│                    vicon_datastream_mcp.py                                  │
│                    (MCP Server - Python)                                      │
│                                                                               │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐                 │
│  │   Connection    │  │  Data Manager   │  │   Coordinator   │                 │
│  │    Manager      │  │                 │  │                 │                 │
│  │  - Connect      │  │  - Enable Types │  │  - Frame Sync   │                 │
│  │  - Disconnect   │  │  - Buffer Mgmt  │  │  - Error Handle │                 │
│  │  - Reconnect    │  │  - Stream Mode  │  │  - Rate Control │                 │
│  └────────┬────────┘  └────────┬────────┘  └─────────────────┘                 │
│           │                  │                                                │
│           └──────────────────┘                                                │
│                      │                                                        │
│                      ▼ DLL / .pyd                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                           Vicon SDK 层                                       │
│                      vicon_dssdk (Python)                                    │
│                           │                                                  │
│                      CoreClient.pyd                                          │
│                           │                                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                           网络层                                             │
│                      TCP Socket (端口 801)                                  │
│                           │                                                  │
│                           ▼                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                         Vicon 软件层                                      ││
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                      ││
│  │  │ Vicon       │  │   Vicon     │  │   Vicon     │                      ││
│  │  │ Tracker     │  │   Nexus     │  │   Evoke     │                      ││
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                      ││
│  │         │                │                │                               ││
│  │         └────────────────┴────────────────┘                               ││
│  │                          │                                              ││
│  │                   DataStream Server                                       ││
│  │                          │                                              ││
│  │         ┌────────────────┼────────────────┐                               ││
│  │         ▼                ▼                ▼                               ││
│  │    ┌─────────┐     ┌─────────┐     ┌─────────┐                           ││
│  │    │ Camera  │ ... │ Camera  │     │ Force   │                           ││
│  │    │  Array  │     │  Array  │     │ Plates  │                           ││
│  │    └─────────┘     └─────────┘     └─────────┘                           ││
│  │                                                                           ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

## MCP Server 内部结构

### 1. ViconClientWrapper

核心封装类，管理所有 Vicon 交互：

```python
class ViconClientWrapper:
    - connect(host, timeout)      # 建立连接
    - disconnect()              # 断开连接
    - enable_data_type(type)    # 启用数据类型
    - set_stream_mode(mode)     # 设置流模式
    - get_frame()               # 刷新帧数据
    - get_segment(subject, seg) # 获取段数据
    - get_markers()             # 获取标记点
    - get_force_plates()        # 获取力板数据
    - set_axis_mapping(x,y,z)   # 设置坐标系
```

### 2. 数据流生命周期

```
初始化
   │
   ▼
connect() ───────────────┐
   │                      │
   ▼                      │
enable_data_type()       │
   │                      │
   ▼                      │
set_stream_mode()        │
   │                      │
   ▼                      │
┌──────────────────┐     │
│  数据获取循环     │◄────┘
│                  │
│  get_frame()     │
│      │           │
│      ▼           │
│  get_segment()   │
│  get_markers()   │
│  ...             │
└──────────────────┘
   │
   ▼
disconnect()
```

### 3. 并发模型

```
┌─────────────────────────────────────┐
│         asyncio 事件循环             │
│                                     │
│  ┌─────────────┐  ┌─────────────┐  │
│  │  MCP Tool   │  │  MCP Tool   │  │
│  │   Handler   │  │   Handler   │  │
│  └──────┬──────┘  └──────┬──────┘  │
│         │                │          │
│         └────────────────┘          │
│                  │                   │
│         ┌─────────────┐            │
│         │ ThreadPool  │            │
│         │  Executor   │            │
│         └──────┬──────┘            │
│                │                   │
│         ┌──────┴──────┐            │
│         ▼             ▼            │
│    Vicon SDK     Vicon SDK        │
│    (阻塞)        (阻塞)            │
└─────────────────────────────────────┘
```

- **MCP 层**: 异步处理 (asyncio)
- **Vicon SDK**: 同步阻塞操作 → 在线程池中执行
- **线程安全**: Vicon SDK 的 Client 实例是线程安全的

### 4. 数据转换流程

```
Vicon SDK 原始数据
      │
      ▼
┌─────────────────┐
│  Vicon Python   │  doubleArray → Python tuple
│     SDK         │  Enum → Python enum/str
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ ViconClient     │  结构化数据封装
│  Wrapper        │  mm → mm (保持)
│                 │  rad → rad (保持)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  JSON 序列化     │  Dict → JSON string
│                 │  ensure_ascii=False
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  MCP Response   │  TextContent(text=json_string)
│                 │
└─────────────────┘
```

## 坐标系处理

### 默认坐标系 (Vicon)

```
        Z (Up)
        │
        │    X (Forward)
        │   ╱
        │  ╱
        │ ╱
        └────────── Y (Left)
       Origin
```

- 右手坐标系
- 单位: mm (位置), rad (角度)

### 坐标系映射实现

```python
# 用户请求: Unity 坐标系 (Y-up)
set_axis_mapping("Forward", "Up", "Right")

# 内部转换为 Vicon SDK 调用
ViconDataStream.Client.AxisMapping.EForward  # X
ViconDataStream.Client.AxisMapping.EUp       # Y
ViconDataStream.Client.AxisMapping.ERight    # Z

# SDK 会自动处理坐标变换
```

## 流模式实现

### 三种模式对比

```
ClientPull Mode:
┌────────┐          ┌────────┐
│ Client │ ──请求──>│ Server │
│        │ <─帧数据─│        │
└────────┘          └────────┘
   延迟: ~16ms (取决于请求频率)

ClientPullPreFetch:
┌────────┐          ┌────────┐
│ Client │ ──请求──>│ Server │
│        │ <─预缓存─│ (buffer)│
└────────┘          └────────┘
   延迟: ~8ms

ServerPush:
┌────────┐          ┌────────┐
│ Client │ <────────│ Server │
│ (buffer)│ ←─持续推送─│        │
└────────┘          └────────┘
   延迟: ~2-4ms
```

## 错误处理策略

```
┌─────────────────────────────────────────┐
│              错误分类                    │
├─────────────────────────────────────────┤
│ 连接错误                                │
│   - InvalidHostName                    │
│   - ClientConnectionFailed             │
│   → 重试3次，指数退避                   │
├─────────────────────────────────────────┤
│ 运行时错误                              │
│   - NotConnected                       │
│   - NoFrame                            │
│   → 返回错误信息，不中断连接            │
├─────────────────────────────────────────┤
│ 数据错误                                │
│   - InvalidSubjectName                 │
│   - InvalidSegmentName                 │
│   → 提示用户检查名称                    │
└─────────────────────────────────────────┘
```

## 性能指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 连接建立 | < 500ms | TCP 握手 + SDK 初始化 |
| 单次调用延迟 | < 5ms | Tool 调用往返 |
| 帧数据获取 | < 1ms | 从 SDK 缓冲区读取 |
| 内存占用 | < 100MB | 客户端实例 + 缓冲 |
| 支持帧率 | 120Hz+ | 受限于 Vicon 相机 |

## 扩展点

### 添加新的 Tool

```python
@mcp.tool()
async def vicon_get_camera_calibration(camera_id: str) -> str:
    """
    获取相机标定数据
    
    在 ViconClientWrapper 中添加:
    - get_camera_calibration(camera_id)
    
    处理步骤:
    1. 检查 camera_calibration 数据类型已启用
    2. 调用 SDK GetCameraGlobalTranslation/Rotation
    3. 封装为 JSON 返回
    """
    result = await vicon.get_camera_calibration(camera_id)
    return json.dumps(result)
```

### 添加新的 Resource

```python
@mcp.resource("vicon://cameras")
async def get_vicon_cameras() -> str:
    """获取相机列表"""
    result = await vicon.get_camera_names()
    return json.dumps(result)
```

## 调试工具

### 日志级别

```python
logging.basicConfig(level=logging.DEBUG)  # 详细调试
logging.basicConfig(level=logging.INFO)   # 正常运行
logging.basicConfig(level=logging.WARNING) # 仅警告和错误
```

### 手动测试

```bash
# 启动 Server
python vicon_datastream_mcp.py

# 在另一个终端使用 MCP Inspector
npx @anthropic-ai/mcp-inspector
```
