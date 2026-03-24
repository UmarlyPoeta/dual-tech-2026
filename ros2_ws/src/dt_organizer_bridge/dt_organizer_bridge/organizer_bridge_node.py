"""Publish placeholder organizer topics until wired to the Python mission stack.

Replace topic names, message types, and field mapping per the official competition
ROS interface document. When stub_mode is false, the timer can be disabled and
callbacks added to accept external data (e.g. from a multiprocessing queue).
"""

from __future__ import annotations

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

from dt_interfaces.msg import MissionTelemetry, ObjectDetected


def _organizer_qos() -> QoSProfile:
    """Best-effort, small history — suitable for high-rate vision; tunable per organizer spec."""
    return QoSProfile(
        reliability=ReliabilityPolicy.BEST_EFFORT,
        durability=DurabilityPolicy.VOLATILE,
        history=HistoryPolicy.KEEP_LAST,
        depth=5,
    )


class OrganizerBridgeNode(Node):
    def __init__(self) -> None:
        super().__init__("dt_organizer_bridge")

        self.declare_parameter("stub_mode", True)
        self.declare_parameter("publish_rate_hz", 1.0)
        self.declare_parameter("object_topic", "/dualtech/placeholder/organizers/object_detected")
        self.declare_parameter("telemetry_topic", "/dualtech/placeholder/organizers/mission_telemetry")
        self.declare_parameter("status_topic", "/dualtech/placeholder/organizers/bridge_status")
        self.declare_parameter("frame_id", "camera_optical_frame")
        self.declare_parameter("platform", "ugv")

        self._pub_object = self.create_publisher(
            ObjectDetected,
            self.get_parameter("object_topic").get_parameter_value().string_value,
            _organizer_qos(),
        )
        self._pub_telemetry = self.create_publisher(
            MissionTelemetry,
            self.get_parameter("telemetry_topic").get_parameter_value().string_value,
            _organizer_qos(),
        )
        self._pub_status = self.create_publisher(
            String,
            self.get_parameter("status_topic").get_parameter_value().string_value,
            10,
        )

        rate = max(0.1, float(self.get_parameter("publish_rate_hz").get_parameter_value().double_value))
        period = 1.0 / rate
        self._timer = self.create_timer(period, self._on_timer)
        self.get_logger().info(
            "Organizer bridge up (stub_mode=%s). Replace topic names per organizer spec."
            % self.get_parameter("stub_mode").get_parameter_value().bool_value
        )

    def _on_timer(self) -> None:
        if not self.get_parameter("stub_mode").get_parameter_value().bool_value:
            return

        now = self.get_clock().now().to_msg()
        frame_id = self.get_parameter("frame_id").get_parameter_value().string_value
        platform = self.get_parameter("platform").get_parameter_value().string_value

        obj = ObjectDetected()
        obj.header.stamp = now
        obj.header.frame_id = frame_id
        obj.class_name = "PLACEHOLDER_CLASS"
        obj.confidence = 0.0
        obj.bbox_x_min = 0.0
        obj.bbox_y_min = 0.0
        obj.bbox_x_max = 0.0
        obj.bbox_y_max = 0.0
        obj.qr_payload = ""
        obj.placeholder = True
        self._pub_object.publish(obj)

        telem = MissionTelemetry()
        telem.header.stamp = now
        telem.header.frame_id = "map"
        telem.platform = platform
        telem.latitude = 0.0
        telem.longitude = 0.0
        telem.altitude_m = 0.0
        telem.baro_alt_m = 0.0
        telem.yaw_deg = 0.0
        telem.placeholder = True
        self._pub_telemetry.publish(telem)

        st = String()
        st.data = "dt_organizer_bridge stub active — replace topics/messages for organizers"
        self._pub_status.publish(st)


def main() -> None:
    rclpy.init()
    node = OrganizerBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
