#!/usr/bin/env python3
"""
ROS 2 node for XIMEA and Lucid hyperspectral camera line scan data acquisition.

Purpose:
    Unified interface for XIMEA and Lucid hyperspectral cameras to publish individual
    line scan images as ROS 2 topics for synchronized data logging with other sensors.
    Replaces standalone hypercube file saving with ROS topic publishing for better
    integration with mission data logging systems.

Features:
    - Support for both XIMEA and Lucid Vision Lab cameras
    - Publishes line scan images at configurable frequency for data logging
    - Publishes camera info, wavelength calibration, and diagnostic data
    - Exposure control via ROS 2 parameters and topics
    - Image statistics monitoring (variance, mean, median) for external analysis
    - JSON-based camera configuration (exposure, FOV, wavelengths, crop area, etc.)
    - NetCDF calibration data support with multiple processing levels
    - Applies optical cropping, wavelength calibration, and hardware binning
    - Radiometric calibration (flat field, dark subtract, radiance conversion)

Example run commands:
    # Launch with Ximea camera:
    ros2 run hyperspec_pkg hyperspec_ros2_node --ros-args \
        -p camera_type:=ximea \
        -p config_file:=/path/to/cam_settings_ximea.json \
        -p cap_hz:=10.0 \
        -p exposure_ms:=10.0

    # Launch with Lucid camera:
    ros2 run hyperspec_pkg hyperspec_ros2_node --ros-args \
        -p camera_type:=lucid \
        -p config_file:=/path/to/cam_settings_lucid.json \
        -p calibration_file:=/path/to/calibration.nc \
        -p processing_lvl:=2 \
        -p cap_hz:=10.0 \
        -p exposure_ms:=15.0

Created: November 2025
Author: Michael Venz
"""

import os
import sys
import time
import warnings
import traceback
import numpy as np
import json
import ctypes
import threading
import queue
from typing import Tuple, Optional, Dict, Any, List
from abc import ABC, abstractmethod
from collections import deque

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from std_msgs.msg import Header, Float64, Float64MultiArray, String
from sensor_msgs.msg import Image, CameraInfo
from cv_bridge import CvBridge


class AutoExposureController:
    """
    Automatic exposure adjustment controller for hyperspectral cameras.

    Monitors image statistics and adjusts exposure through predefined presets
    to maintain optimal signal levels in varying light conditions.
    """

    def __init__(
        self,
        exposure_presets_ms: List[float],
        initial_exposure_ms: float,
        low_signal_threshold: float = 500.0,
        high_signal_threshold: float = 3000.0,
        evaluation_window_sec: float = 5.0,
        min_samples_for_decision: int = 10,
        logger=None,
    ):
        """
        Initialize auto-exposure controller.

        Args:
            exposure_presets_ms: List of allowed exposure values in milliseconds
            initial_exposure_ms: Starting exposure value
            low_signal_threshold: Mean pixel value below which to increase exposure
            high_signal_threshold: Mean pixel value above which to decrease exposure
            evaluation_window_sec: Time window for statistics evaluation
            min_samples_for_decision: Minimum samples needed before adjustment
            logger: ROS 2 logger instance
        """
        self.logger = logger
        self.exposure_presets_ms = sorted(exposure_presets_ms)
        self.low_threshold = low_signal_threshold
        self.high_threshold = high_signal_threshold
        self.evaluation_window = evaluation_window_sec
        self.min_samples = min_samples_for_decision

        # Find initial preset index
        self.current_preset_index = self._find_closest_preset_index(initial_exposure_ms)
        self.current_exposure_ms = self.exposure_presets_ms[self.current_preset_index]

        # Statistics tracking
        self.mean_buffer = deque(maxlen=100)
        self.last_adjustment_time = time.time()
        self.adjustment_count = 0

        if self.logger:
            self.logger.info(
                f"Auto-exposure initialized: {len(self.exposure_presets_ms)} presets, "
                f"range {self.exposure_presets_ms[0]:.1f}-{self.exposure_presets_ms[-1]:.1f}ms"
            )
            self.logger.info(
                f"Thresholds: low={self.low_threshold:.0f}, high={self.high_threshold:.0f}, "
                f"window={self.evaluation_window:.1f}s"
            )

    def _find_closest_preset_index(self, exposure_ms: float) -> int:
        """
        Find index of closest preset to given exposure value.

        Args:
            exposure_ms: Target exposure in milliseconds

        Returns:
            Index of closest preset
        """
        differences = [abs(preset - exposure_ms) for preset in self.exposure_presets_ms]
        return differences.index(min(differences))

    def update_statistics(self, mean: float, variance: float, median: float) -> None:
        """
        Update statistics buffer with new image measurements.

        Args:
            mean: Mean pixel value
            variance: Pixel variance
            median: Median pixel value
        """
        self.mean_buffer.append(mean)

    def should_adjust_exposure(self) -> Tuple[bool, Optional[str]]:
        """
        Determine if exposure adjustment is needed based on accumulated statistics.

        Returns:
            Tuple of (should_adjust, reason) where reason is 'increase', 'decrease', or None
        """
        # Check if enough time has passed since last adjustment
        time_since_adjustment = time.time() - self.last_adjustment_time
        if time_since_adjustment < self.evaluation_window:
            return False, None

        # Check if we have enough samples
        if len(self.mean_buffer) < self.min_samples:
            return False, None

        # Calculate average mean over the buffer
        avg_mean = np.mean(list(self.mean_buffer))

        # Determine if adjustment needed
        if avg_mean < self.low_threshold:
            # Signal too low, need to increase exposure if possible
            if self.current_preset_index < len(self.exposure_presets_ms) - 1:
                return True, "increase"
            else:
                if self.logger:
                    self.logger.warning(
                        f"Signal low (mean={avg_mean:.0f}) but already at maximum exposure "
                        f"({self.current_exposure_ms:.1f}ms)"
                    )
                return False, None

        elif avg_mean > self.high_threshold:
            # Signal too high, need to decrease exposure if possible
            if self.current_preset_index > 0:
                return True, "decrease"
            else:
                if self.logger:
                    self.logger.warning(
                        f"Signal high (mean={avg_mean:.0f}) but already at minimum exposure "
                        f"({self.current_exposure_ms:.1f}ms)"
                    )
                return False, None

        return False, None

    def adjust_exposure(self, direction: str) -> Optional[float]:
        """
        Adjust exposure to next preset in specified direction.

        Args:
            direction: 'increase' or 'decrease'

        Returns:
            New exposure value in milliseconds, or None if no adjustment made
        """
        if (
            direction == "increase"
            and self.current_preset_index < len(self.exposure_presets_ms) - 1
        ):
            self.current_preset_index += 1
        elif direction == "decrease" and self.current_preset_index > 0:
            self.current_preset_index -= 1
        else:
            return None

        old_exposure = self.current_exposure_ms
        self.current_exposure_ms = self.exposure_presets_ms[self.current_preset_index]
        self.last_adjustment_time = time.time()
        self.adjustment_count += 1

        # Clear statistics buffer after adjustment
        self.mean_buffer.clear()

        if self.logger:
            avg_mean = np.mean(list(self.mean_buffer)) if self.mean_buffer else 0
            self.logger.info(
                f"Auto-exposure adjustment #{self.adjustment_count}: "
                f"{old_exposure:.1f}ms -> {self.current_exposure_ms:.1f}ms "
                f"({direction}, mean={avg_mean:.0f})"
            )

        return self.current_exposure_ms

    def get_current_exposure(self) -> float:
        """
        Get current exposure setting.

        Returns:
            Current exposure in milliseconds
        """
        return self.current_exposure_ms

    def get_preset_info(self) -> Dict[str, Any]:
        """
        Get information about current preset state.

        Returns:
            Dictionary with preset information
        """
        return {
            "current_index": self.current_preset_index,
            "current_exposure_ms": self.current_exposure_ms,
            "total_presets": len(self.exposure_presets_ms),
            "all_presets": self.exposure_presets_ms,
            "can_increase": self.current_preset_index
            < len(self.exposure_presets_ms) - 1,
            "can_decrease": self.current_preset_index > 0,
            "adjustments_made": self.adjustment_count,
        }


class HyperspectralCameraBase(ABC):
    """
    Abstract base class for hyperspectral camera interfaces.
    Defines common interface that both Ximea and Lucid cameras must implement.
    """

    def __init__(self, json_path: str, logger):
        """
        Initialize camera base with configuration and logger.

        Args:
            json_path: Path to JSON configuration file
            logger: ROS 2 logger instance
        """
        self.logger = logger
        self.settings = {}
        self.load_settings(json_path)

    def load_settings(self, json_path: str) -> None:
        """
        Load camera settings from JSON configuration file.

        Args:
            json_path: Path to JSON configuration file

        Raises:
            FileNotFoundError: If JSON file does not exist
            ValueError: If JSON file cannot be parsed
        """
        if not os.path.exists(json_path):
            raise FileNotFoundError(f"Configuration file not found: {json_path}")

        try:
            with open(json_path, "r") as f:
                self.settings = json.load(f)
            self.logger.info(f"Loaded camera settings from: {json_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON file '{json_path}': {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to load settings from '{json_path}': {e}")

    @abstractmethod
    def connect_camera(self, serial_num: Optional[str] = None) -> None:
        """Connect to camera device."""
        pass

    @abstractmethod
    def configure_camera(self) -> None:
        """Configure camera parameters including binning, ROI, and exposure."""
        pass

    @abstractmethod
    def set_exposure(self, exposure_ms: float) -> None:
        """Set camera exposure time in milliseconds."""
        pass

    @abstractmethod
    def start_acquisition(self) -> None:
        """Start camera image acquisition."""
        pass

    @abstractmethod
    def stop_acquisition(self) -> None:
        """Stop camera image acquisition."""
        pass

    @abstractmethod
    def get_line_image(self) -> Tuple[Optional[np.ndarray], Optional[float]]:
        """
        Capture a single line scan image from the camera.

        Returns:
            Tuple of (image_array, capture_timestamp) or (None, None) on failure
        """
        pass

    @abstractmethod
    def get_temperature(self) -> float:
        """Get camera temperature in degrees Celsius."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close camera connection and cleanup resources."""
        pass


class XimeaHyperspectralCamera(HyperspectralCameraBase):
    """
    XIMEA hyperspectral camera interface.
    Handles camera initialization, configuration, and line capture with Headwall processing.
    """

    def __init__(self, json_path: str, logger, serial_num: Optional[str] = None):
        """
        Initialize XIMEA camera with hyperspectral configuration.

        Args:
            json_path: Path to JSON configuration file
            logger: ROS 2 logger instance
            serial_num: Optional camera serial number for specific device selection
        """
        super().__init__(json_path, logger)

        try:
            from ximea import xiapi

            self.xiapi = xiapi
        except ImportError:
            raise ImportError(
                "XIMEA API not available. Install: pip install ximea-py --break-system-packages"
            )

        self.xicam = self.xiapi.Camera()
        self.connect_camera(serial_num)
        self.configure_camera()
        self.img = self.xiapi.Image()

    def connect_camera(self, serial_num: Optional[str] = None) -> None:
        """
        Connect to XIMEA camera device.

        Args:
            serial_num: Optional serial number for specific camera selection

        Raises:
            RuntimeError: If camera connection fails
        """
        try:
            s_num_to_use = serial_num or self.settings.get("serial_num")
            if s_num_to_use:
                self.logger.info(f"Connecting to XIMEA camera S/N: {s_num_to_use}")
                self.xicam.open_device_by_SN(s_num_to_use)
            else:
                self.logger.info("Connecting to first available XIMEA camera")
                self.xicam.open_device()

            actual_sn = self.xicam.get_device_sn().decode("utf-8")
            self.settings["actual_serial_num"] = actual_sn
            self.logger.info(f"Successfully connected to XIMEA camera S/N: {actual_sn}")
        except self.xiapi.Xi_error as e:
            raise RuntimeError(f"Failed to connect to XIMEA camera: {e}")

    def configure_camera(self) -> None:
        """
        Configure XIMEA camera parameters including binning and ROI.
        Follows NASA principle: function under 60 lines with clear structure.

        Raises:
            RuntimeError: If configuration fails
        """
        try:
            if self.xicam.get_acquisition_status():
                self.xicam.stop_acquisition()

            # Step 1: Set hardware binning (must be done before ROI)
            bin_v = self.settings.get("binxy", [1, 1])[0]
            bin_h = self.settings.get("binxy", [1, 1])[1]
            if bin_v > 1 or bin_h > 1:
                self.logger.info(
                    f"Applying binning: Vertical={bin_v}, Horizontal={bin_h}"
                )
                self.xicam.set_param("binning_selector", "XI_BIN_SELECT_SENSOR")
                self.xicam.set_param("binning_vertical_mode", "XI_BIN_MODE_SUM")
                self.xicam.set_param("binning_horizontal_mode", "XI_BIN_MODE_SUM")
            self.xicam.set_binning_vertical(bin_v)
            self.xicam.set_binning_horizontal(bin_h)

            # Step 2: Reset ROI to full frame after binning
            max_w = self.xicam.get_width_maximum()
            max_h = self.xicam.get_height_maximum()
            self.xicam.set_offsetX(0)
            self.xicam.set_offsetY(0)
            self.xicam.set_width(max_w)
            self.xicam.set_height(max_h)

            # Step 3: Apply hardware ROI from settings
            self._apply_hardware_roi()

            # Step 4: Configure other camera parameters
            self.xicam.set_gain_direct(0.0)
            self.xicam.set_imgdataformat(self.settings["pixel_format"])
            self.xicam.disable_aeag()

            self.rows = self.xicam.get_height()
            self.cols = self.xicam.get_width()

            self.logger.info(
                f"Camera configured for {self.rows}x{self.cols} hardware capture"
            )
        except self.xiapi.Xi_error as e:
            raise RuntimeError(f"Failed to configure camera: {e}")

    def _apply_hardware_roi(self) -> None:
        """
        Apply hardware ROI settings from configuration.
        Helper method to keep configure_camera under 60 lines (NASA principle).
        """
        target_h = self.settings["win_resolution_h_hw_api"]
        target_w = self.settings["win_resolution_w_hw_api"]
        offset_y = self.settings["win_offset_y_hw_api"]
        offset_x = self.settings["win_offset_x_hw_api"]

        self.xicam.set_width(target_w)
        self.xicam.set_height(target_h)
        self.xicam.set_offsetX(offset_x)
        self.xicam.set_offsetY(offset_y)

        self.logger.info(
            f"XIMEA ROI: {self.xicam.get_height()}x{self.xicam.get_width()} "
            f"at offset ({self.xicam.get_offsetY()},{self.xicam.get_offsetX()})"
        )

        if not (
            self.xicam.get_height() == target_h and self.xicam.get_width() == target_w
        ):
            self.logger.warning("Actual camera resolution differs from target settings")

    def set_exposure(self, exposure_ms: float) -> None:
        """
        Set XIMEA camera exposure time in milliseconds.

        Args:
            exposure_ms: Desired exposure time in milliseconds
        """
        try:
            min_exp_us = self.xicam.get_exposure_minimum()
            max_exp_us = self.xicam.get_exposure_maximum()
            target_exp_us = float(exposure_ms) * 1000.0

            # Clamp exposure to valid range
            if target_exp_us < min_exp_us:
                self.logger.warning(
                    f"Exposure {exposure_ms:.2f}ms below minimum "
                    f"{min_exp_us/1000.0:.2f}ms. Clamping."
                )
                target_exp_us = min_exp_us
            elif target_exp_us > max_exp_us:
                self.logger.warning(
                    f"Exposure {exposure_ms:.2f}ms above maximum "
                    f"{max_exp_us/1000.0:.2f}ms. Clamping."
                )
                target_exp_us = max_exp_us

            self.xicam.set_exposure(int(target_exp_us))
            actual_exposure_us = self.xicam.get_exposure()
            self.settings["exposure_ms"] = actual_exposure_us / 1000.0
            self.logger.info(f"Exposure set to {self.settings['exposure_ms']:.2f} ms")
        except self.xiapi.Xi_error as e:
            self.logger.error(f"Failed to set exposure: {e}")

    def start_acquisition(self) -> None:
        """Start XIMEA camera acquisition."""
        try:
            self.xicam.start_acquisition()
            self.logger.info("XIMEA acquisition started")
        except self.xiapi.Xi_error as e:
            raise RuntimeError(f"Failed to start acquisition: {e}")

    def stop_acquisition(self) -> None:
        """Stop XIMEA camera acquisition."""
        try:
            if self.xicam.get_acquisition_status():
                self.xicam.stop_acquisition()
                self.logger.info("XIMEA acquisition stopped")
        except self.xiapi.Xi_error as e:
            self.logger.warning(f"Error stopping acquisition: {e}")

    def get_line_image(self) -> Tuple[Optional[np.ndarray], Optional[float]]:
        """
        Capture single line scan image from XIMEA camera.

        Returns:
            Tuple of (image_array, capture_timestamp) or (None, None) on failure
        """
        try:
            self.xicam.get_image(self.img)
            capture_time = time.time()
            raw_image = self.img.get_image_data_numpy()
            return raw_image, capture_time
        except self.xiapi.Xi_error as e:
            self.logger.error(f"Failed to capture image: {e}")
            return None, None

    def get_temperature(self) -> float:
        """
        Get XIMEA camera temperature.

        Returns:
            Temperature in degrees Celsius, or -1.0 on error
        """
        try:
            return self.xicam.get_temp()
        except self.xiapi.Xi_error as e:
            self.logger.warning(f"Failed to get temperature: {e}")
            return -1.0

    def close(self) -> None:
        """Close XIMEA camera connection and cleanup resources."""
        try:
            self.stop_acquisition()
            if hasattr(self, "xicam") and self.xicam.handle:
                self.xicam.close_device()
            self.logger.info("XIMEA camera closed successfully")
        except self.xiapi.Xi_error as e:
            self.logger.warning(f"Error closing camera: {e}")


class LucidHyperspectralCamera(HyperspectralCameraBase):
    """
    Lucid Vision Lab hyperspectral camera interface.
    Handles camera initialization, configuration, and line capture.
    """

    def __init__(self, json_path: str, logger, mac_addr: Optional[str] = None):
        """
        Initialize Lucid camera with hyperspectral configuration.

        Args:
            json_path: Path to JSON configuration file
            logger: ROS 2 logger instance
            mac_addr: Optional MAC address for specific device selection
        """
        super().__init__(json_path, logger)

        try:
            from arena_api.system import system as arsys
            from arena_api.system import DeviceNotFoundError

            self.arsys = arsys
            self.DeviceNotFoundError = DeviceNotFoundError
        except ImportError:
            raise ImportError(
                "Arena SDK not available. Install Lucid Arena SDK from thinklucid.com"
            )

        self.connect_camera(mac_addr)
        self.configure_camera()

    def connect_camera(self, mac_addr: Optional[str] = None) -> None:
        """
        Connect to Lucid camera device.

        Args:
            mac_addr: Optional MAC address for specific camera selection

        Raises:
            RuntimeError: If no camera found or connection fails
        """
        try:
            self.arsys.destroy_device()

            devices = self.arsys.create_device()
            if not devices:
                raise RuntimeError(
                    "No Lucid camera found. Please connect camera and retry."
                )

            self.device = devices[0]

            # Optimize stream settings
            tl_stream = self.device.tl_stream_nodemap
            tl_stream["StreamAutoNegotiatePacketSize"].value = True
            tl_stream["StreamPacketResendEnable"].value = True

            self.logger.info("Successfully connected to Lucid camera")
        except self.DeviceNotFoundError as e:
            raise RuntimeError(f"Lucid camera not found: {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Lucid camera: {e}")

    def configure_camera(self) -> None:
        """
        Configure Lucid camera parameters including binning, ROI, and exposure.

        Raises:
            RuntimeError: If configuration fails
        """
        try:
            # Initialize device settings access
            node_names = [
                "AcquisitionFrameRate",
                "AcquisitionFrameRateEnable",
                "AcquisitionMode",
                "AcquisitionStart",
                "AcquisitionStop",
                "BinningHorizontal",
                "BinningVertical",
                "DeviceTemperature",
                "DeviceUserID",
                "ExposureAuto",
                "ExposureTime",
                "Gain",
                "GammaEnable",
                "Height",
                "OffsetX",
                "OffsetY",
                "PixelFormat",
                "Width",
                "DeviceSerialNumber",
            ]
            self.device_settings = self.device.nodemap.get_node(node_names)

            # Set pixel format and binning
            self.device_settings["BinningHorizontal"].value = self.settings["binxy"][0]
            self.device_settings["PixelFormat"].value = self.settings["pixel_format"]

            # Reset to full frame
            self.device_settings["OffsetY"].value = 0
            self.device_settings["OffsetX"].value = 0
            self.device_settings["Height"].value = self.device_settings["Height"].max
            self.device_settings["Width"].value = self.device_settings["Width"].max

            # Apply ROI from settings
            self._apply_lucid_roi()

            # Configure exposure and gain
            self.device_settings["ExposureAuto"].value = "Off"
            self.device_settings["GammaEnable"].value = False
            self.set_gain(0.0)

            self.rows = self.device_settings["Height"].value
            self.cols = self.device_settings["Width"].value

            self.settings["camera_id"] = self.device_settings["DeviceUserID"].value

            self.logger.info(
                f"Lucid camera configured for {self.rows}x{self.cols} capture"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to configure Lucid camera: {e}")

    def _apply_lucid_roi(self) -> None:
        """
        Apply ROI settings for Lucid camera.
        Helper method to maintain function size limits.
        """
        win_res = self.settings["win_resolution"]
        win_off = self.settings["win_offset"]

        # Set height and width
        self.device_settings["Height"].value = (
            win_res[0] if win_res[0] > 0 else self.device_settings["Height"].max
        )
        self.device_settings["Width"].value = (
            win_res[1] if win_res[1] > 0 else self.device_settings["Width"].max
        )

        # Set offsets
        self.device_settings["OffsetY"].value = win_off[0] if win_off[0] > 0 else 0
        self.device_settings["OffsetX"].value = win_off[1] if win_off[1] > 0 else 0

        self.logger.info(
            f"Lucid ROI: {self.device_settings['Height'].value}x"
            f"{self.device_settings['Width'].value} at offset "
            f"({self.device_settings['OffsetY'].value},"
            f"{self.device_settings['OffsetX'].value})"
        )

    def set_exposure(self, exposure_ms: float) -> None:
        """
        Set Lucid camera exposure time in milliseconds.

        Args:
            exposure_ms: Desired exposure time in milliseconds
        """
        try:
            min_exp_us = self.device_settings["ExposureTime"].min
            exposure_us = max(exposure_ms * 1000.0, min_exp_us)

            # Calculate and set frame rate
            nominal_framerate = 1_000_000.0 / exposure_us * 0.98

            if nominal_framerate < self.device_settings["AcquisitionFrameRate"].max:
                self.device_settings["AcquisitionFrameRateEnable"].value = True
                self.device_settings["AcquisitionFrameRate"].value = nominal_framerate
            else:
                self.device_settings["AcquisitionFrameRateEnable"].value = False

            self.device_settings["ExposureTime"].value = exposure_us
            self.settings["exposure_ms"] = (
                self.device_settings["ExposureTime"].value / 1000.0
            )

            self.logger.info(f"Exposure set to {self.settings['exposure_ms']:.2f} ms")
        except Exception as e:
            self.logger.error(f"Failed to set exposure: {e}")

    def set_gain(self, gain_val: float) -> None:
        """
        Set Lucid camera gain value.

        Args:
            gain_val: Gain value to set
        """
        try:
            self.device_settings["Gain"].value = float(gain_val)
        except Exception as e:
            self.logger.warning(f"Failed to set gain: {e}")

    def start_acquisition(self) -> None:
        """Start Lucid camera acquisition."""
        try:
            self.device.start_stream(1)
            self.logger.info("Lucid acquisition started")
        except Exception as e:
            raise RuntimeError(f"Failed to start acquisition: {e}")

    def stop_acquisition(self) -> None:
        """Stop Lucid camera acquisition."""
        try:
            self.device.stop_stream()
            self.logger.info("Lucid acquisition stopped")
        except Exception as e:
            self.logger.warning(f"Error stopping acquisition: {e}")

    def get_line_image(self) -> Tuple[Optional[np.ndarray], Optional[float]]:
        """
        Capture single line scan image from Lucid camera.

        Returns:
            Tuple of (image_array, capture_timestamp) or (None, None) on failure
        """
        try:
            image_buffer = self.device.get_buffer()
            capture_time = time.time()

            # Process buffer based on bit depth
            nparray = self._process_lucid_buffer(image_buffer)

            self.device.requeue_buffer(image_buffer)
            return nparray, capture_time
        except Exception as e:
            self.logger.error(f"Failed to capture image: {e}")
            return None, None

    def _process_lucid_buffer(self, image_buffer) -> np.ndarray:
        """
        Process Lucid camera buffer based on pixel format bit depth.

        Args:
            image_buffer: Arena buffer object

        Returns:
            Processed numpy array
        """
        bits_per_pixel = image_buffer.bits_per_pixel
        height = image_buffer.height
        width = image_buffer.width

        if bits_per_pixel == 8:
            nparray = np.ctypeslib.as_array(image_buffer.pdata, (height, width)).copy()

        elif bits_per_pixel in (10, 12):
            split = np.ctypeslib.as_array(
                image_buffer.pdata, (image_buffer.buffer_size, 1)
            ).astype(np.uint16)
            fst_uint12 = (split[0::3] << 4) + (split[1::3] >> 4)
            snd_uint12 = (split[2::3] << 4) + (np.bitwise_and(15, split[1::3]))
            nparray = np.reshape(
                np.concatenate((fst_uint12[:, None], snd_uint12[:, None]), axis=1),
                (height, width),
            )

        elif bits_per_pixel == 16:
            pdata_as16 = ctypes.cast(
                image_buffer.pdata, ctypes.POINTER(ctypes.c_ushort)
            )
            nparray = np.ctypeslib.as_array(pdata_as16, (height, width)).copy()

        else:
            raise ValueError(f"Unsupported bit depth: {bits_per_pixel}")

        return nparray

    def get_temperature(self) -> float:
        """
        Get Lucid camera temperature.

        Returns:
            Temperature in degrees Celsius, or -1.0 on error
        """
        try:
            return self.device_settings["DeviceTemperature"].value
        except Exception as e:
            self.logger.warning(f"Failed to get temperature: {e}")
            return -1.0

    def close(self) -> None:
        """Close Lucid camera connection and cleanup resources."""
        try:
            self.stop_acquisition()
            if hasattr(self, "arsys"):
                self.arsys.destroy_device()
            self.logger.info("Lucid camera closed successfully")
        except Exception as e:
            self.logger.warning(f"Error closing camera: {e}")


def software_crop_image(image: np.ndarray, settings: Dict[str, Any]) -> np.ndarray:
    """
    @brief Apply software cropping to raw camera image based on settings.

    This function handles both Ximea Headwall cropping and Lucid custom cropping.

    @param image Raw camera image array
    @param settings Camera settings dictionary containing crop parameters
    @return Cropped and transposed image array
    @pre image must be 2D numpy array
    @pre settings must be dictionary
    """
    # Validate inputs (NASA assertion principle)
    assert isinstance(image, np.ndarray), "image must be numpy array"
    assert image.ndim == 2, f"image must be 2D, got {image.ndim}D"
    assert isinstance(settings, dict), "settings must be dictionary"

    # Determine if using Ximea Headwall parameters or generic crop parameters
    if "headwall_spectral_offset_fullsensor_px" in settings:
        # Ximea Headwall cropping
        hw_offset_y = settings["win_offset_y_hw_api"]
        hw_offset_x = settings["win_offset_x_hw_api"]
        spectral_start = settings["headwall_spectral_offset_fullsensor_px"]
        spectral_size = settings["headwall_spectral_size_px"]
        spatial_start = settings["headwall_spatial_offset_fullsensor_px"]
        spatial_size = settings["headwall_spatial_size_px"]

        start_y = spectral_start - hw_offset_y
        end_y = start_y + spectral_size
        start_x = spatial_start - hw_offset_x
        end_x = start_x + spatial_size
    else:
        # Generic cropping for Lucid or other cameras
        start_y = settings.get("crop_offset_y", 0)
        start_x = settings.get("crop_offset_x", 0)
        crop_height = settings.get("crop_height", image.shape[0])
        crop_width = settings.get("crop_width", image.shape[1])

        end_y = start_y + crop_height
        end_x = start_x + crop_width

    cropped = image[start_y:end_y, start_x:end_x]
    return cropped.T


def apply_calibration(
    image: np.ndarray,
    calibration_data: Optional[Dict],
    processing_lvl: int = 0,
    exposure_ms: float = 10.0,
    logger=None
) -> np.ndarray:
    """
    @brief Apply calibration correction to image based on processing level.

    Processing levels:
        0: Raw digital numbers (no processing)
        1: Dark-subtracted
        2: Flat-field corrected
        3: Spectral radiance (μW/cm²/sr/nm)
        4: Reflectance (requires reference panel - not yet implemented)

    @param image Input image array (cross_track × wavelength)
    @param calibration_data Calibration data dictionary from NetCDF file
    @param processing_lvl Desired processing level (0-4)
    @param exposure_ms Exposure time in milliseconds
    @param logger Optional logger for warnings
    @return Calibrated image array
    @pre image must be 2D numpy array
    @pre processing_lvl must be in range [0, 4]
    @pre exposure_ms must be positive
    """
    # Validate inputs (NASA assertion principle)
    assert isinstance(image, np.ndarray), "image must be numpy array"
    assert image.ndim == 2, f"image must be 2D, got {image.ndim}D"
    assert 0 <= processing_lvl <= 4, f"processing_lvl must be 0-4, got {processing_lvl}"
    assert exposure_ms > 0, f"exposure_ms must be positive, got {exposure_ms}"

    if calibration_data is not None:
        assert isinstance(calibration_data, dict), "calibration_data must be dict"

    if calibration_data is None or processing_lvl == 0:
        return image

    try:
        # Processing level 1: Dark subtraction (not implemented yet - placeholder)
        if processing_lvl >= 1:
            # TODO: Implement dark frame subtraction
            # Would require dark frames in calibration data
            pass

        # Processing level 2: Flat field correction
        if processing_lvl >= 2:
            if 'flat_field_pic' in calibration_data:
                flat_field = calibration_data['flat_field_pic']

                # Ensure flat field matches image shape
                if flat_field.shape == image.shape:
                    # Normalize by flat field (avoid divide by zero)
                    flat_field_safe = np.where(flat_field > 0, flat_field, 1)
                    image = image.astype(np.float32) / flat_field_safe.astype(np.float32)
                    image = (image * np.mean(flat_field_safe)).astype(image.dtype)
                elif logger:
                    logger.warning(
                        f"Flat field shape {flat_field.shape} doesn't match "
                        f"image shape {image.shape}. Skipping flat field correction."
                    )

        # Processing level 3: Radiance calibration
        if processing_lvl >= 3:
            if 'rad_ref' in calibration_data and 'sfit_y' in calibration_data:
                # Convert to radiance using calibration data
                # This is a simplified version - full implementation would use rad_ref cube
                # and interpolate based on exposure time

                # Get spectral radiance reference
                if 'sfit_y' in calibration_data:
                    spec_rad_ref = calibration_data['sfit_y']

                    # Simple scaling (proper implementation would use rad_ref cube)
                    # radiance = (DN / flat_field) * spec_rad_ref / exposure_time
                    image = image.astype(np.float32) * spec_rad_ref.astype(np.float32)
                elif logger:
                    logger.warning("Spectral radiance data not found in calibration")

        # Processing level 4: Reflectance (placeholder)
        if processing_lvl >= 4:
            if logger:
                logger.warning("Reflectance conversion not yet implemented")
            # TODO: Implement reflectance conversion using reference panel

        return image

    except Exception as e:
        if logger:
            logger.error(f"Error applying calibration: {e}")
        return image


class FrameQueue:
    """
    @brief Thread-safe bounded queue for frame buffering.

    Implements drop-oldest policy when full to prevent memory overflow
    while maintaining real-time performance. Follows NASA principle of
    bounded data structures with clear capacity limits.
    """

    def __init__(self, maxsize: int = 10):
        """
        @brief Initialize frame queue with maximum capacity.

        @param maxsize Maximum number of frames to buffer
        @pre maxsize must be positive integer
        @post Queue initialized with bounded capacity
        """
        assert maxsize > 0, "maxsize must be positive"

        self._queue = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        self._maxsize = maxsize
        self._dropped_count = 0

    def put(self, frame: np.ndarray, timestamp: float) -> bool:
        """
        @brief Add frame to queue with drop-oldest policy.

        Non-blocking operation that drops oldest frame if queue full.
        Prevents producer thread from blocking on camera I/O timing.

        @param frame Image frame array
        @param timestamp Frame capture timestamp
        @return True if frame added, False if queue was full
        @pre frame must be valid numpy array
        @post Frame added to queue or oldest frame replaced
        """
        assert isinstance(frame, np.ndarray), "frame must be numpy array"
        assert timestamp > 0, "timestamp must be positive"

        try:
            # Try non-blocking put
            self._queue.put_nowait((frame, timestamp))
            return True
        except queue.Full:
            # Queue full - drop oldest frame and add new one
            with self._lock:
                try:
                    self._queue.get_nowait()  # Remove oldest
                    self._dropped_count += 1
                    self._queue.put_nowait((frame, timestamp))
                    return False
                except (queue.Empty, queue.Full):
                    return False

    def get(self, timeout: Optional[float] = None) -> Optional[Tuple[np.ndarray, float]]:
        """
        @brief Retrieve frame from queue.

        @param timeout Maximum wait time in seconds (None = indefinite)
        @return Tuple of (frame, timestamp) or None if timeout
        @post Frame removed from queue if available
        """
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def qsize(self) -> int:
        """
        @brief Get approximate queue size.

        @return Current number of frames in queue
        """
        return self._queue.qsize()

    def get_dropped_count(self) -> int:
        """
        @brief Get count of dropped frames.

        @return Total number of frames dropped due to full queue
        """
        return self._dropped_count


class CameraAcquisitionThread:
    """
    @brief Dedicated thread for real-time camera frame acquisition.

    Runs camera I/O in separate thread with precise timing control,
    decoupled from ROS processing pipeline. Follows NASA principles:
    - Bounded loop with clear termination
    - Simple control flow
    - Thread-safe communication via bounded queue
    """

    def __init__(
        self,
        camera,
        frame_queue: FrameQueue,
        capture_frequency: float,
        logger
    ):
        """
        @brief Initialize camera acquisition thread.

        @param camera Camera interface object
        @param frame_queue Thread-safe queue for frame buffering
        @param capture_frequency Target capture rate in Hz
        @param logger ROS logger for diagnostics
        @pre capture_frequency must be positive
        @post Thread initialized but not started
        """
        assert capture_frequency > 0, "capture_frequency must be positive"
        assert isinstance(frame_queue, FrameQueue), "frame_queue must be FrameQueue"

        self.camera = camera
        self.frame_queue = frame_queue
        self.capture_period = 1.0 / capture_frequency
        self.logger = logger

        self._running = False
        self._thread = None
        self._frame_count = 0
        self._error_count = 0

    def start(self) -> None:
        """
        @brief Start acquisition thread.

        @pre Camera must be initialized
        @post Thread running with camera acquisition active
        """
        if self._running:
            self.logger.warning("Acquisition thread already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._acquisition_loop, daemon=True)
        self._thread.start()
        self.logger.info("Camera acquisition thread started")

    def stop(self) -> None:
        """
        @brief Stop acquisition thread gracefully.

        @post Thread stopped and resources cleaned up
        """
        if not self._running:
            return

        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self.logger.info(
                f"Camera acquisition thread stopped. "
                f"Captured {self._frame_count} frames, {self._error_count} errors"
            )

    def _acquisition_loop(self) -> None:
        """
        @brief Main acquisition loop running in dedicated thread.

        Bounded loop with clear termination condition (self._running).
        Maintains precise timing for camera frame capture.

        @post Frames continuously acquired and queued while running
        """
        next_capture_time = time.time()

        # Bounded loop with clear exit condition (NASA guideline compliance)
        while self._running:
            try:
                # Precise timing control
                current_time = time.time()
                if current_time < next_capture_time:
                    sleep_time = next_capture_time - current_time
                    if sleep_time > 0.0001:  # Avoid unnecessary sleeps
                        time.sleep(sleep_time)

                # Acquire frame
                raw_image, timestamp = self.camera.get_line_image()

                if raw_image is not None:
                    # Add to queue (non-blocking)
                    added = self.frame_queue.put(raw_image, timestamp)
                    self._frame_count += 1

                    if not added and self._frame_count % 100 == 0:
                        self.logger.warning(
                            f"Frame queue full, dropped frame "
                            f"(total dropped: {self.frame_queue.get_dropped_count()})"
                        )
                else:
                    self._error_count += 1

                # Calculate next capture time
                next_capture_time += self.capture_period

            except Exception as e:
                self._error_count += 1
                self.logger.error(f"Error in acquisition loop: {e}")
                time.sleep(0.1)  # Brief pause on error


class HyperspectralROS2Node(Node):
    """
    ROS 2 node for hyperspectral line scan data acquisition and publishing.
    Supports both Ximea and Lucid cameras with unified interface.
    """

    def __init__(self):
        """
        @brief Initialize ROS 2 hyperspectral camera node.

        Automatically selects timer-based or threaded acquisition based on
        capture frequency: <50 Hz uses timer, >=50 Hz uses dedicated thread.

        @post Node initialized with appropriate capture mode
        """
        super().__init__("hyperspec_camera")

        self.get_logger().info("Starting hyperspectral camera node...")

        self.shape_warning_logged = False
        self.calibration_data = None

        # Threading-related attributes
        self.use_threaded_capture = False
        self.frame_queue = None
        self.acquisition_thread = None
        self.capture_timer = None
        self.processing_timer = None

        self.declare_and_load_parameters()
        self.initialize_camera()
        self.calculate_wavelengths()
        self.load_calibration_data()
        self.setup_publishers_and_subscribers()

        self.bridge = CvBridge()

        self.camera.start_acquisition()

        # Determine capture mode based on frequency
        # Use threaded mode for high frame rates (>=50 Hz)
        self.use_threaded_capture = self.capture_frequency >= 50.0

        if self.use_threaded_capture:
            self._init_threaded_capture()
        else:
            self._init_timer_capture()

        # Create timer for wavelength publishing (1 Hz)
        self.wavelength_timer = self.create_timer(1.0, self.publish_wavelengths)

        self.get_logger().info("Hyperspectral camera node initialized successfully")
        mode_str = "THREADED" if self.use_threaded_capture else "TIMER"
        self.get_logger().info(
            f"Mode: {mode_str} | Publishing at {self.capture_frequency} Hz "
            f"on topic 'hyperspec/image_raw'"
        )

    def _init_timer_capture(self) -> None:
        """
        @brief Initialize timer-based capture mode.

        Used for low to medium frame rates (<50 Hz) where camera I/O
        fits within ROS timer callback budget.

        @post Timer callback created for periodic frame capture
        """
        self.capture_timer = self.create_timer(
            1.0 / self.capture_frequency, self.capture_callback
        )
        self.get_logger().info(
            f"Initialized TIMER-based capture at {self.capture_frequency:.1f} Hz"
        )

    def _init_threaded_capture(self) -> None:
        """
        @brief Initialize threaded capture mode.

        Used for high frame rates (>=50 Hz) where dedicated acquisition
        thread prevents timer jitter and missed frames.

        @post Acquisition thread and processing callback initialized
        """
        # Create frame queue with reasonable buffer size
        queue_size = min(int(self.capture_frequency * 0.5), 50)  # 0.5s buffer
        self.frame_queue = FrameQueue(maxsize=queue_size)

        # Create acquisition thread
        self.acquisition_thread = CameraAcquisitionThread(
            camera=self.camera,
            frame_queue=self.frame_queue,
            capture_frequency=self.capture_frequency,
            logger=self.get_logger()
        )

        # Start acquisition thread
        self.acquisition_thread.start()

        # Create processing timer (runs slightly faster than capture rate)
        processing_hz = self.capture_frequency * 1.1
        self.processing_timer = self.create_timer(
            1.0 / processing_hz, self._processing_callback
        )

        self.get_logger().info(
            f"Initialized THREADED capture at {self.capture_frequency:.1f} Hz "
            f"(queue size: {queue_size}, processing: {processing_hz:.1f} Hz)"
        )

    def declare_and_load_parameters(self) -> None:
        """
        Declare and load ROS 2 parameters.
        Follows NASA principle: clear parameter validation and error handling.
        """
        # Declare parameters with default values
        self.declare_parameter("camera_type", "ximea")
        self.declare_parameter("config_file", "")
        self.declare_parameter("calibration_file", "")
        self.declare_parameter("processing_lvl", 0)
        self.declare_parameter("cap_hz", 10.0)
        self.declare_parameter("exposure_ms", 10.0)
        self.declare_parameter("serial_number", "")
        self.declare_parameter("mac_address", "")

        # Auto-exposure parameters
        self.declare_parameter("auto_exposure_enable", False)
        self.declare_parameter("auto_exposure_low_threshold", 500.0)
        self.declare_parameter("auto_exposure_high_threshold", 3000.0)
        self.declare_parameter("auto_exposure_window_sec", 5.0)
        self.declare_parameter("auto_exposure_min_samples", 10)

        # Get parameter values
        self.camera_type = self.get_parameter("camera_type").value.lower()
        self.config_path = self.get_parameter("config_file").value
        self.calibration_path = self.get_parameter("calibration_file").value
        self.processing_lvl = self.get_parameter("processing_lvl").value
        self.capture_frequency = self.get_parameter("cap_hz").value
        self.initial_exposure_ms = self.get_parameter("exposure_ms").value
        self.serial_number = self.get_parameter("serial_number").value
        self.mac_address = self.get_parameter("mac_address").value

        # Auto-exposure parameters
        self.auto_exposure_enabled = self.get_parameter("auto_exposure_enable").value
        self.auto_exp_low_threshold = self.get_parameter(
            "auto_exposure_low_threshold"
        ).value
        self.auto_exp_high_threshold = self.get_parameter(
            "auto_exposure_high_threshold"
        ).value
        self.auto_exp_window = self.get_parameter("auto_exposure_window_sec").value
        self.auto_exp_min_samples = self.get_parameter(
            "auto_exposure_min_samples"
        ).value

        # Validate parameters
        if self.camera_type not in ["ximea", "lucid"]:
            raise ValueError(
                f"Invalid camera_type '{self.camera_type}'. Must be 'ximea' or 'lucid'"
            )

        if not self.config_path:
            raise ValueError("config_file parameter is required")

        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        if self.capture_frequency <= 0:
            raise ValueError("cap_hz must be positive")

        if self.initial_exposure_ms <= 0:
            raise ValueError("exposure_ms must be positive")

        if self.auto_exp_low_threshold >= self.auto_exp_high_threshold:
            raise ValueError(
                "auto_exposure_low_threshold must be less than auto_exposure_high_threshold"
            )

        if self.processing_lvl < 0 or self.processing_lvl > 4:
            raise ValueError("processing_lvl must be between 0 and 4")

        self.get_logger().info("--- Hyperspectral Parameters ---")
        self.get_logger().info(f"  Camera type: {self.camera_type}")
        self.get_logger().info(f"  Config file: {self.config_path}")
        self.get_logger().info(f"  Calibration file: {self.calibration_path if self.calibration_path else 'None'}")
        self.get_logger().info(f"  Processing level: {self.processing_lvl}")
        self.get_logger().info(f"  Capture frequency: {self.capture_frequency:.2f} Hz")
        self.get_logger().info(f"  Initial exposure: {self.initial_exposure_ms:.2f} ms")
        self.get_logger().info(
            f"  Auto-exposure: {'ENABLED' if self.auto_exposure_enabled else 'DISABLED'}"
        )
        if self.auto_exposure_enabled:
            self.get_logger().info(
                f"    Thresholds: {self.auto_exp_low_threshold:.0f} - {self.auto_exp_high_threshold:.0f}"
            )
            self.get_logger().info(f"    Window: {self.auto_exp_window:.1f}s")
        self.get_logger().info("--------------------------------")

    def initialize_camera(self) -> None:
        """
        Initialize camera based on type parameter.

        Raises:
            RuntimeError: If camera initialization fails
        """
        try:
            if self.camera_type == "ximea":
                serial = self.serial_number if self.serial_number else None
                self.camera = XimeaHyperspectralCamera(
                    self.config_path, self.get_logger(), serial_num=serial
                )
            elif self.camera_type == "lucid":
                mac = self.mac_address if self.mac_address else None
                self.camera = LucidHyperspectralCamera(
                    self.config_path, self.get_logger(), mac_addr=mac
                )
            else:
                raise ValueError(f"Unsupported camera type: {self.camera_type}")

            # Initialize auto-exposure controller if enabled
            self.auto_exposure_controller = None
            if self.auto_exposure_enabled:
                # Get exposure presets from config, or create default array
                exposure_presets = self.camera.settings.get(
                    "exposure_presets_ms",
                    [5.0, 8.0, 10.0, 12.0, 16.0, 20.0, 25.0, 30.0, 40.0, 50.0],
                )

                self.auto_exposure_controller = AutoExposureController(
                    exposure_presets_ms=exposure_presets,
                    initial_exposure_ms=self.initial_exposure_ms,
                    low_signal_threshold=self.auto_exp_low_threshold,
                    high_signal_threshold=self.auto_exp_high_threshold,
                    evaluation_window_sec=self.auto_exp_window,
                    min_samples_for_decision=self.auto_exp_min_samples,
                    logger=self.get_logger(),
                )

                # Set initial exposure from controller
                self.initial_exposure_ms = (
                    self.auto_exposure_controller.get_current_exposure()
                )
                self.get_logger().info(
                    f"Auto-exposure controller initialized with {len(exposure_presets)} presets"
                )

            self.camera.set_exposure(self.initial_exposure_ms)

            # Get expected final shape after cropping
            self.final_shape_expected = tuple(
                self.camera.settings.get(
                    "final_image_shape_after_crop",
                    self.camera.settings.get("resolution", [1024, 343]),
                )
            )

            self.get_logger().info(
                f"Camera initialized. Expected final shape: {self.final_shape_expected}"
            )
        except Exception as e:
            self.get_logger().fatal(
                f"CRITICAL: Camera initialization failed. Error: {e}"
            )
            raise RuntimeError(f"Camera initialization failed: {e}")

    def calculate_wavelengths(self) -> None:
        """
        Calculate wavelength array from camera settings.
        Uses either Headwall parameters or custom wavelength calibration.

        Raises:
            KeyError: If required wavelength parameters are missing
        """
        settings = self.camera.settings

        try:
            # Check if using Headwall wavelength parameters (Ximea)
            if "headwall_spectral_size_px" in settings:
                num_pixels = settings["headwall_spectral_size_px"]
                offset = settings["headwall_spectral_offset_fullsensor_px"]
                dispersion = settings["headwall_pixel_dispersion_nm_px"]
                wl_start = settings["headwall_pixel0_wavelength_nm"]

                indices = offset + np.arange(num_pixels)
                self.wavelengths = (wl_start + indices * dispersion).astype(np.float32)
                self.pixel_dispersion = dispersion

            # Check for custom wavelength array (Lucid or other)
            elif "wavelength_array" in settings:
                self.wavelengths = np.array(
                    settings["wavelength_array"], dtype=np.float32
                )
                self.pixel_dispersion = settings.get("pixel_dispersion_nm_px", 1.0)

            # Calculate from start, end, and number of bands
            elif all(
                k in settings
                for k in [
                    "wavelength_start_nm",
                    "wavelength_end_nm",
                    "num_spectral_bands",
                ]
            ):
                wl_start = settings["wavelength_start_nm"]
                wl_end = settings["wavelength_end_nm"]
                num_bands = settings["num_spectral_bands"]

                self.wavelengths = np.linspace(
                    wl_start, wl_end, num_bands, dtype=np.float32
                )
                self.pixel_dispersion = (wl_end - wl_start) / (num_bands - 1)

            else:
                raise KeyError(
                    "Settings must contain wavelength calibration parameters. "
                    "Expected: 'headwall_*' parameters OR 'wavelength_array' OR "
                    "'wavelength_start_nm/wavelength_end_nm/num_spectral_bands'"
                )

            self.get_logger().info(
                f"Generated {len(self.wavelengths)} wavelengths: "
                f"{self.wavelengths[0]:.2f} nm to {self.wavelengths[-1]:.2f} nm"
            )
        except KeyError as e:
            self.get_logger().fatal(
                f"CRITICAL: Missing wavelength parameter in settings: {e}"
            )
            raise

    def load_calibration_data(self) -> None:
        """
        Load calibration data from NetCDF file.

        Expected calibration file format (.nc):
            - wavelengths: 1D array of wavelengths (nm)
            - wavelengths_linear: 1D array of linear wavelength fit
            - smile_shifts: 1D array of smile correction shifts
            - flat_field_pic: 2D array (cross_track × wavelength)
            - HgAr_pic: 2D array of HgAr calibration spectrum
            - rad_ref: 4D array (cross_track × wavelength × exposure × luminance)
            - sfit_x, sfit_y: Spectral radiance interpolation data
            - spec_rad_ref_luminance: Reference luminance value
        """
        if not self.calibration_path or not os.path.exists(self.calibration_path):
            self.get_logger().info(
                "No calibration file specified or file not found. "
                "Operating without calibration correction."
            )
            self.calibration_data = None
            return

        try:
            # Check if xarray is available
            try:
                import xarray as xr
            except ImportError:
                self.get_logger().error(
                    "xarray not installed. Install with: "
                    "pip3 install xarray netcdf4 --break-system-packages"
                )
                self.calibration_data = None
                return

            # Load NetCDF calibration file
            ds = xr.open_dataset(self.calibration_path)

            # Convert to dictionary of numpy arrays for easier access
            self.calibration_data = {}

            # Load all data variables
            for var_name in ds.data_vars:
                self.calibration_data[var_name] = ds[var_name].values

            # Load attributes
            for attr_name, attr_value in ds.attrs.items():
                self.calibration_data[attr_name] = attr_value

            ds.close()

            # Log loaded calibration info
            self.get_logger().info(
                f"Loaded calibration data from: {self.calibration_path}"
            )
            self.get_logger().info(
                f"  Contains: {', '.join(self.calibration_data.keys())}"
            )

            if 'wavelengths' in self.calibration_data:
                wl = self.calibration_data['wavelengths']
                self.get_logger().info(
                    f"  Wavelength range: {wl[0]:.1f} - {wl[-1]:.1f} nm "
                    f"({len(wl)} bands)"
                )

            if 'flat_field_pic' in self.calibration_data:
                ff_shape = self.calibration_data['flat_field_pic'].shape
                self.get_logger().info(f"  Flat field shape: {ff_shape}")

            if 'rad_ref' in self.calibration_data:
                rr_shape = self.calibration_data['rad_ref'].shape
                self.get_logger().info(f"  Radiance reference cube shape: {rr_shape}")

        except Exception as e:
            self.get_logger().error(
                f"Failed to load calibration file: {e}. "
                "Operating without calibration correction."
            )
            import traceback
            self.get_logger().error(traceback.format_exc())
            self.calibration_data = None

    def setup_publishers_and_subscribers(self) -> None:
        """Setup ROS 2 publishers and subscribers for camera topics."""
        # Publishers
        self.image_pub = self.create_publisher(Image, "hyperspec/image_raw", 10)
        self.camera_info_pub = self.create_publisher(
            CameraInfo, "hyperspec/camera_info", 10
        )
        self.exposure_info_pub = self.create_publisher(
            Float64MultiArray, "hyperspec/exposure_info", 10
        )
        self.exposure_ms_pub = self.create_publisher(
            Float64, "hyperspec/exposure_ms", 10
        )
        self.temperature_pub = self.create_publisher(
            Float64, "hyperspec/temperature", 10
        )
        self.wavelengths_pub = self.create_publisher(
            Float64MultiArray, "hyperspec/wavelengths", 10
        )
        self.auto_exposure_status_pub = self.create_publisher(
            String, "hyperspec/auto_exposure_status", 10
        )

        # Subscribers
        self.exposure_sub = self.create_subscription(
            Float64, "hyperspec/set_exposure_ms", self.set_exposure_callback, 10
        )
        self.auto_exposure_enable_sub = self.create_subscription(
            String,
            "hyperspec/auto_exposure_control",
            self.auto_exposure_control_callback,
            10,
        )

        self.get_logger().info("ROS 2 publishers and subscribers created")

    def set_exposure_callback(self, msg: Float64) -> None:
        """
        Callback for exposure control topic.

        Args:
            msg: Float64 message containing desired exposure in milliseconds
        """
        self.get_logger().info(f"Received request to set exposure to {msg.data:.2f} ms")
        self.camera.set_exposure(msg.data)

        # Update auto-exposure controller if active
        if self.auto_exposure_controller:
            # Find closest preset and update controller
            preset_index = self.auto_exposure_controller._find_closest_preset_index(
                msg.data
            )
            self.auto_exposure_controller.current_preset_index = preset_index
            self.auto_exposure_controller.current_exposure_ms = (
                self.auto_exposure_controller.exposure_presets_ms[preset_index]
            )
            self.auto_exposure_controller.mean_buffer.clear()
            self.get_logger().info(
                f"Auto-exposure controller updated to preset index {preset_index}"
            )

    def auto_exposure_control_callback(self, msg: String) -> None:
        """
        Callback for auto-exposure enable/disable control.

        Args:
            msg: String message with commands: 'enable', 'disable', 'status'
        """
        command = msg.data.lower().strip()

        if command == "enable":
            if self.auto_exposure_controller:
                self.auto_exposure_enabled = True
                self.get_logger().info("Auto-exposure ENABLED")
            else:
                self.get_logger().warning(
                    "Cannot enable auto-exposure: controller not initialized"
                )

        elif command == "disable":
            self.auto_exposure_enabled = False
            self.get_logger().info("Auto-exposure DISABLED")

        elif command == "status":
            if self.auto_exposure_controller:
                info = self.auto_exposure_controller.get_preset_info()
                status_msg = (
                    f"Auto-exposure {'ENABLED' if self.auto_exposure_enabled else 'DISABLED'}\n"
                    f"  Current: {info['current_exposure_ms']:.1f}ms "
                    f"(preset {info['current_index']+1}/{info['total_presets']})\n"
                    f"  Presets: {info['all_presets']}\n"
                    f"  Adjustments made: {info['adjustments_made']}"
                )
                self.get_logger().info(status_msg)
            else:
                self.get_logger().info("Auto-exposure not initialized")

        else:
            self.get_logger().warning(
                f"Unknown auto-exposure command: '{command}'. "
                "Valid commands: 'enable', 'disable', 'status'"
            )

    def analyse_image_stats(self, image: np.ndarray) -> Tuple[float, float, float]:
        """
        Calculate image statistics for diagnostic purposes.

        Args:
            image: Input image array

        Returns:
            Tuple of (variance, mean, median)
        """
        img_float = image.astype(np.float64)
        variance = np.var(img_float)
        mean = np.mean(img_float)
        median = np.median(img_float)
        return variance, mean, median

    def create_camera_info_msg(self, header: Header) -> CameraInfo:
        """
        Create CameraInfo message with calibration parameters.

        Args:
            header: ROS 2 header with timestamp and frame_id

        Returns:
            CameraInfo message
        """
        ci = CameraInfo()
        ci.header = header
        ci.height = self.final_shape_expected[1]
        ci.width = self.final_shape_expected[0]
        ci.distortion_model = "plumb_bob"
        ci.d = [0.0, 0.0, 0.0, 0.0, 0.0]
        ci.k = [1.0, 0.0, ci.width / 2.0, 0.0, 1.0, ci.height / 2.0, 0.0, 0.0, 1.0]
        ci.r = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
        ci.p = [
            1.0,
            0.0,
            ci.width / 2.0,
            0.0,
            0.0,
            1.0,
            ci.height / 2.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
        ]
        return ci

    def _acquire_frame(self) -> Tuple[Optional[np.ndarray], Optional[float]]:
        """
        @brief Acquire single frame from camera.

        @return Tuple of (image_array, timestamp) or (None, None) on failure
        @post Returns raw image data from camera sensor
        """
        raw_image, capture_time = self.camera.get_line_image()
        return raw_image, capture_time

    def _process_frame(self, raw_image: np.ndarray) -> np.ndarray:
        """
        @brief Apply cropping and calibration to raw camera image.

        @param raw_image Raw image from camera sensor
        @return Processed image after cropping and calibration
        @pre raw_image must be valid numpy array
        @post Returns calibrated image matching expected output shape
        """
        assert isinstance(raw_image, np.ndarray), "raw_image must be numpy array"

        # Apply software cropping
        processed = software_crop_image(raw_image, self.camera.settings)

        # Apply calibration correction
        processed = apply_calibration(
            processed,
            self.calibration_data,
            processing_lvl=self.processing_lvl,
            exposure_ms=self.camera.settings["exposure_ms"],
            logger=self.get_logger()
        )

        # Validate shape once
        if (
            not self.shape_warning_logged
            and processed.shape != self.final_shape_expected
        ):
            self.get_logger().warning(
                f"Processed image shape {processed.shape} does not match "
                f"expected shape {self.final_shape_expected}. Check settings."
            )
            self.shape_warning_logged = True

        return processed

    def _calculate_statistics(self, image: np.ndarray) -> Dict[str, float]:
        """
        @brief Calculate image statistics for monitoring.

        @param image Processed image array
        @return Dictionary with 'variance', 'mean', 'median' keys
        @pre image must be valid 2D numpy array
        @post Returns statistical measurements for exposure control
        """
        assert isinstance(image, np.ndarray), "image must be numpy array"
        assert image.ndim == 2, f"image must be 2D, got {image.ndim}D"

        variance, mean, median = self.analyse_image_stats(image)
        return {
            'variance': variance,
            'mean': mean,
            'median': median
        }

    def _handle_auto_exposure(self, stats: Dict[str, float]) -> None:
        """
        @brief Update auto-exposure based on image statistics.

        @param stats Dictionary containing image statistics
        @pre stats must contain 'mean', 'variance', 'median'
        @post Camera exposure may be adjusted if conditions met
        """
        assert 'mean' in stats, "stats must contain 'mean'"
        assert 'variance' in stats, "stats must contain 'variance'"
        assert 'median' in stats, "stats must contain 'median'"

        if not self.auto_exposure_controller:
            return

        self.auto_exposure_controller.update_statistics(
            stats['mean'], stats['variance'], stats['median']
        )

        should_adjust, direction = (
            self.auto_exposure_controller.should_adjust_exposure()
        )

        if should_adjust:
            new_exposure = self.auto_exposure_controller.adjust_exposure(direction)
            if new_exposure is not None:
                self.camera.set_exposure(new_exposure)
                self._publish_auto_exposure_status(
                    new_exposure, direction, stats['mean']
                )

    def _publish_auto_exposure_status(
        self, new_exposure: float, direction: str, mean: float
    ) -> None:
        """
        @brief Publish auto-exposure adjustment status.

        @param new_exposure New exposure time in milliseconds
        @param direction Adjustment direction ('increase' or 'decrease')
        @param mean Current image mean value
        @post Status message published to auto_exposure_status topic
        """
        info = self.auto_exposure_controller.get_preset_info()
        status_msg = String()
        status_msg.data = (
            f"adjusted:{direction},"
            f"exposure:{new_exposure:.1f}ms,"
            f"preset:{info['current_index']+1}/{info['total_presets']},"
            f"mean:{mean:.0f}"
        )
        self.auto_exposure_status_pub.publish(status_msg)

    def _publish_frame_data(
        self, image: np.ndarray, stats: Dict[str, float], timestamp: float
    ) -> None:
        """
        @brief Publish image and metadata to all ROS topics.

        @param image Processed image array
        @param stats Dictionary of image statistics
        @param timestamp Frame capture timestamp
        @pre image must be valid 2D array
        @pre stats must contain required keys
        @post All ROS topics updated with current frame data
        """
        # Create header
        header = Header()
        header.stamp = self.get_clock().now().to_msg()
        header.frame_id = "hyperspec_optical_frame"

        # Publish image
        image_msg = self.bridge.cv2_to_imgmsg(image, encoding="mono16")
        image_msg.header = header
        self.image_pub.publish(image_msg)

        # Publish camera info
        self.camera_info_pub.publish(self.create_camera_info_msg(header))

        # Publish exposure info
        exposure_info = Float64MultiArray()
        exposure_info.data = [
            self.camera.settings["exposure_ms"],
            stats['variance'],
            stats['mean'],
            stats['median'],
        ]
        self.exposure_info_pub.publish(exposure_info)

        # Publish simple exposure value
        exposure_msg = Float64()
        exposure_msg.data = self.camera.settings["exposure_ms"]
        self.exposure_ms_pub.publish(exposure_msg)

        # Publish temperature
        temp_msg = Float64()
        temp_msg.data = self.camera.get_temperature()
        self.temperature_pub.publish(temp_msg)

    def capture_callback(self) -> None:
        """
        @brief Main timer callback for image capture and publishing.

        Orchestrates the complete frame acquisition pipeline:
        1. Acquire frame from camera
        2. Process (crop + calibration)
        3. Calculate statistics
        4. Handle auto-exposure
        5. Publish to ROS topics

        @pre Camera must be initialized and acquisition started
        @post Frame data published to all topics
        """
        try:
            # Acquire frame
            raw_image, timestamp = self._acquire_frame()
            if raw_image is None:
                return

            # Process frame
            processed_image = self._process_frame(raw_image)

            # Calculate statistics
            stats = self._calculate_statistics(processed_image)

            # Handle auto-exposure
            if self.auto_exposure_enabled:
                self._handle_auto_exposure(stats)

            # Publish all data
            self._publish_frame_data(processed_image, stats, timestamp)

        except Exception as e:
            self.get_logger().error(
                f"Error in capture callback: {e}\n{traceback.format_exc()}"
            )

    def _processing_callback(self) -> None:
        """
        @brief Processing callback for threaded capture mode.

        Retrieves frames from acquisition thread queue and processes them.
        Runs in ROS executor thread, decoupled from camera I/O thread.

        @pre Threaded capture mode must be initialized
        @post Frame retrieved from queue and published (if available)
        """
        try:
            # Try to get frame from queue (non-blocking)
            result = self.frame_queue.get(timeout=0.001)
            if result is None:
                return

            raw_image, timestamp = result

            # Process frame (same as timer mode)
            processed_image = self._process_frame(raw_image)

            # Calculate statistics
            stats = self._calculate_statistics(processed_image)

            # Handle auto-exposure
            if self.auto_exposure_enabled:
                self._handle_auto_exposure(stats)

            # Publish all data
            self._publish_frame_data(processed_image, stats, timestamp)

        except Exception as e:
            self.get_logger().error(
                f"Error in processing callback: {e}\n{traceback.format_exc()}"
            )

    def publish_wavelengths(self) -> None:
        """
        Timer callback to publish wavelength calibration data.
        Published at 1 Hz to provide wavelength information to subscribers.
        """
        try:
            msg = Float64MultiArray()
            msg.data = self.wavelengths.tolist()
            self.wavelengths_pub.publish(msg)
        except Exception as e:
            self.get_logger().error(f"Error publishing wavelengths: {e}")

    def cleanup(self) -> None:
        """
        @brief Cleanup resources on node shutdown.

        Ensures proper shutdown of acquisition thread (if used) and camera.
        Follows NASA principle of deterministic resource cleanup.

        @post All resources released and threads stopped
        """
        self.get_logger().info("Shutting down hyperspectral camera node...")

        # Stop acquisition thread if running
        if hasattr(self, "acquisition_thread") and self.acquisition_thread:
            self.acquisition_thread.stop()

        # Cancel timers
        if hasattr(self, "capture_timer") and self.capture_timer:
            self.capture_timer.cancel()

        if hasattr(self, "processing_timer") and self.processing_timer:
            self.processing_timer.cancel()

        if hasattr(self, "wavelength_timer") and self.wavelength_timer:
            self.wavelength_timer.cancel()

        # Close camera
        if hasattr(self, "camera"):
            self.camera.close()

        self.get_logger().info("Shutdown complete")


def main(args=None):
    """
    @brief Main entry point for ROS 2 hyperspectral camera node.

    Automatically selects appropriate executor:
    - SingleThreadedExecutor for timer-based capture (<50 Hz)
    - MultiThreadedExecutor for threaded capture (>=50 Hz)

    @param args Command line arguments (default: None)
    @post Node created, executed, and cleaned up
    """
    rclpy.init(args=args)

    node = None
    executor = None
    try:
        node = HyperspectralROS2Node()

        # Select executor based on capture mode
        if node.use_threaded_capture:
            # Use multi-threaded executor for high-rate capture
            # Allows processing callback to run concurrently with other callbacks
            executor = rclpy.executors.MultiThreadedExecutor(num_threads=2)
            executor.add_node(node)
            node.get_logger().info("Using MultiThreadedExecutor (2 threads)")
            executor.spin()
        else:
            # Use default single-threaded executor for timer-based capture
            node.get_logger().info("Using SingleThreadedExecutor")
            rclpy.spin(node)

    except KeyboardInterrupt:
        if node:
            node.get_logger().info("Keyboard interrupt received")
    except Exception as e:
        if node:
            node.get_logger().fatal(
                f"Unhandled exception: {e}\n{traceback.format_exc()}"
            )
        else:
            print(f"Fatal error during node creation: {e}\n{traceback.format_exc()}")
    finally:
        if node:
            node.cleanup()
            node.destroy_node()
        if executor:
            executor.shutdown()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
