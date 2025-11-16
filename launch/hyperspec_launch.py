#!/usr/bin/env python3
"""
ROS2 launch file for openhsi_ros2 hyperspectral camera node.

Purpose:
    Launch the hyperspectral camera node with configurable parameters for both
    XIMEA and Lucid Vision Lab cameras. Automatically sets up Arena SDK environment
    for Lucid cameras.

Features:
    - Configurable camera type (ximea/lucid)
    - JSON-based camera configuration loading
    - Adjustable capture frequency and exposure
    - Auto-exposure control
    - Optional camera serial number / MAC address selection

Example run commands:
    # Launch with Ximea camera:
    ros2 launch openhsi_ros2 hyperspec_launch.py camera_type:=ximea \
        config_file:=/path/to/cam_settings_ximea.json

    # Launch with Lucid camera:
    ros2 launch openhsi_ros2 hyperspec_launch.py camera_type:=lucid \
        config_file:=/path/to/cam_settings_lucid.json \
        cap_hz:=15.0 exposure_ms:=12.0

    # Launch with auto-exposure:
    ros2 launch openhsi_ros2 hyperspec_launch.py camera_type:=lucid \
        config_file:=/path/to/cam_settings_lucid.json \
        auto_exposure_enable:=true

Created: November 2025
"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    """
    Generate launch description for hyperspectral camera node.

    Returns:
        LaunchDescription with all configured nodes and parameters
    """
    # Get package directories
    pkg_share = FindPackageShare("openhsi_ros2").find("openhsi_ros2")
    config_dir = os.path.join(pkg_share, "config")
    arena_sdk_dir = os.path.join(
        os.path.dirname(os.path.dirname(pkg_share)), "src", "openhsi_ros2", "arena_sdk"
    )

    # Declare launch arguments with defaults
    camera_type_arg = DeclareLaunchArgument(
        "camera_type", default_value="ximea", description="Camera type: ximea or lucid"
    )

    config_file_arg = DeclareLaunchArgument(
        "config_file",
        default_value=os.path.join(config_dir, "cam_settings_ximea_MVCV-1082.json"),
        description="Path to camera configuration JSON file",
    )

    calibration_file_arg = DeclareLaunchArgument(
        "calibration_file",
        default_value="",
        description="Path to calibration file (optional)",
    )

    cap_hz_arg = DeclareLaunchArgument(
        "cap_hz", default_value="10.0", description="Capture frequency in Hz"
    )

    exposure_ms_arg = DeclareLaunchArgument(
        "exposure_ms",
        default_value="10.0",
        description="Initial exposure time in milliseconds",
    )

    serial_number_arg = DeclareLaunchArgument(
        "serial_number",
        default_value="",
        description="Camera serial number (Ximea) or MAC address (Lucid)",
    )

    mac_address_arg = DeclareLaunchArgument(
        "mac_address", default_value="", description="MAC address for Lucid camera"
    )

    # Auto-exposure arguments
    auto_exposure_enable_arg = DeclareLaunchArgument(
        "auto_exposure_enable",
        default_value="false",
        description="Enable automatic exposure adjustment",
    )

    auto_exposure_low_threshold_arg = DeclareLaunchArgument(
        "auto_exposure_low_threshold",
        default_value="500.0",
        description="Low signal threshold for auto-exposure (increase exposure when below)",
    )

    auto_exposure_high_threshold_arg = DeclareLaunchArgument(
        "auto_exposure_high_threshold",
        default_value="3000.0",
        description="High signal threshold for auto-exposure (decrease exposure when above)",
    )

    auto_exposure_window_sec_arg = DeclareLaunchArgument(
        "auto_exposure_window_sec",
        default_value="5.0",
        description="Time window in seconds for auto-exposure evaluation",
    )

    auto_exposure_min_samples_arg = DeclareLaunchArgument(
        "auto_exposure_min_samples",
        default_value="10",
        description="Minimum samples needed before auto-exposure adjustment",
    )

    # Set up Arena SDK environment variables for Lucid cameras
    arena_sdk_lib_path = os.path.join(arena_sdk_dir, "ArenaSDK", "lib64")
    arena_sdk_genicam_path = os.path.join(
        arena_sdk_dir, "ArenaSDK", "GenICam", "library", "lib", "Linux64_ARM"
    )
    arena_sdk_ffmpeg_path = os.path.join(arena_sdk_dir, "ArenaSDK", "ffmpeg")

    # Set environment variables (these will be set if Arena SDK is installed)
    ld_library_path = SetEnvironmentVariable(
        name="LD_LIBRARY_PATH",
        value=[
            arena_sdk_lib_path,
            ":",
            arena_sdk_genicam_path,
            ":",
            arena_sdk_ffmpeg_path,
            ":",
            os.environ.get("LD_LIBRARY_PATH", ""),
        ],
    )

    genicam_gentl64_path = SetEnvironmentVariable(
        name="GENICAM_GENTL64_PATH", value=arena_sdk_genicam_path
    )

    genicam_root = SetEnvironmentVariable(
        name="GENICAM_ROOT_V3_1",
        value=os.path.join(arena_sdk_dir, "ArenaSDK", "GenICam"),
    )

    # Define the hyperspec camera node
    hyperspec_node = Node(
        package="openhsi_ros2",
        executable="hyperspec_node",
        name="hyperspec_camera",
        output="screen",
        emulate_tty=True,
        parameters=[
            {
                "camera_type": LaunchConfiguration("camera_type"),
                "config_file": LaunchConfiguration("config_file"),
                "calibration_file": LaunchConfiguration("calibration_file"),
                "cap_hz": LaunchConfiguration("cap_hz"),
                "exposure_ms": LaunchConfiguration("exposure_ms"),
                "serial_number": LaunchConfiguration("serial_number"),
                "mac_address": LaunchConfiguration("mac_address"),
                "auto_exposure_enable": LaunchConfiguration("auto_exposure_enable"),
                "auto_exposure_low_threshold": LaunchConfiguration(
                    "auto_exposure_low_threshold"
                ),
                "auto_exposure_high_threshold": LaunchConfiguration(
                    "auto_exposure_high_threshold"
                ),
                "auto_exposure_window_sec": LaunchConfiguration(
                    "auto_exposure_window_sec"
                ),
                "auto_exposure_min_samples": LaunchConfiguration(
                    "auto_exposure_min_samples"
                ),
            }
        ],
    )

    # Create and return launch description
    return LaunchDescription(
        [
            # Set environment variables
            ld_library_path,
            genicam_gentl64_path,
            genicam_root,
            # Declare arguments
            camera_type_arg,
            config_file_arg,
            calibration_file_arg,
            cap_hz_arg,
            exposure_ms_arg,
            serial_number_arg,
            mac_address_arg,
            auto_exposure_enable_arg,
            auto_exposure_low_threshold_arg,
            auto_exposure_high_threshold_arg,
            auto_exposure_window_sec_arg,
            auto_exposure_min_samples_arg,
            # Launch node
            hyperspec_node,
        ]
    )
