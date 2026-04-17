"""
ROS2 桥接示例

将 Vicon DataStream 数据发布为 ROS2 topics。
需要安装: pip install rclpy geometry_msgs std_msgs
"""

import asyncio
import json
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from geometry_msgs.msg import PoseStamped, TransformStamped
from std_msgs.msg import Float32MultiArray
import tf2_ros

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class ViconMCPBridge(Node):
    """Vicon MCP 到 ROS2 的桥接节点"""
    
    def __init__(self):
        super().__init__('vicon_mcp_bridge')
        
        # 参数
        self.declare_parameter('host', 'localhost:801')
        self.declare_parameter('subjects', [''])  # 空列表表示所有主体
        self.declare_parameter('publish_rate', 100.0)  # Hz
        
        self.host = self.get_parameter('host').value
        self.subjects = self.get_parameter('subjects').value
        self.publish_rate = self.get_parameter('publish_rate').value
        
        # QoS 配置
        qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT
        )
        
        # 发布器
        self.pose_publishers = {}
        self.marker_pub = self.create_publisher(Float32MultiArray, '/vicon/markers', qos)
        
        # TF 广播器
        self.tf_broadcaster = tf2_ros.TransformBroadcaster(self)
        
        # 状态
        self.connected = False
        self.session = None
        self.available_subjects = []
        
        # 启动 MCP 连接
        self.mcp_task = asyncio.create_task(self._run_mcp_bridge())
        
        # 创建定时器
        self.timer = self.create_timer(1.0 / self.publish_rate, self._publish_data)
        
        self.get_logger().info(f'Vicon MCP Bridge 已启动，连接到 {self.host}')
    
    async def _run_mcp_bridge(self):
        """运行 MCP 客户端并维持连接"""
        server_params = StdioServerParameters(
            command="python",
            args=["vicon_datastream_mcp.py"],
            env={"VICON_HOST": self.host}
        )
        
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self.session = session
                    
                    # 连接并配置
                    result = await session.call_tool("vicon_connect", {
                        "host": self.host
                    })
                    self.get_logger().info(f'连接结果: {result}')
                    
                    # 启用数据
                    await session.call_tool("vicon_enable_data", {"data_type": "segment"})
                    await session.call_tool("vicon_enable_data", {"data_type": "marker"})
                    await session.call_tool("vicon_set_stream_mode", {"mode": "ServerPush"})
                    
                    self.connected = True
                    
                    # 获取主体列表
                    subjects_result = await session.call_tool("vicon_get_subjects", {})
                    subjects_data = json.loads(subjects_result.content[0].text)
                    if subjects_data.get('success'):
                        self.available_subjects = [
                            s['name'] for s in subjects_data.get('subjects', [])
                        ]
                        self.get_logger().info(f'可用主体: {self.available_subjects}')
                        
                        # 为每个主体创建发布器
                        for subject in self.available_subjects:
                            topic_name = f'/vicon/{subject}/pose'
                            self.pose_publishers[subject] = self.create_publisher(
                                PoseStamped, topic_name, qos
                            )
                    
                    # 保持连接
                    while rclpy.ok() and self.connected:
                        await asyncio.sleep(0.1)
                        
        except Exception as e:
            self.get_logger().error(f'MCP 连接错误: {e}')
            self.connected = False
    
    def _publish_data(self):
        """定时发布数据"""
        if not self.connected or not self.session:
            return
        
        try:
            # 创建任务来获取数据
            asyncio.create_task(self._fetch_and_publish())
        except Exception as e:
            self.get_logger().warn(f'发布数据失败: {e}')
    
    async def _fetch_and_publish(self):
        """获取并发布数据"""
        try:
            # 获取最新帧
            await self.session.call_tool("vicon_get_frame", {})
            
            # 发布每个主体的数据
            for subject_name in self.available_subjects:
                # 获取根段（或所有段）
                segments_result = await self.session.call_tool("vicon_get_all_segments", {
                    "subject_name": subject_name
                })
                segments_data = json.loads(segments_result.content[0].text)
                
                if not segments_data.get('success'):
                    continue
                
                for segment in segments_data.get('segments', []):
                    self._publish_segment_tf(subject_name, segment)
                    
                    # 如果是根段，也发布到 pose topic
                    if segment['segment'] == segments_data.get('root_segment', ''):
                        self._publish_pose(subject_name, segment)
            
            # 发布标记点
            markers_result = await self.session.call_tool("vicon_get_markers", {})
            markers_data = json.loads(markers_result.content[0].text)
            if markers_data.get('success'):
                self._publish_markers(markers_data.get('markers', []))
                
        except Exception as e:
            self.get_logger().warn(f'获取数据失败: {e}')
    
    def _publish_pose(self, subject_name: str, segment_data: dict):
        """发布位姿到 ROS topic"""
        if subject_name not in self.pose_publishers:
            return
        
        msg = PoseStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'vicon_world'
        
        # 位置 (Vicon 是 mm，ROS 是 m)
        trans = segment_data['global']['translation']
        msg.pose.position.x = trans['x'] / 1000.0
        msg.pose.position.y = trans['y'] / 1000.0
        msg.pose.position.z = trans['z'] / 1000.0
        
        # 旋转（四元数）
        quat = segment_data['global']['rotation_quaternion']
        msg.pose.orientation.x = quat['x']
        msg.pose.orientation.y = quat['y']
        msg.pose.orientation.z = quat['z']
        msg.pose.orientation.w = quat['w']
        
        self.pose_publishers[subject_name].publish(msg)
    
    def _publish_segment_tf(self, subject_name: str, segment_data: dict):
        """发布 TF 变换"""
        t = TransformStamped()
        t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id = 'vicon_world'
        t.child_frame_id = f'vicon/{subject_name}/{segment_data["segment"]}'
        
        # 位置
        trans = segment_data['global']['translation']
        t.transform.translation.x = trans['x'] / 1000.0
        t.transform.translation.y = trans['y'] / 1000.0
        t.transform.translation.z = trans['z'] / 1000.0
        
        # 旋转
        quat = segment_data['global']['rotation_quaternion']
        t.transform.rotation.x = quat['x']
        t.transform.rotation.y = quat['y']
        t.transform.rotation.z = quat['z']
        t.transform.rotation.w = quat['w']
        
        self.tf_broadcaster.sendTransform(t)
    
    def _publish_markers(self, markers: list):
        """发布标记点数据"""
        if not markers:
            return
        
        msg = Float32MultiArray()
        # 格式: [count, id1, x1, y1, z1, occluded1, id2, x2, y2, z2, occluded2, ...]
        data = [len(markers)]
        for marker in markers:
            data.append(marker.get('trajectory_id', 0))
            pos = marker.get('position', {})
            data.extend([pos.get('x', 0) / 1000.0, 
                        pos.get('y', 0) / 1000.0, 
                        pos.get('z', 0) / 1000.0])
            data.append(1.0 if marker.get('occluded', False) else 0.0)
        
        msg.data = data
        self.marker_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    
    bridge = ViconMCPBridge()
    
    try:
        rclpy.spin(bridge)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
