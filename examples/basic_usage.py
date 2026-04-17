"""
基本使用示例 - Vicon DataStream MCP Client

展示如何作为 MCP 客户端调用 Vicon MCP Server 的工具。
"""

import asyncio
import json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def vicon_demo():
    """演示 Vicon MCP Server 的基本使用"""
    
    # 配置 MCP Server 启动参数
    server_params = StdioServerParameters(
        command="python",
        args=["vicon_datastream_mcp.py"],
        env={"VICON_HOST": "localhost:801"}
    )
    
    # 连接到 MCP Server
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # 初始化
            await session.initialize()
            
            print("=== Vicon DataStream MCP Demo ===\n")
            
            # 1. 连接到 Vicon Server
            print("1. 连接到 Vicon Server...")
            result = await session.call_tool("vicon_connect", {
                "host": "localhost:801",
                "timeout_ms": 5000
            })
            print(f"   结果: {result}\n")
            
            # 2. 获取状态
            print("2. 获取连接状态...")
            result = await session.call_tool("vicon_get_status", {})
            print(f"   结果: {result}\n")
            
            # 3. 启用数据类型
            print("3. 启用运动学段数据...")
            result = await session.call_tool("vicon_enable_data", {
                "data_type": "segment"
            })
            print(f"   结果: {result}\n")
            
            # 4. 设置流模式
            print("4. 设置 ServerPush 流模式（低延迟）...")
            result = await session.call_tool("vicon_set_stream_mode", {
                "mode": "ServerPush"
            })
            print(f"   结果: {result}\n")
            
            # 5. 获取最新帧
            print("5. 获取最新帧...")
            result = await session.call_tool("vicon_get_frame", {})
            print(f"   结果: {result}\n")
            
            # 6. 获取所有主体
            print("6. 获取主体列表...")
            result = await session.call_tool("vicon_get_subjects", {})
            data = json.loads(result.content[0].text)
            print(f"   找到 {data.get('subject_count', 0)} 个主体")
            for subject in data.get('subjects', []):
                print(f"   - {subject['name']} (根段: {subject['root_segment']})")
            print()
            
            # 7. 获取特定段的姿态数据
            if data.get('subjects'):
                subject_name = data['subjects'][0]['name']
                root_segment = data['subjects'][0]['root_segment']
                
                print(f"7. 获取 '{subject_name}' 的 '{root_segment}' 段数据...")
                result = await session.call_tool("vicon_get_segment", {
                    "subject_name": subject_name,
                    "segment_name": root_segment
                })
                
                seg_data = json.loads(result.content[0].text)
                if seg_data.get('success'):
                    global_data = seg_data.get('global', {})
                    trans = global_data.get('translation', {})
                    print(f"   全局位置: X={trans['x']:.2f}, Y={trans['y']:.2f}, Z={trans['z']:.2f} mm")
                    
                    rot = global_data.get('rotation_euler_xyz', {})
                    print(f"   全局旋转: X={rot['x']:.4f}, Y={rot['y']:.4f}, Z={rot['z']:.4f} rad")
                    print(f"   遮挡状态: {'是' if global_data.get('occluded') else '否'}")
                print()
            
            # 8. 获取所有标记点
            print("8. 获取标记点数据...")
            result = await session.call_tool("vicon_get_markers", {})
            marker_data = json.loads(result.content[0].text)
            print(f"   找到 {marker_data.get('marker_count', 0)} 个标记点\n")
            
            # 9. 获取力板数据（如果可用）
            print("9. 获取力板数据...")
            result = await session.call_tool("vicon_get_force_plates", {})
            force_data = json.loads(result.content[0].text)
            if force_data.get('success') and force_data.get('plate_count', 0) > 0:
                print(f"   找到 {force_data['plate_count']} 块力板")
                for plate in force_data.get('force_plates', []):
                    print(f"   力板 ID: {plate['plate_id']}")
                    if 'force_vectors' in plate and plate['force_vectors']:
                        fv = plate['force_vectors'][0]
                        print(f"     力向量: ({fv['x']:.2f}, {fv['y']:.2f}, {fv['z']:.2f}) N")
            else:
                print("   没有检测到力板或设备数据")
            print()
            
            # 10. 断开连接
            print("10. 断开连接...")
            result = await session.call_tool("vicon_disconnect", {})
            print(f"    结果: {result}\n")
            
            print("=== Demo 完成 ===")


async def continuous_stream_demo():
    """演示连续数据流（实时模式）"""
    
    server_params = StdioServerParameters(
        command="python",
        args=["vicon_datastream_mcp.py"],
        env={"VICON_HOST": "localhost:801"}
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # 连接并配置
            await session.call_tool("vicon_connect", {"host": "localhost:801"})
            await session.call_tool("vicon_enable_data", {"data_type": "segment"})
            await session.call_tool("vicon_set_stream_mode", {"mode": "ServerPush"})
            
            print("=== 连续数据流 Demo (按 Ctrl+C 停止) ===\n")
            
            try:
                while True:
                    # 获取帧
                    await session.call_tool("vicon_get_frame", {})
                    
                    # 获取骨盆位置
                    result = await session.call_tool("vicon_get_segment", {
                        "subject_name": "Colin",  # 修改为你的主体名
                        "segment_name": "Pelvis"
                    })
                    
                    data = json.loads(result.content[0].text)
                    if data.get('success'):
                        trans = data['global']['translation']
                        print(f"\r骨盆位置: X={trans['x']:8.2f} Y={trans['y']:8.2f} Z={trans['z']:8.2f} mm", end="")
                    
                    await asyncio.sleep(0.01)  # 100Hz 更新
                    
            except KeyboardInterrupt:
                print("\n\n停止数据流")
            
            await session.call_tool("vicon_disconnect", {})


if __name__ == "__main__":
    # 运行基本演示
    asyncio.run(vicon_demo())
    
    # 运行连续流演示（取消注释）
    # asyncio.run(continuous_stream_demo())
