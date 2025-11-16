"""
Setup configuration for openhsi_ros2 ROS2 package.

Purpose:
    Configure the openhsi_ros2 package for installation with ROS2 colcon build system.
    Defines package metadata, dependencies, entry points, and data files.

Usage:
    Build the package:
        cd /media/logic/USamsung/ros2_ws
        colcon build --packages-select openhsi_ros2

    Source the workspace:
        source install/setup.bash

    Run the node:
        ros2 run openhsi_ros2 hyperspec_node --ros-args -p camera_type:=lucid

Created: November 2025
"""

from setuptools import setup
from glob import glob
import os

package_name = "openhsi_ros2"

setup(
    name=package_name,
    version="1.0.0",
    packages=[package_name],
    data_files=[
        # Install package marker
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        # Install package.xml
        ("share/" + package_name, ["package.xml"]),
        # Install launch files
        (os.path.join("share", package_name, "launch"), glob("launch/*.py")),
        # Install config files
        (os.path.join("share", package_name, "config"), glob("config/*.json")),
    ],
    install_requires=[
        "setuptools",
        "numpy",
        "opencv-python",
        "xarray",
        "netcdf4",
    ],
    zip_safe=True,
    maintainer="Logic",
    maintainer_email="your_email@example.com",
    description="ROS2 package for XIMEA and Lucid hyperspectral cameras",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "hyperspec_node = openhsi_ros2.hyperspec_node:main",
        ],
    },
)
