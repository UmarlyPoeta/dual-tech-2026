"""Launch organizer placeholder bridge with parameters from share/dt_bringup/config."""

from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import SetEnvironmentVariable
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    pkg_share = get_package_share_directory("dt_bringup")
    params_file = os.path.join(pkg_share, "config", "organizer_ros.yaml")

    domain = os.environ.get("ROS_DOMAIN_ID", "0")

    return LaunchDescription(
        [
            SetEnvironmentVariable(name="ROS_DOMAIN_ID", value=domain),
            Node(
                package="dt_organizer_bridge",
                executable="organizer_bridge_node",
                name="dt_organizer_bridge",
                output="screen",
                parameters=[params_file],
            ),
        ]
    )
