# OpenHSI ROS2

ROS2 package for hyperspectral line-scan cameras. Publishes individual line scans as ROS2 topics for synchronized data logging and real-time visualization.

## Supported Cameras

| Camera | Connection | SDK |
|--------|------------|-----|
| **Lucid Vision** (Phoenix series) | GigE Vision (Ethernet) | Arena SDK |
| **XIMEA** (USB hyperspectral) | USB 3.0 | XIMEA API |

## Features

- Publishes hyperspectral line scans at configurable frame rates (up to 30+ Hz)
- Wavelength calibration metadata bundled with each frame
- Multiple processing levels (raw, flat-field, radiance)
- Auto-exposure control with configurable thresholds
- Real-time visualization in Foxglove Studio
- Compatible with ROS2 bag recording for mission logging

---

## Quick Start

### Prerequisites

- **ROS2 Jazzy** (Ubuntu 24.04) or **ROS2 Humble** (Ubuntu 22.04)
- Python 3.10+
- Lucid Arena SDK or XIMEA API (see installation sections below)

### 1. Clone and Build

```bash
cd /media/logic/USamsung/dai_ws/src
git clone https://github.com/your-org/openhsi_ros2.git

# Build the message package first (optional but recommended)
cd /media/logic/USamsung/dai_ws
colcon build --packages-select openhsi_msgs
colcon build --packages-select openhsi_ros2
source install/setup.bash
```

### 2. Run the Node

```bash
ros2 run openhsi_ros2 hyperspec_node --ros-args \
    -p camera_type:=lucid \
    -p config_file:=/media/logic/USamsung/dai_ws/src/openhsi_ros2/config/lucid_calibration/cam_settings_lucid_phoenix_1_6_IMX273.json \
    -p processing_lvl:=0 \
    -p cap_hz:=10.0 \
    -p exposure_ms:=15.0
```

### 3. View in Foxglove

```bash
# Terminal 2: Start Foxglove bridge
ros2 launch foxglove_bridge foxglove_bridge_launch.xml
```

Open Foxglove Studio, connect to `ws://localhost:8765`, and add:
- **Image panel** → `/hyperspec/image_raw`
- **Hypercube Waterfall panel** → `/hyperspec/image_raw` (see Visualization section)

---

## ROS2 Topics

| Topic | Type | Rate | Description |
|-------|------|------|-------------|
| `/hyperspec/image_raw` | sensor_msgs/Image | cap_hz | Line scan image (mono16) |
| `/hyperspec/hyperspectral_image` | openhsi_msgs/HyperspectralImage | cap_hz | Image + wavelength metadata |
| `/hyperspec/wavelengths` | std_msgs/Float64MultiArray | 1 Hz | Wavelength array (nm) |
| `/hyperspec/camera_info` | sensor_msgs/CameraInfo | cap_hz | Camera calibration |
| `/hyperspec/exposure_ms` | std_msgs/Float64 | cap_hz | Current exposure time |
| `/hyperspec/temperature` | std_msgs/Float64 | 1 Hz | Sensor temperature (°C) |
| `/hyperspec/exposure_info` | std_msgs/Float64MultiArray | cap_hz | [exposure, variance, mean, median] |

### Image Dimensions

After processing, image dimensions depend on `axis_order` in the config:

**Lucid cameras** (after transpose, `axis_order: "spectral,spatial"`):

- **height** = spectral bands (e.g., 532 wavelengths)
- **width** = spatial pixels (e.g., 448 cross-track pixels)

**XIMEA cameras** (default, `axis_order: "spatial,spectral"`):

- **height** = spatial pixels (cross-track)
- **width** = spectral bands (wavelengths)

**Encoding**: `mono16` (16-bit unsigned, 0-65535 for Mono16, 0-4095 for Mono12)

Each image represents one spatial line with full spectral information at each pixel.

### HyperspectralImage Message

The custom `openhsi_msgs/HyperspectralImage` bundles the image with wavelength calibration:

```
std_msgs/Header header
sensor_msgs/Image image
float64[] wavelengths_nm        # Wavelength for each spectral band
float64 wavelength_start_nm     # First wavelength (e.g., 426.07)
float64 wavelength_end_nm       # Last wavelength (e.g., 897.69)
float64 pixel_dispersion_nm_px  # Wavelength spacing per pixel (e.g., 0.895)
string axis_order               # "spectral,spatial" or "spatial,spectral"
float64 exposure_ms
float64 sensor_temperature_c
```

**Important**: The `axis_order` field tells subscribers how to interpret the image:

- `"spectral,spatial"` → rows are wavelengths, columns are spatial pixels
- `"spatial,spectral"` → rows are spatial pixels, columns are wavelengths

---

## Node Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `camera_type` | string | `ximea` | Camera type: `lucid` or `ximea` |
| `config_file` | string | - | Path to camera configuration JSON |
| `calibration_file` | string | `""` | Path to calibration NetCDF file |
| `processing_lvl` | int | `0` | Processing level (see below) |
| `cap_hz` | float | `10.0` | Capture rate in Hz |
| `exposure_ms` | float | `10.0` | Initial exposure time (ms) |
| `serial_number` | string | `""` | Camera serial (XIMEA) or MAC (Lucid) |
| `auto_exposure_enable` | bool | `false` | Enable auto-exposure |
| `auto_exposure_low_threshold` | float | `500.0` | Min signal for exposure increase |
| `auto_exposure_high_threshold` | float | `3000.0` | Max signal for exposure decrease |

### Processing Levels

| Level | Name | Description | Data Type |
|-------|------|-------------|-----------|
| 0 | Raw | Digital numbers from sensor | uint16 |
| 1 | Dark-subtracted | Dark current removed | uint16 |
| 2 | Flat-field | Pixel sensitivity corrected | float32 |
| 3 | Radiance | Calibrated to μW/cm²/sr/nm | float32 |

---

## Visualization

### Foxglove Hypercube Waterfall Panel

A custom Foxglove extension for visualizing hyperspectral data as an RGB waterfall.

**Features:**

- RGB composite from selectable wavelength bands
- Multiple presets: visible, vegetation, coral, water
- Click on waterfall to view spectrum at any point
- Real-time scrolling waterfall display
- Automatic wavelength calibration from HyperspectralImage message
- Supports both Lucid and XIMEA axis orders

**Installation:**

```bash
cd foxglove-hypercube-panel
npm install
npm run package
```

In Foxglove: **Settings** → **Extensions** → **Install local extension** → select the `.foxe` file.

**Configuration (Recommended - Combined Message Mode):**

- ☑️ **Combined msg** checkbox enabled
- **Topic**: `/hyperspec/hyperspectral_image`
- Wavelengths and axis_order are read automatically from the message

**Configuration (Legacy - Separate Topics Mode):**

- ☐ **Combined msg** checkbox disabled
- **Image Topic**: `/hyperspec/image_raw`
- **WL Topic**: `/hyperspec/wavelengths`

**RGB Presets:**

| Preset | Red | Green | Blue | Use Case |
|--------|-----|-------|------|----------|
| visible | 650nm | 550nm | 470nm | Natural color |
| vegetation | 800nm | 670nm | 550nm | Plant health (NIR) |
| water | 560nm | 490nm | 440nm | Water column |
| coral | 680nm | 570nm | 480nm | Coral pigmentation |
| custom | user | user | user | Custom wavelengths |

---

## Lucid Camera Installation

### Lucid Camera Datasheet

| Parameter | Design Goal | Notes |
|---|---|---|
| Input Aperture | 4mm |  |
| Field Lens Focal Length | 16mm |  |
| Sensor Size | 1440 x 1080 px, 1.6 MP | Only a 1080 pixel square area is required. |
| Pixel Size | 3.45µm |  |
| FOV | 10.7◦ |  |
| iFOV (along and across-track) | approx. 2 milli-radians (0.1◦ ) | along-track, limited by slit width. |
| Spatial Samples | >800 | slit image length divided by pixel size, binning and image quality my reduce effective samples. |
| Spectrograph Slit Size (Physical) | 3mm by 25µm |  |
| Slit Image Size on sensor | 3.1mm by 25.9µm | M=1.035 |
| Spectral Sampling Interval | 0.45 nm | nm per pixel |
| Band Size | 3.3 nm | 7.5 pixel across slit, corresponds to slit width, ie pixel that need to be binned |
| Wavelength Range | 430 nm to 900 nm | spatial resolution will be de- graded blue of 500nm, and be- yond 850nm. |
| Number of Bands | approx 144 |  |
| Typical Exposure Time. | 10ms |  |
| Signal to Noise estimate | > 150 (430nm to 660nm) > 90 (680nm to 800nm) | 10ms exposure, estimated using 6SV solar illumination, Mid lati- tude Summer, nadir pointing and including detector QE |
| Size (L x W x H) | 35mm x 52mm x 35mm | Enclosing rectangle |
| Camera Sensor Model | Phoenix 1.6 MP Model | https://thinklucid.com/ product/phoenix-16-mp- imx273/ |
| Weight | < 200g without enclosure |  |
| Digital Interface | 1000BASE-T RJ45, PoE ix Industrial, PoE |  |
| Power Requirement | PoE (IEEE 802.3af), or 12-24 VDC external | external via GPIO port, cable not provided. |
| Power Consumption | 3.1W via PoE, 2.5W when powered externally |  |

### 1. Install Arena SDK

Download from [Lucid Vision Downloads](https://thinklucid.com/downloads-hub/):
- **ArenaSDK_v0.1.104_Linux_x64.tar.gz** (or ARM64 for Jetson)
- **arena_api-2.7.1-py3-none-any.zip**

```bash
# Run the installation script
cd /media/logic/USamsung/dai_ws/src/openhsi_ros2
./install_arena_sdk_x64.sh  # or install_arena_sdk_ARM.sh for Jetson
```

### 2. Configure GigE Network

```bash
# Configure Link-Local Address (replace "Wired connection 1" with your connection name)
sudo nmcli connection modify "Wired connection 1" \
    ipv4.method manual \
    ipv4.addresses 169.254.0.1/16 \
    802-3-ethernet.mtu 9000

sudo nmcli connection up "Wired connection 1"

# Increase socket buffers
sudo sh -c "echo 'net.core.rmem_default=33554432' >> /etc/sysctl.conf"
sudo sh -c "echo 'net.core.rmem_max=33554432' >> /etc/sysctl.conf"
sudo sysctl -p
```

### 3. Verify Camera Detection

```bash
python3 -c "
from arena_api.system import system
devices = system.create_device()
print(f'Found {len(devices)} camera(s)')
for d in devices:
    print(f'  - {d.nodemap.get_node(\"DeviceModelName\").value}')
    system.destroy_device(d)
"
```

---

## XIMEA Camera Installation

### 1. Install XIMEA API

```bash
cd ~/Downloads
wget https://updates.ximea.com/public/ximea_linux_sp_beta.tgz
tar xzf ximea_linux_sp_beta.tgz
cd package
sudo ./install
```

### 2. Configure USB Permissions

```bash
# Add user to plugdev group
sudo gpasswd -a $USER plugdev

# Increase USB buffer (permanent)
echo '#!/bin/sh -e
echo 0 > /sys/module/usbcore/parameters/usbfs_memory_mb
exit 0' | sudo tee /etc/rc.local
sudo chmod +x /etc/rc.local
```

Log out and back in for group changes to take effect.

---

## Camera Configuration Guide

This section explains how to create a camera configuration JSON file for any hyperspectral pushbroom camera.

### Understanding Pushbroom Camera Geometry

A pushbroom hyperspectral camera captures a single **spatial line** at a time, with each pixel in that line containing a full **spectrum**:

```
┌────────────────────────────────────────────────────┐
│                    SENSOR ARRAY                    │
│                                                    │
│  ◄──────────── Spectral Axis (wavelengths) ──────► │
│                                                    │
│  ▲  ┌────┬────┬────┬────┬────┬────┬────┬────┐      │
│  │  │ λ₁ │ λ₂ │ λ₃ │ λ₄ │ λ₅ │ ...│λₙ₋₁│ λₙ │ ← Pixel 0 (spatial)
│  │  ├────┼────┼────┼────┼────┼────┼────┼────┤      │
│  S  │ λ₁ │ λ₂ │ λ₃ │ λ₄ │ λ₅ │ ...│λₙ₋₁│ λₙ │ ← Pixel 1
│  p  ├────┼────┼────┼────┼────┼────┼────┼────┤      │
│  a  │ .. │ .. │ .. │ .. │ .. │ .. │ .. │ .. │      │
│  t  ├────┼────┼────┼────┼────┼────┼────┼────┤      │
│  i  │ λ₁ │ λ₂ │ λ₃ │ λ₄ │ λ₅ │ ...│λₙ₋₁│ λₙ │ ← Pixel N (spatial)
│  a  └────┴────┴────┴────┴────┴────┴────┴────┘      │
│  l                                                 │
│  ▼                                                 │
└────────────────────────────────────────────────────┘
```

**Key Terminology:**
- **Spatial pixels**: Cross-track pixels (perpendicular to flight direction)
- **Spectral bands**: Wavelength channels (e.g., 426nm, 427nm, 428nm, ...)
- **axis_order**: Describes which image dimension is spatial vs spectral

### Axis Order Explained

The `axis_order` field tells visualization tools how to interpret the image dimensions:

| axis_order | Image Layout | Use Case |
|------------|--------------|----------|
| `"spatial,spectral"` | rows=spatial, cols=spectral | XIMEA default, some Lucid modes |
| `"spectral,spatial"` | rows=spectral, cols=spatial | Lucid after transpose |

**Example:** For a 448×532 image with `axis_order: "spectral,spatial"`:
- 448 rows = spectral bands (wavelengths)
- 532 columns = spatial pixels (cross-track)

### Configuration File Reference

#### Complete Example (Lucid Camera)

```json
{
    "camera_type": "lucid",
    "camera_id": "OpenHSI-06",
    "pixel_format": "Mono12",
    "binxy": [2, 2],

    "win_resolution": [464, 532],
    "win_offset": [42, 76],

    "row_slice": [7, 455],

    "crop_offset_y": 7,
    "crop_offset_x": 0,
    "crop_height": 448,
    "crop_width": 532,

    "exposure_ms": 8.417,

    "wavelength_start_nm": 426.07,
    "wavelength_end_nm": 897.69,
    "num_spectral_bands": 532,
    "num_spatial_pixels": 448,
    "pixel_dispersion_nm_px": 0.895,

    "fwhm_nm": 4,

    "final_image_shape_after_crop_and_transpose": [532, 448],
    "resolution": [448, 532],

    "axis_order_before_transpose": "spatial,spectral",
    "axis_order_after_transpose": "spectral,spatial",

    "exposure_presets_ms": [
        5.0, 6.0, 8.0, 10.0, 12.0, 15.0, 18.0, 20.0, 25.0, 30.0, 40.0, 50.0
    ],

    "camera_notes": "Description of camera setup and calibration",
    "calibration_file": "OpenHSI-06_calibration_Mono12_bin2_window.nc",
    "calibration_date": "2021-05-26",
    "operator": "OpenHSI"
}
```

#### Field Descriptions

##### Camera Identification

| Field | Type | Description |
|-------|------|-------------|
| `camera_type` | string | `"lucid"` or `"ximea"` |
| `camera_id` | string | Unique identifier (e.g., `"OpenHSI-06"`) |
| `pixel_format` | string | Sensor pixel format (`"Mono12"`, `"Mono16"`) |

##### Hardware Configuration

| Field | Type | Description |
|-------|------|-------------|
| `binxy` | [int, int] | Hardware binning [rows, cols] (e.g., `[2, 2]` for 2×2) |
| `win_resolution` | [int, int] | ROI size [height, width] in pixels |
| `win_offset` | [int, int] | ROI offset [y, x] from sensor origin |

##### Software Cropping

| Field | Type | Description |
|-------|------|-------------|
| `row_slice` | [int, int] | Valid row range [start, end] for spectral extraction |
| `crop_offset_y` | int | Y offset for final crop (pixels) |
| `crop_offset_x` | int | X offset for final crop (pixels) |
| `crop_height` | int | Final image height after crop |
| `crop_width` | int | Final image width after crop |

##### Wavelength Calibration (Critical!)

| Field | Type | Description |
|-------|------|-------------|
| `wavelength_start_nm` | float | First wavelength in spectrum (nm) |
| `wavelength_end_nm` | float | Last wavelength in spectrum (nm) |
| `num_spectral_bands` | int | Number of spectral channels |
| `num_spatial_pixels` | int | Number of cross-track pixels |
| `pixel_dispersion_nm_px` | float | Wavelength change per pixel (nm/px) |
| `fwhm_nm` | float | Full-width half-maximum spectral resolution (nm) |

##### Output Shape & Axis Order

| Field | Type | Description |
|-------|------|-------------|
| `resolution` | [int, int] | Output shape before transpose [height, width] |
| `final_image_shape_after_crop_and_transpose` | [int, int] | Final output shape [height, width] |
| `axis_order_before_transpose` | string | Axis interpretation before transpose |
| `axis_order_after_transpose` | string | Axis interpretation after transpose (used by Foxglove) |

##### Exposure Settings

| Field | Type | Description |
|-------|------|-------------|
| `exposure_ms` | float | Default exposure time (milliseconds) |
| `exposure_presets_ms` | float[] | Auto-exposure preset values |

##### Metadata

| Field | Type | Description |
|-------|------|-------------|
| `camera_notes` | string | Human-readable description |
| `calibration_file` | string | Reference to calibration NetCDF file |
| `calibration_date` | string | Date of calibration |
| `operator` | string | Person/organization who performed calibration |

### Creating a Config from Calibration Data

If you have a calibration NetCDF file (`.nc`), extract the wavelength parameters:

```python
import xarray as xr

# Open calibration file
ds = xr.open_dataset("calibration.nc")

# Extract wavelength array
wavelengths = ds["wavelengths"].values
print(f"wavelength_start_nm: {wavelengths[0]:.2f}")
print(f"wavelength_end_nm: {wavelengths[-1]:.2f}")
print(f"num_spectral_bands: {len(wavelengths)}")
print(f"pixel_dispersion_nm_px: {(wavelengths[-1] - wavelengths[0]) / (len(wavelengths) - 1):.3f}")

# Check for spatial dimension
if "smile_shifts" in ds:
    print(f"num_spatial_pixels: {len(ds['smile_shifts'])}")

ds.close()
```

### XIMEA vs Lucid Differences

| Feature | XIMEA | Lucid |
|---------|-------|-------|
| Connection | USB 3.0 | GigE Vision |
| Default axis_order | `spatial,spectral` | `spectral,spatial` (after transpose) |
| Typical format | Mono16 | Mono12 |
| Binning | Software | Hardware |

---

## Recording and Playback

### Record a ROS2 Bag

```bash
ros2 bag record /hyperspec/image_raw /hyperspec/wavelengths /hyperspec/camera_info \
    -o hyperspectral_mission
```

### Playback with Foxglove

```bash
# Terminal 1: Play bag
ros2 bag play hyperspectral_mission --loop

# Terminal 2: Foxglove bridge
ros2 launch foxglove_bridge foxglove_bridge_launch.xml
```

Open Foxglove and connect to `ws://localhost:8765`.

---

## Troubleshooting

### Lucid Camera Not Detected

1. Check network configuration: `ip addr show` should show 169.254.x.x
2. Verify MTU: `ip link show` should show `mtu 9000`
3. Run `sudo ldconfig` after SDK installation
4. Try disabling reverse path filtering:
   ```bash
   sudo sysctl -w net.ipv4.conf.all.rp_filter=0
   ```

### Frame Drops / Slow Rate

1. Increase socket buffers:

   ```bash
   sudo sysctl -w net.core.rmem_max=67108864
   ```

2. Check RX ring buffer:

   ```bash
   sudo ethtool -g <interface>
   sudo ethtool -G <interface> rx 1024
   ```

### XIMEA Error Code 13

Increase USB buffer size (see XIMEA installation section).

### OpenCV Import Error After Arena SDK Install

The Arena SDK may conflict with system OpenCV on Ubuntu 24.04. Run:

```bash
./install_arena_sdk_x64.sh  # Includes fix for Metavision library conflicts
```

---

## Directory Structure

```bash
openhsi_ros2/
├── openhsi_ros2/
│   └── hyperspec_node.py      # Main ROS2 node
├── config/
│   ├── lucid_calibration/     # Lucid camera configs
│   └── ximea_calibration/     # XIMEA camera configs
├── arena_sdk/                 # Lucid Arena SDK (after install)
├── launch/
│   └── hyperspec_launch.py    # Launch file
├── install_arena_sdk_x64.sh   # x64 SDK installer
├── install_arena_sdk_ARM.sh   # ARM64 SDK installer
└── README.md
```

---

## Related Packages

- **openhsi_msgs** - Custom ROS2 messages for hyperspectral data
- **foxglove-hypercube-panel** - Foxglove extension for waterfall visualization

---

## License

MIT License

## Author

Michael Venz
