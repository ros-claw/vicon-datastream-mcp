# 配置指南

## OpenClaw 配置

### 方法 1: 配置文件

编辑 `~/.openclaw/openclaw.json`:

```json
{
  "mcpServers": {
    "vicon": {
      "command": "python",
      "args": [
        "D:/workspace/rosclaw/mcp/vicon-datastream-mcp/vicon_datastream_mcp.py"
      ],
      "env": {
        "VICON_HOST": "localhost:801",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

### 方法 2: Control UI 配置

在 OpenClaw Control UI 的 MCP Server 管理界面：

- **Name**: `vicon`
- **Command**: `python`
- **Arguments**: `D:\workspace\rosclaw\mcp\vicon-datastream-mcp\vicon_datastream_mcp.py`
- **Environment**: 
  - `VICON_HOST=localhost:801`
  - `PYTHONIOENCODING=utf-8`

## Claude Desktop 配置

### Windows

编辑 `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "vicon": {
      "command": "python",
      "args": ["D:/workspace/rosclaw/mcp/vicon-datastream-mcp/vicon_datastream_mcp.py"],
      "env": {"VICON_HOST": "localhost:801"}
    }
  }
}
```

### macOS

编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "vicon": {
      "command": "python3",
      "args": ["/path/to/vicon-datastream-mcp/vicon_datastream_mcp.py"],
      "env": {"VICON_HOST": "localhost:801"}
    }
  }
}
```

## 环境变量

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `VICON_HOST` | Vicon Server 地址 | `localhost:801` |
| `VICON_SDK_PATH` | SDK 路径（可选） | 自动检测 |
| `PYTHONIOENCODING` | 编码 | `utf-8` |

## 多服务器配置

如果你有多套 Vicon 系统：

```json
{
  "mcpServers": {
    "vicon-lab1": {
      "command": "python",
      "args": [".../vicon_datastream_mcp.py"],
      "env": {"VICON_HOST": "192.168.1.10:801"}
    },
    "vicon-lab2": {
      "command": "python",
      "args": [".../vicon_datastream_mcp.py"],
      "env": {"VICON_HOST": "192.168.1.20:801"}
    }
  }
}
```

## 故障排除

### SDK 未找到

```
⚠️ 警告: 无法加载 Vicon DataStream SDK。
```

**解决**:
```powershell
cd "D:\Program Files\Vicon\DataStream SDK\Win64\Python"
pip install -e vicon_dssdk
```

或者设置环境变量：
```powershell
$env:VICON_SDK_PATH = "D:\Program Files\Vicon\DataStream SDK\Win64\Python"
```

### 连接失败

```json
{"success": false, "error": "ClientConnectionFailed"}
```

**检查清单**:
1. Vicon Tracker/Nexus/Evoke 是否已启动？
2. DataStream 是否已启用？（在 Vicon 软件设置中）
3. 网络连接是否正常？
4. 防火墙是否阻止了端口 801？

### 数据为空

确保流程正确：
1. `vicon_connect` - 连接
2. `vicon_enable_data("segment")` - 启用数据
3. `vicon_get_frame()` - 刷新帧
4. `vicon_get_segment(...)` - 获取数据

## 性能优化

### 选择合适的流模式

| 场景 | 推荐模式 | 说明 |
|------|----------|------|
| 远程连接 | ClientPull | 节省带宽 |
| 本地实时控制 | ServerPush | 最低延迟 |
| 一般用途 | ClientPullPreFetch | 平衡 |

### 只启用需要的数据

```python
# 只需要运动学数据
vicon_enable_data("segment")

# 不需要时不启用
# vicon_enable_data("centroid")  # 减少带宽
# vicon_enable_data("camera_calibration")  # 除非需要相机标定
```

## 坐标系配置

### 常用软件映射

```python
# Unity (左手 Y-up)
vicon_set_axis_mapping("Forward", "Up", "Right")

# Unreal (左手 Z-up)  
vicon_set_axis_mapping("Forward", "Right", "Up")

# ROS (右手 Z-up)
vicon_set_axis_mapping("Forward", "Left", "Up")

# Blender (右手 Z-up, Y-forward)
vicon_set_axis_mapping("Right", "Forward", "Up")
```

## 安全配置

### 生产环境

- 使用防火墙限制端口 801 访问
- 考虑使用 Multicast 减少网络负载
- 定期备份 Vicon 校准数据
