#!/usr/bin/env bash
# Source ROS 2 Humble, build workspace if needed, launch organizer placeholder bridge.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS="${ROOT}/ros2_ws"

if [[ ! -d /opt/ros/humble ]]; then
  echo "ERROR: /opt/ros/humble not found. Install ROS 2 Humble or use the Docker CI image." >&2
  exit 1
fi

# shellcheck source=/dev/null
source /opt/ros/humble/setup.bash
cd "${WS}"

if [[ ! -f install/setup.bash ]]; then
  echo "Workspace not built; running colcon build..."
  rosdep update
  rosdep install --from-paths src --ignore-src -r -y || true
  colcon build --symlink-install
fi

# shellcheck source=/dev/null
source install/setup.bash
exec ros2 launch dt_bringup organizer_bridge.launch.py
