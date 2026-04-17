# Windows 系统完整安装与配置指南

## 目录
1. [Vicon 软件安装](#1-vicon-软件安装)
2. [DataStream SDK 目录结构说明](#2-datastream-sdk-目录结构说明)
3. [OpenClaw 连接配置](#3-openclaw-连接配置)
4. [端口说明与配置](#4-端口说明与配置)
5. [实时数据获取教程](#5-实时数据获取教程)
6. [故障排除](#6-故障排除)

---

## 1. Vicon 软件安装

### 1.1 下载
访问 Vicon 官网下载页面：
- **网址**: https://www.vicon.com/software/datastream-sdk/
- **下载文件**: `ViconDataStreamSDK_1.12_145507h.zip` (或更新版本)

### 1.2 安装步骤

#### 步骤 1: 解压 SDK
```powershell
# 解压到 D:\Program Files\Vicon\
Expand-Archive -Path "ViconDataStreamSDK_1.12_145507h.zip" -DestinationPath "D:\Program Files\Vicon\"
```

#### 步骤 2: 安装 Python SDK
```powershell
# 进入 Python SDK 目录
cd "D:\Program Files\Vicon\DataStream SDK\Win64\Python"

# 以 Editable 模式安装（推荐）
pip install -e vicon_dssdk

# 验证安装
python -c "from vicon_dssdk import ViconDataStream; print('✅ SDK 安装成功')"
```

> **注意**: 如果 pip 安装失败，可以直接将 `vicon_dssdk` 文件夹复制到你的 Python 项目目录中使用。

---

## 2. DataStream SDK 目录结构说明

安装后目录结构：

```
D:\Program Files\Vicon\DataStream SDK\
├── Documentation\
│   └── Vicon DataStream SDK Manual.pdf      # 完整 API 文档
│
├── Win64\
│   ├── Python\
│   │   └── vicon_dssdk\                     # Python SDK 主目录
│   │       ├── __init__.py
│   │       ├── CoreClient.py               # 底层 C++ 绑定
│   │       ├── CoreClient3.py              # Python 3 版本
│   │       ├── ViconDataStream.py          # 主要客户端类
│   │       └── ...
│   │
│   ├── C\                                   # C 语言头文件和库
│   │   ├── CClient.h
│   │   ├── ViconDataStreamSDK_C.dll
│   │   └── ...
│   │
│   ├── CPP\                                 # C++ 头文件和库
│   │   ├── DataStreamClient.h
│   │   ├── ViconDataStreamSDK_CPP.dll
│   │   └── ...
│   │
│   ├── dotNET\                              # .NET/C# 支持
│   │   ├── ViconDataStreamSDK_DotNET.dll
│   │   └── ...
│   │
│   └── MATLAB\                              # MATLAB 支持
│       └── ...
│
└── x86\                                     # 32位版本（旧系统）
    └── ...
```

### 关键文件说明

| 文件 | 用途 |
|------|------|
| `ViconDataStream.py` | Python 主要接口，包含 `Client` 类 |
| `CoreClient.pyd` | C++ 编写的 Python 扩展模块（高性能） |
| `DataStreamClient.h` | C++ 头文件，定义所有 API |
| `ViconDataStreamSDK_CPP.dll` | C++ 运行时库 |

---

## 3. OpenClaw 连接配置

### 3.1 配置文件位置

**Windows 配置文件路径**:
```
C:\Users\<你的用户名>\.openclaw\openclaw.json
```

或使用 Control UI 配置。

### 3.2 基础配置（单服务器）

编辑 `openclaw.json`:

```json
{
  "mcpServers": {
    "vicon": {
      "command": "python",
      "args": [
        "D:\\workspace\\rosclaw\\mcp\\vicon-datastream-mcp\\vicon_datastream_mcp.py"
      ],
      "env": {
        "VICON_HOST": "192.168.20.24:801",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

### 3.3 多服务器配置示例

如果你有多台 Vicon 服务器：

```json
{
  "mcpServers": {
    "vicon-main": {
      "command": "python",
      "args": ["D:/workspace/rosclaw/mcp/vicon-datastream-mcp/vicon_datastream_mcp.py"],
      "env": {
        "VICON_HOST": "192.168.20.24:801"
      }
    },
    "vicon-lab2": {
      "command": "python",
      "args": ["D:/workspace/rosclaw/mcp/vicon-datastream-mcp/vicon_datastream_mcp.py"],
      "env": {
        "VICON_HOST": "192.168.20.25:801"
      }
    }
  }
}
```

### 3.4 配置环境变量（可选）

如果 SDK 不在默认位置，添加环境变量：

```powershell
# 临时设置（当前 PowerShell 会话）
$env:VICON_SDK_PATH = "D:\Program Files\Vicon\DataStream SDK\Win64\Python"

# 永久设置（系统环境变量）
[Environment]::SetEnvironmentVariable("VICON_SDK_PATH", "D:\Program Files\Vicon\DataStream SDK\Win64\Python", "User")
```

---

## 4. 端口说明与配置

根据你的 Vicon Tracker 配置，各端口用途如下：

### 端口对照表

| 端口 | 名称 | 用途 | 协议 | MCP 使用 |
|------|------|------|------|----------|
| **801** | DataStream Live/Offline Port | 主要数据流端口（推荐） | TCP | ✅ 主要连接端口 |
| **804** | DataStream Low Latency Port | 低延迟数据流 | TCP | ✅ 替代端口 |
| **8802** | DataStream Live Port | 实时数据（旧版） | TCP | ⚠️ 兼容模式 |
| **7000** | OSC Port | Open Sound Control | UDP | ❌ MCP 不使用 |
| **51001** | UDP Port | 自定义 UDP 数据 | UDP | ❌ MCP 不使用 |

### 推荐的端口配置

#### 配置 A: 标准模式（推荐）
```json
{
  "env": {
    "VICON_HOST": "192.168.20.24:801"
  }
}
```

#### 配置 B: 低延迟模式
```json
{
  "env": {
    "VICON_HOST": "192.168.20.24:804"
  }
}
```

### 在 Vicon Tracker 中启用 DataStream

1. 打开 **Vicon Tracker** 软件
2. 进入 `System` → `Preferences`
3. 找到 **DataStream** 选项卡
4. 勾选 **Enable DataStream Server**
5. 设置端口为 **801**（或你需要的端口）
6. 点击 **Apply**

---

## 5. 实时数据获取教程

### 5.1 连接与基础数据获取

```python
# 自然语言指令示例：

"连接到 Vicon 服务器 192.168.20.24:801"
→ 执行: vicon_connect(host="192.168.20.24:801")

"获取当前所有主体列表"
→ 执行: vicon_get_subjects()

"启用运动学段数据并刷新帧"
→ 执行: 
  vicon_enable_data("segment")
  vicon_get_frame()
```

### 5.2 获取特定主体数据

```python
# 假设要获取名为 "Colin" 的动捕演员的骨盆数据

"获取 Colin 的骨盆位置和旋转"
→ 执行: vicon_get_segment(subject_name="Colin", segment_name="Pelvis")

返回 JSON 示例:
{
  "success": true,
  "subject": "Colin",
  "segment": "Pelvis",
  "global": {
    "translation": {"x": -522.3, "y": -1.6, "z": 1119.1},
    "rotation_euler_xyz": {"x": 0.1, "y": -0.2, "z": 0.05},
    "rotation_quaternion": {"x": 0.0, "y": 0.1, "z": 0.0, "w": 0.995},
    "rotation_matrix": [[...], [...], [...]],
    "occluded": false
  },
  "local": { /* 相对父段的数据 */ },
  "hierarchy": {
    "parent": "Hips",
    "children": ["Spine", "LeftUpperLeg", "RightUpperLeg"]
  }
}
```

### 5.3 实时数据流模式

```python
# 设置低延迟推送模式（适合实时控制）

"设置服务器推送模式"
→ 执行: vicon_set_stream_mode("ServerPush")

"开始持续获取骨盆位置"
→ 循环执行:
    vicon_get_frame()
    vicon_get_segment("Colin", "Pelvis")
    # 延迟 10ms (100Hz)
```

### 5.4 力板数据获取

```python
"获取力板数据（全局坐标）"
→ 执行: vicon_get_force_plates()

"获取力板本地坐标数据"
→ 执行: vicon_get_force_plates(include_local=true)
```

### 5.5 标记点数据获取

```python
"获取 Colin 的所有标记点"
→ 执行: vicon_get_markers(subject_name="Colin")

"获取所有未标记的反射点"
→ 执行: vicon_get_unlabeled_markers()
```

### 5.6 坐标系配置

```python
"设置 Unity 坐标系（Y-up）"
→ 执行: vicon_set_axis_mapping("Forward", "Up", "Right")

"设置 Unreal 坐标系（Z-up）"
→ 执行: vicon_set_axis_mapping("Forward", "Right", "Up")

"设置 ROS 坐标系"
→ 执行: vicon_set_axis_mapping("Forward", "Left", "Up")
```

---

## 6. 故障排除

### 6.1 常见问题

#### ❌ "Vicon SDK 不可用"
**原因**: Python 找不到 vicon_dssdk 模块

**解决**:
```powershell
# 方法 1: 重新安装 SDK
cd "D:\Program Files\Vicon\DataStream SDK\Win64\Python"
pip install -e vicon_dssdk --force-reinstall

# 方法 2: 手动添加路径
$env:PYTHONPATH = "D:\Program Files\Vicon\DataStream SDK\Win64\Python;$env:PYTHONPATH"
```

#### ❌ "ClientConnectionFailed"
**原因**: 无法连接到 Vicon 服务器

**检查清单**:
1. ✅ Vicon Tracker 软件是否已启动？
2. ✅ DataStream Server 是否已启用？（System → Preferences → DataStream）
3. ✅ IP 地址 192.168.20.24 是否正确？
4. ✅ 防火墙是否允许端口 801？
5. ✅ 网络连接是否正常？

**测试连接**:
```powershell
# 测试网络连通性
Test-NetConnection -ComputerName 192.168.20.24 -Port 801
```

#### ❌ 数据为空或全为 0
**原因**: 数据类型未启用或主体未激活

**解决**:
1. 启用数据类型: `vicon_enable_data("segment")`
2. 确保调用了 `vicon_get_frame()`
3. 检查 Vicon Tracker 中主体是否已校准并激活

#### ❌ "模块找不到 DLL"
**原因**: C++ 运行时库缺失

**解决**:
安装 Visual C++ Redistributable:
- https://aka.ms/vs/17/release/vc_redist.x64.exe

### 6.2 性能优化

#### 降低延迟
```python
# 使用 ServerPush 模式
vicon_set_stream_mode("ServerPush")

# 只启用需要的数据类型
vicon_enable_data("segment")  # 不需要 marker 时禁用
```

#### 减少带宽
```python
# 使用轻量级段数据
vicon_enable_data("lightweight_segment")

# 增加缓冲区大小（减少丢帧）
vicon_set_buffer_size(5)
```

---

## 7. 完整示例脚本

```python
#!/usr/bin/env python3
"""Windows 系统 Vicon MCP 使用示例"""

import asyncio
import json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def vicon_demo():
    # 配置 MCP Server
    server_params = StdioServerParameters(
        command="python",
        args=[r"D:\workspace\rosclaw\mcp\vicon-datastream-mcp\vicon_datastream_mcp.py"],
        env={
            "VICON_HOST": "192.168.20.24:801",
            "VICON_SDK_PATH": r"D:\Program Files\Vicon\DataStream SDK\Win64\Python"
        }
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # 1. 连接
            print("1. 连接到 Vicon...")
            result = await session.call_tool("vicon_connect", {
                "host": "192.168.20.24:801"
            })
            print(result.content[0].text)
            
            # 2. 启用数据
            print("\n2. 启用运动学段数据...")
            await session.call_tool("vicon_enable_data", {"data_type": "segment"})
            
            # 3. 设置坐标系
            print("\n3. 设置 Unity 坐标系...")
            await session.call_tool("vicon_set_axis_mapping", {
                "x": "Forward", "y": "Up", "z": "Right"
            })
            
            # 4. 获取主体列表
            print("\n4. 获取主体列表...")
            result = await session.call_tool("vicon_get_subjects", {})
            subjects = json.loads(result.content[0].text)
            print(f"   发现 {subjects['subject_count']} 个主体")
            
            # 5. 实时获取数据
            if subjects.get("subjects"):
                subject = subjects["subjects"][0]
                print(f"\n5. 获取 {subject['name']} 的 {subject['root_segment']} 数据...")
                
                for i in range(10):  # 获取 10 帧
                    await session.call_tool("vicon_get_frame", {})
                    result = await session.call_tool("vicon_get_segment", {
                        "subject_name": subject["name"],
                        "segment_name": subject["root_segment"]
                    })
                    data = json.loads(result.content[0].text)
                    
                    if data.get("success"):
                        pos = data["global"]["translation"]
                        print(f"   Frame {i}: X={pos['x']:.1f}, Y={pos['y']:.1f}, Z={pos['z']:.1f} mm")
                    
                    await asyncio.sleep(0.01)  # 100Hz
            
            # 6. 断开
            print("\n6. 断开连接...")
            await session.call_tool("vicon_disconnect", {})

if __name__ == "__main__":
    asyncio.run(vicon_demo())
```

---

**最后更新**: 2026-04-18
