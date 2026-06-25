#!/usr/bin/env python3
"""
Vicon DataStream MCP Server
============================

基于 MCP (Model Context Protocol) 的 Vicon 动作捕捉数据流服务器。
通过 stdio 或 SSE 与 OpenClaw/Claude 通信，提供对 Vicon 动捕系统的标准化访问接口。

功能:
- 连接/断开 Vicon DataStream Server (支持 TCP 和 Multicast)
- 获取实时的运动学数据 (段/关节位置和旋转)
- 获取标记点数据 (labeled/unlabeled/marker rays)
- 获取设备数据 (力板、EMG、眼动仪等)
- 获取相机数据 (质心、相机标定)
- 配置数据流参数 (帧率、坐标系、流模式、缓冲区大小)
- 主体过滤
- 延迟分析
- 时间码获取

运行方式:
    python src/mcp_server.py [--transport stdio|sse] [--port 8000]

环境变量:
    VICON_HOST: 默认 Vicon Server 地址 (默认: localhost:801)

依赖:
    pip install mcp vicon_dssdk

作者: AI Assistant
版本: 1.0.0
"""

import asyncio
import json
import logging
import sys
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Union
from enum import Enum

from mcp.server import Server
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent
from mcp.server.models import InitializationOptions
from anyio import ClosedResourceError

# =============================================================================
# SDK 导入处理
# =============================================================================

VICON_SDK_AVAILABLE = False
ViconDataStream = None

SDK_PATHS = [
    # 标准安装路径
    Path(r"D:\Program Files\Vicon\DataStream SDK\Win64\Python"),
    Path(r"C:\Program Files\Vicon\DataStream SDK\Win64\Python"),
    Path(r"D:\Program Files (x86)\Vicon\DataStream SDK\Win64\Python"),
    Path(r"C:\Program Files (x86)\Vicon\DataStream SDK\Win64\Python"),
    # 自定义路径
    Path(os.environ.get("VICON_SDK_PATH", "")) if os.environ.get("VICON_SDK_PATH") else None,
]

# 尝试导入
try:
    from vicon_dssdk import ViconDataStream
    VICON_SDK_AVAILABLE = True
except ImportError:
    for sdk_path in SDK_PATHS:
        if sdk_path and sdk_path.exists():
            sys.path.insert(0, str(sdk_path))
            try:
                from vicon_dssdk import ViconDataStream
                VICON_SDK_AVAILABLE = True
                break
            except ImportError:
                continue

if not VICON_SDK_AVAILABLE:
    print("⚠️ 警告: 无法加载 Vicon DataStream SDK。将使用模拟模式运行。", file=sys.stderr)
    print(r"   请安装 SDK: cd 'D:\Program Files\Vicon\DataStream SDK\Win64\Python' && pip install -e vicon_dssdk", file=sys.stderr)


# =============================================================================
# 日志配置
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("vicon_mcp")


# =============================================================================
# 数据模型
# =============================================================================

@dataclass
class ViconConnection:
    """Vicon 连接状态管理"""
    client: Optional[Any] = None
    host: str = "localhost:801"
    is_connected: bool = False
    enabled_data_types: Dict[str, bool] = field(default_factory=lambda: {
        "segment": False,
        "lightweight_segment": False,
        "marker": False,
        "unlabeled_marker": False,
        "marker_ray": False,
        "device": False,
        "centroid": False,
        "camera_calibration": False,
    })
    stream_mode: str = "ClientPull"
    frame_count: int = 0
    multicast_enabled: bool = False


# =============================================================================
# Vicon 客户端封装 (完整版)
# =============================================================================

class ViconClientWrapper:
    """Vicon 客户端的完整封装 - 实现所有 SDK 功能"""
    
    def __init__(self):
        self.conn = ViconConnection()
        
    # -------------------------------------------------------------------------
    # 连接管理
    # -------------------------------------------------------------------------
    
    async def connect(self, host: str = None, timeout_ms: int = 5000) -> Dict[str, Any]:
        """连接到 Vicon Server (TCP)"""
        if not VICON_SDK_AVAILABLE:
            return {"success": False, "error": "Vicon SDK 不可用"}
        
        if self.conn.is_connected:
            return {"success": True, "message": "已经连接", "host": self.conn.host}
        
        try:
            self.conn.client = ViconDataStream.Client()
            self.conn.client.SetConnectionTimeout(timeout_ms)
            
            host = host or os.getenv("VICON_HOST", "localhost:801")
            self.conn.host = host
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.conn.client.Connect, host)
            
            self.conn.is_connected = True
            version = self.conn.client.GetVersion()
            
            logger.info(f"✅ 已连接到 Vicon Server: {host}, SDK版本: {version}")
            
            return {
                "success": True,
                "host": host,
                "sdk_version": {"major": version[0], "minor": version[1], "point": version[2]},
                "message": f"成功连接到 {host}"
            }
            
        except Exception as e:
            self.conn.client = None
            self.conn.is_connected = False
            logger.error(f"❌ 连接失败: {e}")
            return {"success": False, "error": str(e), "host": host}
    
    async def connect_to_multicast(self, local_ip: str, multicast_ip: str = "224.0.0.0") -> Dict[str, Any]:
        """通过 Multicast 连接到 Vicon Server"""
        if not VICON_SDK_AVAILABLE:
            return {"success": False, "error": "Vicon SDK 不可用"}
        
        if self.conn.is_connected:
            return {"success": False, "error": "已连接到 TCP，请先断开"}
        
        try:
            self.conn.client = ViconDataStream.Client()
            self.conn.host = f"multicast:{multicast_ip}@{local_ip}"
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, 
                self.conn.client.ConnectToMulticast, 
                local_ip, 
                multicast_ip
            )
            
            self.conn.is_connected = True
            self.conn.multicast_enabled = True
            version = self.conn.client.GetVersion()
            
            logger.info(f"✅ 已通过 Multicast 连接: {local_ip} -> {multicast_ip}")
            
            return {
                "success": True,
                "local_ip": local_ip,
                "multicast_ip": multicast_ip,
                "sdk_version": {"major": version[0], "minor": version[1], "point": version[2]}
            }
            
        except Exception as e:
            self.conn.client = None
            self.conn.is_connected = False
            return {"success": False, "error": str(e)}
    
    async def start_transmitting_multicast(self, server_ip: str, multicast_ip: str) -> Dict[str, Any]:
        """开始通过 Multicast 转发数据（Server 端操作）"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self.conn.client.StartTransmittingMulticast,
                server_ip,
                multicast_ip
            )
            return {
                "success": True,
                "server_ip": server_ip,
                "multicast_ip": multicast_ip,
                "message": f"开始 Multicast 转发到 {multicast_ip}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def stop_transmitting_multicast(self) -> Dict[str, Any]:
        """停止 Multicast 转发"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self.conn.client.StopTransmittingMulticast
            )
            return {"success": True, "message": "已停止 Multicast 转发"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def disconnect(self) -> Dict[str, Any]:
        """断开连接"""
        if not self.conn.is_connected or not self.conn.client:
            return {"success": True, "message": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.conn.client.Disconnect)
            self.conn.is_connected = False
            self.conn.client = None
            self.conn.multicast_enabled = False
            logger.info("🔌 已断开连接")
            return {"success": True, "message": "已断开连接"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def set_buffer_size(self, size: int) -> Dict[str, Any]:
        """设置缓冲区大小"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.conn.client.SetBufferSize, size)
            return {"success": True, "buffer_size": size}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # 数据类型管理
    # -------------------------------------------------------------------------
    
    async def enable_data_type(self, data_type: str) -> Dict[str, Any]:
        """启用特定数据类型"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        data_type_map = {
            "segment": "EnableSegmentData",
            "lightweight_segment": "EnableLightweightSegmentData",
            "marker": "EnableMarkerData",
            "unlabeled_marker": "EnableUnlabeledMarkerData",
            "marker_ray": "EnableMarkerRayData",
            "device": "EnableDeviceData",
            "centroid": "EnableCentroidData",
            "camera_calibration": "EnableCameraCalibrationData",
        }
        
        disable_map = {
            "segment": "DisableSegmentData",
            "lightweight_segment": "DisableLightweightSegmentData",
            "marker": "DisableMarkerData",
            "unlabeled_marker": "DisableUnlabeledMarkerData",
            "marker_ray": "DisableMarkerRayData",
            "device": "DisableDeviceData",
            "centroid": "DisableCentroidData",
            "camera_calibration": "DisableCameraCalibrationData",
        }
        
        if data_type not in data_type_map:
            return {
                "success": False,
                "error": f"未知数据类型: {data_type}",
                "available_types": list(data_type_map.keys())
            }
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, 
                getattr(self.conn.client, data_type_map[data_type])
            )
            self.conn.enabled_data_types[data_type] = True
            return {"success": True, "data_type": data_type, "enabled": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def disable_data_type(self, data_type: str) -> Dict[str, Any]:
        """禁用特定数据类型"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        disable_map = {
            "segment": "DisableSegmentData",
            "marker": "DisableMarkerData",
            "unlabeled_marker": "DisableUnlabeledMarkerData",
            "marker_ray": "DisableMarkerRayData",
            "device": "DisableDeviceData",
            "centroid": "DisableCentroidData",
            "camera_calibration": "DisableCameraCalibrationData",
        }
        
        if data_type not in disable_map:
            return {"success": False, "error": f"无法禁用类型: {data_type}"}
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                getattr(self.conn.client, disable_map[data_type])
            )
            self.conn.enabled_data_types[data_type] = False
            return {"success": True, "data_type": data_type, "enabled": False}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def is_data_type_enabled(self, data_type: str) -> Dict[str, Any]:
        """检查数据类型是否已启用"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        check_map = {
            "segment": "IsSegmentDataEnabled",
            "lightweight_segment": "IsLightweightSegmentDataEnabled",
            "marker": "IsMarkerDataEnabled",
            "unlabeled_marker": "IsUnlabeledMarkerDataEnabled",
            "marker_ray": "IsMarkerRayDataEnabled",
            "device": "IsDeviceDataEnabled",
            "centroid": "IsCentroidDataEnabled",
            "camera_calibration": "IsCameraCalibrationDataEnabled",
        }
        
        if data_type not in check_map:
            return {"success": False, "error": f"未知类型: {data_type}"}
        
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                getattr(self.conn.client, check_map[data_type])
            )
            return {"success": True, "data_type": data_type, "enabled": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # 流模式和帧管理
    # -------------------------------------------------------------------------
    
    async def set_stream_mode(self, mode: str) -> Dict[str, Any]:
        """设置流模式"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        mode_map = {
            "ClientPull": ViconDataStream.Client.StreamMode.EClientPull,
            "ClientPullPreFetch": ViconDataStream.Client.StreamMode.EClientPullPreFetch,
            "ServerPush": ViconDataStream.Client.StreamMode.EServerPush,
        }
        
        if mode not in mode_map:
            return {
                "success": False,
                "error": f"未知流模式: {mode}",
                "available_modes": list(mode_map.keys())
            }
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self.conn.client.SetStreamMode,
                mode_map[mode]
            )
            self.conn.stream_mode = mode
            
            descriptions = {
                "ClientPull": "客户端拉取模式（低带宽，较高延迟）",
                "ClientPullPreFetch": "预取拉取模式（平衡带宽和延迟）",
                "ServerPush": "服务器推送模式（低延迟，高带宽）"
            }
            
            return {
                "success": True,
                "mode": mode,
                "description": descriptions.get(mode, "")
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_frame(self) -> Dict[str, Any]:
        """获取最新帧"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            has_frame = await loop.run_in_executor(None, self.conn.client.GetFrame)
            
            if not has_frame:
                return {"success": False, "error": "服务器当前未传输数据"}
            
            self.conn.frame_count += 1
            
            # 获取帧元数据
            frame_number = await loop.run_in_executor(None, self.conn.client.GetFrameNumber)
            frame_rate = await loop.run_in_executor(None, self.conn.client.GetFrameRate)
            hardware_frame = await loop.run_in_executor(None, self.conn.client.GetHardwareFrameNumber)
            
            return {
                "success": True,
                "frame_number": frame_number,
                "hardware_frame_number": hardware_frame,
                "frame_rate": frame_rate,
                "total_frames_received": self.conn.frame_count
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_timecode(self) -> Dict[str, Any]:
        """获取时间码信息"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            tc = await loop.run_in_executor(None, self.conn.client.GetTimecode)
            
            return {
                "success": True,
                "timecode": {
                    "hours": tc[0],
                    "minutes": tc[1],
                    "seconds": tc[2],
                    "frames": tc[3],
                    "subframe": tc[4],
                    "field_flag": tc[5],
                    "standard": str(tc[6]),
                    "sub_frames_per_frame": tc[7],
                    "user_bits": tc[8]
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_frame_rates(self) -> Dict[str, Any]:
        """获取所有帧率信息"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            frame_rates = await loop.run_in_executor(None, self.conn.client.GetFrameRates)
            return {
                "success": True,
                "frame_rates": frame_rates
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # 延迟分析
    # -------------------------------------------------------------------------
    
    async def get_latency_total(self) -> Dict[str, Any]:
        """获取总延迟"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            total = await loop.run_in_executor(None, self.conn.client.GetLatencyTotal)
            return {
                "success": True,
                "total_latency_seconds": total,
                "total_latency_milliseconds": total * 1000
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_latency_samples(self) -> Dict[str, Any]:
        """获取各阶段延迟样本"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            samples = await loop.run_in_executor(None, self.conn.client.GetLatencySamples)
            return {
                "success": True,
                "latency_samples": samples,
                "count": len(samples)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # 主体管理
    # -------------------------------------------------------------------------
    
    async def get_subjects(self) -> Dict[str, Any]:
        """获取所有主体信息"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            await self.get_frame()
            
            subject_names = await loop.run_in_executor(
                None, self.conn.client.GetSubjectNames
            )
            
            subjects = []
            for subject_name in subject_names:
                try:
                    root = await loop.run_in_executor(
                        None,
                        self.conn.client.GetSubjectRootSegmentName,
                        subject_name
                    )
                    quality = None
                    try:
                        quality = await loop.run_in_executor(
                            None,
                            self.conn.client.GetObjectQuality,
                            subject_name
                        )
                    except:
                        pass
                    
                    subjects.append({
                        "name": subject_name,
                        "root_segment": root,
                        "quality": quality
                    })
                except Exception as e:
                    subjects.append({"name": subject_name, "error": str(e)})
            
            return {
                "success": True,
                "subject_count": len(subjects),
                "subjects": subjects
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def clear_subject_filter(self) -> Dict[str, Any]:
        """清除主体过滤"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.conn.client.ClearSubjectFilter)
            return {"success": True, "message": "已清除主体过滤"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def add_to_subject_filter(self, subject_name: str) -> Dict[str, Any]:
        """添加主体到过滤器"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self.conn.client.AddToSubjectFilter,
                subject_name
            )
            return {
                "success": True,
                "subject": subject_name,
                "message": f"已将 {subject_name} 添加到过滤器"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # 段数据获取 (完整版 - 包含所有旋转表示)
    # -------------------------------------------------------------------------
    
    async def get_segment_data(self, subject_name: str, segment_name: str) -> Dict[str, Any]:
        """获取特定段的完整姿态数据（包含所有旋转表示）"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            await self.get_frame()
            
            # 层次结构
            children = await loop.run_in_executor(
                None, self.conn.client.GetSegmentChildren,
                subject_name, segment_name
            )
            try:
                parent = await loop.run_in_executor(
                    None, self.conn.client.GetSegmentParentName,
                    subject_name, segment_name
                )
            except Exception:
                parent = ""
            
            # 全局变换
            global_trans, global_occ = await loop.run_in_executor(
                None, self.conn.client.GetSegmentGlobalTranslation,
                subject_name, segment_name
            )
            
            global_euler, _ = await loop.run_in_executor(
                None, self.conn.client.GetSegmentGlobalRotationEulerXYZ,
                subject_name, segment_name
            )
            
            global_quat, _ = await loop.run_in_executor(
                None, self.conn.client.GetSegmentGlobalRotationQuaternion,
                subject_name, segment_name
            )
            
            global_matrix, _ = await loop.run_in_executor(
                None, self.conn.client.GetSegmentGlobalRotationMatrix,
                subject_name, segment_name
            )
            
            # 全局 Helical (螺旋) 旋转
            try:
                global_helical, _ = await loop.run_in_executor(
                    None, self.conn.client.GetSegmentGlobalRotationHelical,
                    subject_name, segment_name
                )
            except:
                global_helical = None
            
            # 本地变换
            local_trans, local_occ = await loop.run_in_executor(
                None, self.conn.client.GetSegmentLocalTranslation,
                subject_name, segment_name
            )
            
            local_euler, _ = await loop.run_in_executor(
                None, self.conn.client.GetSegmentLocalRotationEulerXYZ,
                subject_name, segment_name
            )
            
            local_quat, _ = await loop.run_in_executor(
                None, self.conn.client.GetSegmentLocalRotationQuaternion,
                subject_name, segment_name
            )
            
            # 本地 Matrix 和 Helical
            try:
                local_matrix, _ = await loop.run_in_executor(
                    None, self.conn.client.GetSegmentLocalRotationMatrix,
                    subject_name, segment_name
                )
            except:
                local_matrix = None
            
            try:
                local_helical, _ = await loop.run_in_executor(
                    None, self.conn.client.GetSegmentLocalRotationHelical,
                    subject_name, segment_name
                )
            except:
                local_helical = None
            
            # Static offsets are optional for some segment types/models.
            try:
                static_trans = await loop.run_in_executor(
                    None, self.conn.client.GetSegmentStaticTranslation,
                    subject_name, segment_name
                )
            except Exception:
                static_trans = (0.0, 0.0, 0.0)
            
            try:
                static_euler = await loop.run_in_executor(
                    None, self.conn.client.GetSegmentStaticRotationEulerXYZ,
                    subject_name, segment_name
                )
            except Exception:
                static_euler = (0.0, 0.0, 0.0)
            
            try:
                static_quat = await loop.run_in_executor(
                    None, self.conn.client.GetSegmentStaticRotationQuaternion,
                    subject_name, segment_name
                )
            except Exception:
                static_quat = (0.0, 0.0, 0.0, 1.0)
            
            try:
                static_matrix = await loop.run_in_executor(
                    None, self.conn.client.GetSegmentStaticRotationMatrix,
                    subject_name, segment_name
                )
            except Exception:
                static_matrix = (
                    (1.0, 0.0, 0.0),
                    (0.0, 1.0, 0.0),
                    (0.0, 0.0, 1.0),
                )
            
            try:
                static_helical = await loop.run_in_executor(
                    None, self.conn.client.GetSegmentStaticRotationHelical,
                    subject_name, segment_name
                )
            except:
                static_helical = None
            
            result = {
                "success": True,
                "subject": subject_name,
                "segment": segment_name,
                "hierarchy": {
                    "parent": parent if parent else None,
                    "children": children
                },
                "global": {
                    "translation": {"x": global_trans[0], "y": global_trans[1], "z": global_trans[2]},
                    "rotation_euler_xyz": {"x": global_euler[0], "y": global_euler[1], "z": global_euler[2]},
                    "rotation_quaternion": {"x": global_quat[0], "y": global_quat[1], "z": global_quat[2], "w": global_quat[3]},
                    "rotation_matrix": global_matrix,
                    "occluded": global_occ
                },
                "local": {
                    "translation": {"x": local_trans[0], "y": local_trans[1], "z": local_trans[2]},
                    "rotation_euler_xyz": {"x": local_euler[0], "y": local_euler[1], "z": local_euler[2]},
                    "rotation_quaternion": {"x": local_quat[0], "y": local_quat[1], "z": local_quat[2], "w": local_quat[3]},
                    "occluded": local_occ
                },
                "static": {
                    "translation": {"x": static_trans[0], "y": static_trans[1], "z": static_trans[2]},
                    "rotation_euler_xyz": {"x": static_euler[0], "y": static_euler[1], "z": static_euler[2]},
                    "rotation_quaternion": {"x": static_quat[0], "y": static_quat[1], "z": static_quat[2], "w": static_quat[3]},
                    "rotation_matrix": static_matrix
                }
            }
            
            # 添加可选的 Helical 和 Matrix（如果 SDK 支持）
            if global_helical:
                result["global"]["rotation_helical"] = {
                    "x": global_helical[0], "y": global_helical[1], "z": global_helical[2],
                    "magnitude": sum(x*x for x in global_helical) ** 0.5
                }
            if local_helical:
                result["local"]["rotation_helical"] = {
                    "x": local_helical[0], "y": local_helical[1], "z": local_helical[2],
                    "magnitude": sum(x*x for x in local_helical) ** 0.5
                }
            if local_matrix:
                result["local"]["rotation_matrix"] = local_matrix
            if static_helical:
                result["static"]["rotation_helical"] = {
                    "x": static_helical[0], "y": static_helical[1], "z": static_helical[2]
                }
            
            return result
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_all_segments(self, subject_name: str) -> Dict[str, Any]:
        """获取主体的所有段数据"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            await self.get_frame()
            
            segment_names = await loop.run_in_executor(
                None, self.conn.client.GetSegmentNames,
                subject_name
            )
            
            segments_data = []
            for segment_name in segment_names:
                seg_data = await self.get_segment_data(subject_name, segment_name)
                if seg_data.get("success"):
                    segments_data.append(seg_data)
            
            return {
                "success": True,
                "subject": subject_name,
                "segment_count": len(segments_data),
                "segments": segments_data
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # 标记点数据
    # -------------------------------------------------------------------------
    
    async def get_markers(self, subject_name: str = None) -> Dict[str, Any]:
        """获取标记点数据（包含光线信息）"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            await self.get_frame()
            
            markers_data = []
            
            if subject_name:
                # 特定主体的标记点
                marker_names = await loop.run_in_executor(
                    None, self.conn.client.GetMarkerNames,
                    subject_name
                )
                
                for marker_name, parent_segment in marker_names:
                    try:
                        position, occluded = await loop.run_in_executor(
                            None, self.conn.client.GetMarkerGlobalTranslation,
                            subject_name, marker_name
                        )
                        
                        marker_info = {
                            "name": marker_name,
                            "subject": subject_name,
                            "parent_segment": parent_segment,
                            "position": {"x": position[0], "y": position[1], "z": position[2]},
                            "occluded": occluded
                        }
                        
                        # 获取光线分配（如果启用了 marker_ray 数据）
                        if self.conn.enabled_data_types.get("marker_ray"):
                            try:
                                ray_assignments = await loop.run_in_executor(
                                    None, self.conn.client.GetMarkerRayAssignments,
                                    subject_name, marker_name
                                )
                                marker_info["ray_assignments"] = [
                                    {"camera_id": cam_id, "centroid_index": cent_idx}
                                    for cam_id, cent_idx in ray_assignments
                                ]
                            except:
                                pass
                        
                        markers_data.append(marker_info)
                    except Exception as e:
                        markers_data.append({
                            "name": marker_name,
                            "subject": subject_name,
                            "error": str(e)
                        })
            else:
                # 所有 labeled 标记点
                labeled_markers = await loop.run_in_executor(
                    None, self.conn.client.GetLabeledMarkers
                )
                
                for position, traj_id in labeled_markers:
                    markers_data.append({
                        "trajectory_id": traj_id,
                        "position": {"x": position[0], "y": position[1], "z": position[2]},
                        "type": "labeled"
                    })
            
            return {
                "success": True,
                "marker_count": len(markers_data),
                "markers": markers_data
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_unlabeled_markers(self) -> Dict[str, Any]:
        """获取未标记标记点"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            await self.get_frame()
            
            unlabeled_markers = await loop.run_in_executor(
                None, self.conn.client.GetUnlabeledMarkers
            )
            
            markers_data = []
            for position, traj_id in unlabeled_markers:
                markers_data.append({
                    "trajectory_id": traj_id,
                    "position": {"x": position[0], "y": position[1], "z": position[2]}
                })
            
            return {
                "success": True,
                "marker_count": len(markers_data),
                "markers": markers_data
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # 设备数据
    # -------------------------------------------------------------------------
    
    async def get_devices(self) -> Dict[str, Any]:
        """获取设备数据"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            await self.get_frame()
            
            device_names = await loop.run_in_executor(
                None, self.conn.client.GetDeviceNames
            )
            
            devices_data = []
            for device_name, device_type in device_names:
                try:
                    outputs = await loop.run_in_executor(
                        None, self.conn.client.GetDeviceOutputDetails,
                        device_name
                    )
                    
                    output_values = []
                    for output_name, component_name, unit in outputs:
                        try:
                            values, occluded = await loop.run_in_executor(
                                None, self.conn.client.GetDeviceOutputValues,
                                device_name, output_name, component_name
                            )
                            output_values.append({
                                "output_name": output_name,
                                "component": component_name,
                                "unit": str(unit).replace("Unit.", ""),
                                "values": values,
                                "occluded": occluded
                            })
                        except Exception as e:
                            output_values.append({
                                "output_name": output_name,
                                "component": component_name,
                                "error": str(e)
                            })
                    
                    devices_data.append({
                        "name": device_name,
                        "type": str(device_type).replace("DeviceType.", ""),
                        "outputs": output_values
                    })
                except Exception as e:
                    devices_data.append({
                        "name": device_name,
                        "error": str(e)
                    })
            
            return {
                "success": True,
                "device_count": len(devices_data),
                "devices": devices_data
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def set_apex_device_feedback(self, device_name: str, on: bool) -> Dict[str, Any]:
        """设置 Apex 设备触觉反馈"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self.conn.client.SetApexDeviceFeedback,
                device_name,
                on
            )
            return {
                "success": True,
                "device": device_name,
                "feedback_enabled": on
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # 力板数据（全局和本地坐标）
    # -------------------------------------------------------------------------
    
    async def get_force_plates(self, include_local: bool = False) -> Dict[str, Any]:
        """获取力板数据（包含全局和本地坐标）"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            await self.get_frame()
            
            force_plates = await loop.run_in_executor(
                None, self.conn.client.GetForcePlates
            )
            
            plates_data = []
            for plate_id in force_plates:
                try:
                    # 全局坐标数据
                    global_force = await loop.run_in_executor(
                        None, self.conn.client.GetGlobalForceVector, plate_id
                    )
                    global_moment = await loop.run_in_executor(
                        None, self.conn.client.GetGlobalMomentVector, plate_id
                    )
                    global_cop = await loop.run_in_executor(
                        None, self.conn.client.GetGlobalCenterOfPressure, plate_id
                    )
                    
                    plate_data = {
                        "plate_id": plate_id,
                        "global": {
                            "force_vectors": [
                                {"x": f[0], "y": f[1], "z": f[2], "unit": "N"} for f in global_force
                            ],
                            "moment_vectors": [
                                {"x": m[0], "y": m[1], "z": m[2], "unit": "Nm"} for m in global_moment
                            ],
                            "center_of_pressure": [
                                {"x": c[0], "y": c[1], "z": c[2], "unit": "mm"} for c in global_cop
                            ]
                        }
                    }
                    
                    # 本地坐标数据（如果请求）
                    if include_local:
                        try:
                            local_force = await loop.run_in_executor(
                                None, self.conn.client.GetForceVector, plate_id
                            )
                            local_moment = await loop.run_in_executor(
                                None, self.conn.client.GetMomentVector, plate_id
                            )
                            local_cop = await loop.run_in_executor(
                                None, self.conn.client.GetCentreOfPressure, plate_id
                            )
                            
                            plate_data["local"] = {
                                "force_vectors": [
                                    {"x": f[0], "y": f[1], "z": f[2], "unit": "N"} for f in local_force
                                ],
                                "moment_vectors": [
                                    {"x": m[0], "y": m[1], "z": m[2], "unit": "Nm"} for m in local_moment
                                ],
                                "center_of_pressure": [
                                    {"x": c[0], "y": c[1], "z": c[2], "unit": "mm"} for c in local_cop
                                ]
                            }
                        except Exception as e:
                            plate_data["local_error"] = str(e)
                    
                    plates_data.append(plate_data)
                except Exception as e:
                    plates_data.append({"plate_id": plate_id, "error": str(e)})
            
            return {
                "success": True,
                "plate_count": len(plates_data),
                "force_plates": plates_data
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_analog_channel_voltage(self, plate_id: int) -> Dict[str, Any]:
        """获取力板模拟通道电压"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            voltage = await loop.run_in_executor(
                None, self.conn.client.GetAnalogChannelVoltage, plate_id
            )
            return {
                "success": True,
                "plate_id": plate_id,
                "voltages": voltage
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # 眼动仪数据
    # -------------------------------------------------------------------------
    
    async def get_eye_trackers(self) -> Dict[str, Any]:
        """获取眼动仪列表"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            await self.get_frame()
            
            eye_tracker_ids = await loop.run_in_executor(
                None, self.conn.client.GetEyeTrackers
            )
            
            return {
                "success": True,
                "count": len(eye_tracker_ids),
                "eye_tracker_ids": eye_tracker_ids
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_eye_tracker_data(self, eye_tracker_id: int) -> Dict[str, Any]:
        """获取眼动仪数据（位置和注视向量）"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            await self.get_frame()
            
            # 位置
            position, pos_occluded = await loop.run_in_executor(
                None, self.conn.client.GetEyeTrackerGlobalPosition,
                eye_tracker_id
            )
            
            # 注视向量
            gaze, gaze_occluded = await loop.run_in_executor(
                None, self.conn.client.GetEyeTrackerGlobalGazeVector,
                eye_tracker_id
            )
            
            return {
                "success": True,
                "eye_tracker_id": eye_tracker_id,
                "position": {
                    "x": position[0], "y": position[1], "z": position[2],
                    "unit": "mm",
                    "occluded": pos_occluded
                },
                "gaze_vector": {
                    "x": gaze[0], "y": gaze[1], "z": gaze[2],
                    "unit": "normalized",
                    "occluded": gaze_occluded
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # 相机数据
    # -------------------------------------------------------------------------
    
    async def get_cameras(self, dynamic_only: bool = False) -> Dict[str, Any]:
        """获取相机列表"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            await self.get_frame()
            
            if dynamic_only:
                camera_names = await loop.run_in_executor(
                    None, self.conn.client.GetDynamicCameraNames
                )
                camera_type = "dynamic"
            else:
                camera_names = await loop.run_in_executor(
                    None, self.conn.client.GetCameraNames
                )
                camera_type = "all"
            
            cameras_data = []
            for camera_name in camera_names:
                try:
                    cam_id = await loop.run_in_executor(
                        None, self.conn.client.GetCameraID, camera_name
                    )
                    user_id = await loop.run_in_executor(
                        None, self.conn.client.GetCameraUserID, camera_name
                    )
                    cam_type = await loop.run_in_executor(
                        None, self.conn.client.GetCameraType, camera_name
                    )
                    display_name = await loop.run_in_executor(
                        None, self.conn.client.GetCameraDisplayName, camera_name
                    )
                    res_x, res_y = await loop.run_in_executor(
                        None, self.conn.client.GetCameraResolution, camera_name
                    )
                    is_video = await loop.run_in_executor(
                        None, self.conn.client.GetIsVideoCamera, camera_name
                    )
                    
                    camera_info = {
                        "name": camera_name,
                        "id": cam_id,
                        "user_id": user_id,
                        "type": cam_type,
                        "display_name": display_name,
                        "resolution": {"width": res_x, "height": res_y},
                        "is_video_camera": is_video
                    }
                    
                    # 如果启用了 camera_calibration，获取位姿
                    if self.conn.enabled_data_types.get("camera_calibration") and dynamic_only:
                        try:
                            translation = await loop.run_in_executor(
                                None, self.conn.client.GetCameraGlobalTranslation, camera_name
                            )
                            euler = await loop.run_in_executor(
                                None, self.conn.client.GetCameraGlobalRotationEulerXYZ, camera_name
                            )
                            camera_info["global_pose"] = {
                                "translation": {"x": translation[0], "y": translation[1], "z": translation[2]},
                                "rotation_euler": {"x": euler[0], "y": euler[1], "z": euler[2]}
                            }
                        except:
                            pass
                    
                    cameras_data.append(camera_info)
                except Exception as e:
                    cameras_data.append({"name": camera_name, "error": str(e)})
            
            return {
                "success": True,
                "camera_type": camera_type,
                "camera_count": len(cameras_data),
                "cameras": cameras_data
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_centroids(self, camera_name: str) -> Dict[str, Any]:
        """获取相机质心数据"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            await self.get_frame()
            
            centroids = await loop.run_in_executor(
                None, self.conn.client.GetCentroids, camera_name
            )
            
            centroids_data = []
            for centroid, radius, weight in centroids:
                centroids_data.append({
                    "position": {"x": centroid[0], "y": centroid[1]},
                    "radius": radius,
                    "weight": weight
                })
            
            return {
                "success": True,
                "camera": camera_name,
                "centroid_count": len(centroids_data),
                "centroids": centroids_data
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_camera_calibration(self, camera_name: str) -> Dict[str, Any]:
        """获取相机标定参数"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            await self.get_frame()
            
            # 全局位姿
            translation = await loop.run_in_executor(
                None, self.conn.client.GetCameraGlobalTranslation, camera_name
            )
            
            rotation_matrix = await loop.run_in_executor(
                None, self.conn.client.GetCameraGlobalRotationMatrix, camera_name
            )
            
            quaternion = await loop.run_in_executor(
                None, self.conn.client.GetCameraGlobalRotationQuaternion, camera_name
            )
            
            euler = await loop.run_in_executor(
                None, self.conn.client.GetCameraGlobalRotationEulerXYZ, camera_name
            )
            
            helical = await loop.run_in_executor(
                None, self.conn.client.GetCameraGlobalRotationHelical, camera_name
            )
            
            # 镜头参数
            focal = await loop.run_in_executor(
                None, self.conn.client.GetCameraFocalLength, camera_name
            )
            
            principal = await loop.run_in_executor(
                None, self.conn.client.GetCameraPrincipalPoint, camera_name
            )
            
            lens_params = await loop.run_in_executor(
                None, self.conn.client.GetCameraLensParameters, camera_name
            )
            
            return {
                "success": True,
                "camera": camera_name,
                "global_pose": {
                    "translation": {"x": translation[0], "y": translation[1], "z": translation[2], "unit": "mm"},
                    "rotation": {
                        "euler_xyz": {"x": euler[0], "y": euler[1], "z": euler[2], "unit": "rad"},
                        "quaternion": {"x": quaternion[0], "y": quaternion[1], "z": quaternion[2], "w": quaternion[3]},
                        "matrix": rotation_matrix,
                        "helical": {"x": helical[0], "y": helical[1], "z": helical[2]}
                    }
                },
                "lens": {
                    "focal_length_mm": focal,
                    "principal_point": {"x": principal[0], "y": principal[1]},
                    "lens_parameters": {
                        "k1": lens_params[0],
                        "k2": lens_params[1],
                        "k3": lens_params[2]
                    }
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # 坐标系管理
    # -------------------------------------------------------------------------
    
    async def set_axis_mapping(self, x: str, y: str, z: str) -> Dict[str, Any]:
        """设置坐标系映射"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            
            direction_map = {
                "Up": ViconDataStream.Client.AxisMapping.EUp,
                "Down": ViconDataStream.Client.AxisMapping.EDown,
                "Left": ViconDataStream.Client.AxisMapping.ELeft,
                "Right": ViconDataStream.Client.AxisMapping.ERight,
                "Forward": ViconDataStream.Client.AxisMapping.EForward,
                "Backward": ViconDataStream.Client.AxisMapping.EBackward,
            }
            
            if x not in direction_map or y not in direction_map or z not in direction_map:
                return {
                    "success": False,
                    "error": f"无效的方向",
                    "available_directions": list(direction_map.keys())
                }
            
            await loop.run_in_executor(
                None,
                self.conn.client.SetAxisMapping,
                direction_map[x],
                direction_map[y],
                direction_map[z]
            )
            
            return {
                "success": True,
                "axis_mapping": {"X": x, "Y": y, "Z": z},
                "coordinate_system": self._get_coordinate_system_name(x, y, z)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _get_coordinate_system_name(self, x: str, y: str, z: str) -> str:
        """根据轴映射识别坐标系名称"""
        mappings = {
            ("Forward", "Left", "Up"): "Vicon 默认 (Z-up, 右手系)",
            ("Forward", "Up", "Right"): "Unity (Y-up, 左手系)",
            ("Forward", "Right", "Up"): "Unreal/ROS (Z-up, 右手系)",
            ("Left", "Forward", "Up"): "Blender (Z-up, Y-forward)",
        }
        return mappings.get((x, y, z), "自定义坐标系")
    
    async def get_axis_mapping(self) -> Dict[str, Any]:
        """获取当前坐标系映射"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            x_axis, y_axis, z_axis = await loop.run_in_executor(
                None, self.conn.client.GetAxisMapping
            )
            
            # 将枚举转换为字符串
            axis_names = {
                ViconDataStream.Client.AxisMapping.EUp: "Up",
                ViconDataStream.Client.AxisMapping.EDown: "Down",
                ViconDataStream.Client.AxisMapping.ELeft: "Left",
                ViconDataStream.Client.AxisMapping.ERight: "Right",
                ViconDataStream.Client.AxisMapping.EForward: "Forward",
                ViconDataStream.Client.AxisMapping.EBackward: "Backward",
            }
            
            x_name = axis_names.get(x_axis, str(x_axis))
            y_name = axis_names.get(y_axis, str(y_axis))
            z_name = axis_names.get(z_axis, str(z_axis))
            
            return {
                "success": True,
                "axis_mapping": {"X": x_name, "Y": y_name, "Z": z_name},
                "coordinate_system": self._get_coordinate_system_name(x_name, y_name, z_name)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_server_orientation(self) -> Dict[str, Any]:
        """获取服务器内部方向"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            orientation = await loop.run_in_executor(
                None, self.conn.client.GetServerOrientation
            )
            
            orientation_names = {
                ViconDataStream.Client.ServerOrientation.EServerOrientationUnknown: "Unknown",
                ViconDataStream.Client.ServerOrientation.EYUp: "Y-Up",
                ViconDataStream.Client.ServerOrientation.EZUp: "Z-Up",
            }
            
            return {
                "success": True,
                "server_orientation": orientation_names.get(orientation, str(orientation))
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # 状态获取
    # -------------------------------------------------------------------------
    
    async def get_status(self) -> Dict[str, Any]:
        """获取完整连接状态"""
        base_status = {
            "success": True,
            "connected": self.conn.is_connected,
            "sdk_available": VICON_SDK_AVAILABLE,
        }
        
        if not self.conn.is_connected:
            return base_status
        
        try:
            loop = asyncio.get_event_loop()
            version = await loop.run_in_executor(None, self.conn.client.GetVersion)
            
            # 获取各数据类型的实际启用状态
            enabled_status = {}
            for data_type in self.conn.enabled_data_types:
                try:
                    result = await self.is_data_type_enabled(data_type)
                    enabled_status[data_type] = result.get("enabled", False)
                except:
                    enabled_status[data_type] = self.conn.enabled_data_types[data_type]
            
            return {
                **base_status,
                "connected": True,
                "host": self.conn.host,
                "multicast": self.conn.multicast_enabled,
                "sdk_version": {"major": version[0], "minor": version[1], "point": version[2]},
                "stream_mode": self.conn.stream_mode,
                "frames_received": self.conn.frame_count,
                "enabled_data_types": enabled_status
            }
        except Exception as e:
            return {**base_status, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # 调试功能
    # -------------------------------------------------------------------------
    
    async def set_timing_log(self, client_log: str = "", cg_stream_log: str = "") -> Dict[str, Any]:
        """设置时序日志文件"""
        if not self.conn.is_connected:
            return {"success": False, "error": "未连接"}
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self.conn.client.SetTimingLog,
                client_log,
                cg_stream_log
            )
            return {
                "success": True,
                "client_log": client_log if client_log else "disabled",
                "cg_stream_log": cg_stream_log if cg_stream_log else "disabled"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def configure_wireless(self) -> Dict[str, Any]:
        """配置无线网络适配器"""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.conn.client.ConfigureWireless)
            return {
                "success": True,
                "message": "无线网络适配器已优化配置"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


# 全局 Vicon 客户端实例
vicon = ViconClientWrapper()


# =============================================================================
# MCP Server 定义
# =============================================================================

mcp = FastMCP("vicon_datastream")


def _get_mcp_server_and_init_options():
    """Return the low-level MCP server and compatible initialization options."""
    server = getattr(mcp, "_mcp_server", mcp)
    if hasattr(server, "create_initialization_options"):
        return server, server.create_initialization_options()

    from mcp.server.lowlevel import NotificationOptions

    return server, InitializationOptions(
        server_name="vicon_datastream",
        server_version="1.0.0",
        capabilities=server.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


# -----------------------------------------------------------------------------
# Tools - 连接管理
# -----------------------------------------------------------------------------

@mcp.tool()
async def vicon_connect(
    host: str = "localhost:801",
    timeout_ms: int = 5000,
    sdk_path: str = ""
) -> str:
    """
    连接到 Vicon DataStream Server (TCP)
    
    Args:
        host: Vicon Server 地址 (格式: "IP:端口" 或 "hostname")
        timeout_ms: 连接超时时间（毫秒）
        sdk_path: SDK 路径（可选，用于自动检测失败时）
    """
    result = await vicon.connect(host, timeout_ms)
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_connect_multicast(
    local_ip: str,
    multicast_ip: str = "224.0.0.0"
) -> str:
    """
    通过 Multicast 连接到 Vicon Server
    
    Args:
        local_ip: 本地网卡 IP 地址
        multicast_ip: 组播地址 (默认 224.0.0.0，范围 224.0.0.0-239.255.255.255)
    """
    result = await vicon.connect_to_multicast(local_ip, multicast_ip)
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_start_multicast_transmit(
    server_ip: str,
    multicast_ip: str = "224.0.0.0"
) -> str:
    """
    开始 Multicast 转发（Server 端操作）
    
    Args:
        server_ip: 服务器出口网卡 IP
        multicast_ip: 目标组播地址
    """
    result = await vicon.start_transmitting_multicast(server_ip, multicast_ip)
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_stop_multicast_transmit() -> str:
    """停止 Multicast 转发"""
    result = await vicon.stop_transmitting_multicast()
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_disconnect() -> str:
    """断开与 Vicon Server 的连接"""
    result = await vicon.disconnect()
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_set_buffer_size(size: int) -> str:
    """
    设置客户端缓冲区大小（帧数）
    
    Args:
        size: 缓冲区大小（默认 1，增大可减少丢帧但增加延迟）
    """
    result = await vicon.set_buffer_size(size)
    return json.dumps(result, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Tools - 数据配置
# -----------------------------------------------------------------------------

@mcp.tool()
async def vicon_enable_data(data_type: str) -> str:
    """
    启用特定类型的数据流
    
    Args:
        data_type: 数据类型，可选:
            - "segment": 运动学段数据
            - "lightweight_segment": 轻量级段数据（节省带宽）
            - "marker": 标记点数据
            - "unlabeled_marker": 未标记标记点数据
            - "marker_ray": 标记点光线数据
            - "device": 设备数据（力板、EMG等）
            - "centroid": 质心数据
            - "camera_calibration": 相机校准数据
    """
    result = await vicon.enable_data_type(data_type)
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_disable_data(data_type: str) -> str:
    """禁用特定类型的数据流"""
    result = await vicon.disable_data_type(data_type)
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_check_data_enabled(data_type: str) -> str:
    """检查数据类型是否已启用"""
    result = await vicon.is_data_type_enabled(data_type)
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_set_stream_mode(mode: str) -> str:
    """
    设置数据流模式
    
    Args:
        mode: 流模式:
            - "ClientPull": 客户端拉取（低带宽，~16ms延迟）
            - "ClientPullPreFetch": 预取拉取（平衡，~8ms延迟）
            - "ServerPush": 服务器推送（高带宽，~2ms延迟）
    """
    result = await vicon.set_stream_mode(mode)
    return json.dumps(result, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Tools - 帧和时间
# -----------------------------------------------------------------------------

@mcp.tool()
async def vicon_get_frame() -> str:
    """
    获取最新帧数据（刷新内部缓冲区）
    
    所有数据获取操作都需要先调用此函数刷新数据。
    返回帧号、硬件帧号、帧率等信息。
    """
    result = await vicon.get_frame()
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_get_timecode() -> str:
    """获取当前帧的时间码信息（时:分:秒:帧）"""
    result = await vicon.get_timecode()
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_get_frame_rates() -> str:
    """获取所有可用的帧率信息"""
    result = await vicon.get_frame_rates()
    return json.dumps(result, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Tools - 延迟分析
# -----------------------------------------------------------------------------

@mcp.tool()
async def vicon_get_latency_total() -> str:
    """获取总延迟（秒）"""
    result = await vicon.get_latency_total()
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_get_latency_samples() -> str:
    """获取各阶段延迟样本详情"""
    result = await vicon.get_latency_samples()
    return json.dumps(result, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Tools - 主体管理
# -----------------------------------------------------------------------------

@mcp.tool()
async def vicon_get_subjects() -> str:
    """获取所有主体列表及其根段、质量分数"""
    result = await vicon.get_subjects()
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_clear_subject_filter() -> str:
    """清除主体过滤器（接收所有主体）"""
    result = await vicon.clear_subject_filter()
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_add_subject_filter(subject_name: str) -> str:
    """
    添加主体到过滤器（只接收指定主体）
    
    Args:
        subject_name: 主体名称
    """
    result = await vicon.add_to_subject_filter(subject_name)
    return json.dumps(result, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Tools - 段数据
# -----------------------------------------------------------------------------

@mcp.tool()
async def vicon_get_segment(subject_name: str, segment_name: str) -> str:
    """
    获取特定运动段的完整姿态数据
    
    包含全局/本地/静态变换，欧拉角/四元数/矩阵/螺旋角多种旋转表示。
    
    Args:
        subject_name: 主体名称（如 "Colin"）
        segment_name: 段名称（如 "Pelvis", "Hips", "Head"）
    """
    result = await vicon.get_segment_data(subject_name, segment_name)
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_get_all_segments(subject_name: str) -> str:
    """
    获取主体的所有运动段数据
    
    Args:
        subject_name: 主体名称
    """
    result = await vicon.get_all_segments(subject_name)
    return json.dumps(result, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Tools - 标记点数据
# -----------------------------------------------------------------------------

@mcp.tool()
async def vicon_get_markers(subject_name: str = "") -> str:
    """
    获取标记点数据
    
    Args:
        subject_name: 主体名称（可选，不指定则获取所有标记点）
    """
    result = await vicon.get_markers(subject_name if subject_name else None)
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_get_unlabeled_markers() -> str:
    """获取未标记标记点数据"""
    result = await vicon.get_unlabeled_markers()
    return json.dumps(result, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Tools - 设备和力板
# -----------------------------------------------------------------------------

@mcp.tool()
async def vicon_get_devices() -> str:
    """获取所有设备及其输出值"""
    result = await vicon.get_devices()
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_set_apex_feedback(device_name: str, enabled: bool) -> str:
    """
    设置 Apex 设备触觉反馈
    
    Args:
        device_name: 设备名称
        enabled: 是否启用反馈
    """
    result = await vicon.set_apex_device_feedback(device_name, enabled)
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_get_force_plates(include_local: bool = False) -> str:
    """
    获取力板数据
    
    Args:
        include_local: 是否包含本地坐标数据（相对于力板自身坐标系）
    
    返回力向量(N)、力矩向量(Nm)、压力中心位置(mm)。
    """
    result = await vicon.get_force_plates(include_local)
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_get_analog_voltage(plate_id: int) -> str:
    """
    获取力板模拟通道电压
    
    Args:
        plate_id: 力板 ID
    """
    result = await vicon.get_analog_channel_voltage(plate_id)
    return json.dumps(result, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Tools - 眼动仪
# -----------------------------------------------------------------------------

@mcp.tool()
async def vicon_get_eye_trackers() -> str:
    """获取眼动仪列表"""
    result = await vicon.get_eye_trackers()
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_get_eye_tracker(eye_tracker_id: int) -> str:
    """
    获取眼动仪数据
    
    Args:
        eye_tracker_id: 眼动仪 ID
    
    返回眼睛位置和注视向量。
    """
    result = await vicon.get_eye_tracker_data(eye_tracker_id)
    return json.dumps(result, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Tools - 相机和质心
# -----------------------------------------------------------------------------

@mcp.tool()
async def vicon_get_cameras(dynamic_only: bool = False) -> str:
    """
    获取相机列表
    
    Args:
        dynamic_only: 只获取动态相机（用于相机标定数据）
    """
    result = await vicon.get_cameras(dynamic_only)
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_get_centroids(camera_name: str) -> str:
    """
    获取相机质心数据
    
    Args:
        camera_name: 相机名称
    """
    result = await vicon.get_centroids(camera_name)
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_get_camera_calibration(camera_name: str) -> str:
    """
    获取相机标定参数
    
    返回相机全局位姿（平移+旋转）和镜头参数（焦距、主点、畸变系数）。
    
    Args:
        camera_name: 相机名称（必须是动态相机）
    """
    result = await vicon.get_camera_calibration(camera_name)
    return json.dumps(result, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Tools - 坐标系
# -----------------------------------------------------------------------------

@mcp.tool()
async def vicon_set_axis_mapping(x: str, y: str, z: str) -> str:
    """
    设置坐标系映射
    
    Vicon 默认使用右手坐标系 (+X前, +Y左, +Z上)。
    
    Args:
        x: X轴方向 ("Forward"|"Backward"|"Left"|"Right"|"Up"|"Down")
        y: Y轴方向
        z: Z轴方向
    
    常用配置:
        - Z-up 右手系: (Forward, Left, Up) - Vicon默认
        - Y-up 左手系: (Forward, Up, Right) - Unity
        - Z-up 右手系: (Forward, Right, Up) - Unreal/ROS
    """
    result = await vicon.set_axis_mapping(x, y, z)
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_get_axis_mapping() -> str:
    """获取当前坐标系映射"""
    result = await vicon.get_axis_mapping()
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_get_server_orientation() -> str:
    """获取服务器内部数据方向（Y-up 或 Z-up）"""
    result = await vicon.get_server_orientation()
    return json.dumps(result, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Tools - 状态
# -----------------------------------------------------------------------------

@mcp.tool()
async def vicon_get_status() -> str:
    """获取完整连接状态"""
    result = await vicon.get_status()
    return json.dumps(result, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Tools - 调试
# -----------------------------------------------------------------------------

@mcp.tool()
async def vicon_set_timing_log(client_log: str = "", cg_stream_log: str = "") -> str:
    """
    设置时序日志文件（用于调试延迟问题）
    
    Args:
        client_log: 客户端日志文件路径（空字符串禁用）
        cg_stream_log: CG Stream 日志文件路径（空字符串禁用）
    """
    result = await vicon.set_timing_log(client_log, cg_stream_log)
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
async def vicon_configure_wireless() -> str:
    """
    配置无线网络适配器以优化数据流
    
    Windows 专用：禁用后台扫描，启用流模式。
    """
    result = await vicon.configure_wireless()
    return json.dumps(result, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# Resources
# -----------------------------------------------------------------------------

@mcp.resource("vicon://status")
async def get_vicon_status() -> str:
    """获取 Vicon 连接状态"""
    status = await vicon.get_status()
    return json.dumps(status, indent=2, ensure_ascii=False)


@mcp.resource("vicon://subjects")
async def get_vicon_subjects() -> str:
    """获取所有主体列表"""
    result = await vicon.get_subjects()
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.resource("vicon://markers/all")
async def get_all_markers() -> str:
    """获取所有标记点数据"""
    result = await vicon.get_markers()
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.resource("vicon://devices")
async def get_vicon_devices() -> str:
    """获取所有设备数据"""
    result = await vicon.get_devices()
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.resource("vicon://forceplates")
async def get_force_plates_resource() -> str:
    """获取力板数据"""
    result = await vicon.get_force_plates()
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.resource("vicon://cameras")
async def get_vicon_cameras() -> str:
    """获取相机列表"""
    result = await vicon.get_cameras()
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.resource("vicon://latency")
async def get_vicon_latency() -> str:
    """获取延迟信息"""
    result = await vicon.get_latency_total()
    if result["success"]:
        samples = await vicon.get_latency_samples()
        result["samples"] = samples.get("latency_samples", {})
    return json.dumps(result, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# 主函数
# -----------------------------------------------------------------------------

async def run_stdio():
    """以 stdio 模式运行"""
    from mcp.server.stdio import stdio_server
    
    async with stdio_server() as (read_stream, write_stream):
        server, init_options = _get_mcp_server_and_init_options()
        await server.run(read_stream, write_stream, init_options)


async def run_sse(port: int = 8000):
    """以 SSE 模式运行"""
    from starlette.applications import Starlette
    from starlette.routing import Route
    import uvicorn
    
    sse = SseServerTransport("/messages/")
    
    class SSEEndpoint:
        async def __call__(self, scope, receive, send):
            async with sse.connect_sse(scope, receive, send) as (
                read_stream,
                write_stream,
            ):
                server, init_options = _get_mcp_server_and_init_options()
                await server.run(read_stream, write_stream, init_options)
    
    class MessageEndpoint:
        async def __call__(self, scope, receive, send):
            try:
                await sse.handle_post_message(scope, receive, send)
            except ClosedResourceError:
                logger.warning("SSE session closed before POST message could be delivered")
    
    starlette_app = Starlette(
        debug=True,
        routes=[
            Route("/sse", endpoint=SSEEndpoint()),
            Route("/messages/", endpoint=MessageEndpoint(), methods=["POST"]),
        ],
    )
    
    config = uvicorn.Config(starlette_app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


def main():
    """主入口点"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Vicon DataStream MCP Server v1.0.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # stdio 模式（默认，用于 OpenClaw/Claude Desktop）
    python src/mcp_server.py

    # SSE 模式（用于 Web 客户端）
    python src/mcp_server.py --transport sse --port 8000

自然语言示例:
    "连接到 Vicon 系统"
    "获取 Colin 的骨盆位置和旋转"
    "设置成 Unity 坐标系"
    "获取所有力板数据"
    "获取眼动仪注视向量"
        """
    )
    
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="传输模式"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="SSE 模式端口"
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 1.0.0"
    )
    
    args = parser.parse_args()
    
    logger.info(f"🚀 启动 Vicon DataStream MCP Server v1.0.0")
    logger.info(f"   传输模式: {args.transport}")
    logger.info(f"   SDK 可用: {VICON_SDK_AVAILABLE}")
    
    if args.transport == "stdio":
        asyncio.run(run_stdio())
    else:
        asyncio.run(run_sse(args.port))


if __name__ == "__main__":
    main()
