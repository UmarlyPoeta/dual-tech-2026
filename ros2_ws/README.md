# ROS 2 workspace (organizer bridge scaffold)

Packages:

- **dt_interfaces** — placeholder `.msg` types; replace or extend per organizer spec.
- **dt_organizer_bridge** — `organizer_bridge_node` publishes stub topics at configurable rate.
- **dt_bringup** — `organizer_bridge.launch.py` + `config/organizer_ros.yaml`.

## Build (native Humble, e.g. RPi5 or x86 with Humble)

```bash
source /opt/ros/humble/setup.bash
cd ros2_ws
rosdep install --from-paths src --ignore-src -y
colcon build --symlink-install
source install/setup.bash
ros2 launch dt_bringup organizer_bridge.launch.py
```

## DDS domain

Set `ROS_DOMAIN_ID` to match organizers (default in launch is `0` or current environment):

```bash
export ROS_DOMAIN_ID=42
ros2 launch dt_bringup organizer_bridge.launch.py
```

## Next steps

Wire `organizer_bridge_node` to `main_uav.py` / `main_ugv.py` (e.g. timer off, `stub_mode: false`, publish from mission callbacks). Replace topic names in `organizer_ros.yaml` with the official list from the competition document.
