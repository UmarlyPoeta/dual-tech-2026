from setuptools import find_packages, setup

package_name = "dt_organizer_bridge"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Dual-Tech",
    maintainer_email="dualtech@example.com",
    description="Organizer-facing ROS2 bridge (placeholder publishers).",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "organizer_bridge_node = dt_organizer_bridge.organizer_bridge_node:main",
        ],
    },
)
