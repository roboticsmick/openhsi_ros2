# openhsi_ros2

Hyperspectral Imaging ROS2 library for line-scan hyperspectral cameras.

This package supports two hyperspectral camera systems:

- **Ximea** - USB 3.0 hyperspectral cameras (via OpenHSI)
- **Lucid Vision** - GigE Vision hyperspectral line-scan cameras

## Prerequisites

- ROS2 (tested with Humble/Iron)
- Ubuntu 22.04/24.04
- Python 3.8+

---

## 1. Ximea Camera Setup

This section covers installation and configuration for Ximea hyperspectral cameras using the OpenHSI library.

### 1.1 Download XIMEA Linux Software Package

Download the appropriate package for your CPU architecture. For Intel x86 (typically the "Beta" package):

```bash
# Navigate to the XIMEA SDK directory
cd "${PROJECT_ROOT}/api_sdks/ximea"

# Download (replace URL if a newer version is available)
wget https://updates.ximea.com/public/ximea_linux_sp_beta.tgz

# Extract
tar xzf ximea_linux_sp_beta.tgz
# This should create a 'package' subdirectory (e.g., api_sdks/ximea/package/)
```

### 1.2 Install XIMEA API

The XIMEA installer typically needs to be run with root privileges.

```bash
# Navigate to the extracted package directory
cd "${PROJECT_ROOT}/api_sdks/ximea/package/"

# Run the installer
sudo ./install
```

**Installation Notes:**

- Follow the on-screen prompts
- If `xiCamTool` (a XIMEA GUI tool) fails to launch, you might be missing Qt dependencies. For example, on Ubuntu: `sudo apt install libxcb-cursor0`
- In some cases, disabling "Secure Boot" in the BIOS/UEFI settings can resolve driver or device recognition issues

### 1.3 Configure USB 3.0 Support

**Crucial for USB3 Cameras**

#### 1.3.1 Check Kernel Version

Ensure your Linux kernel is version 3.4 or newer:

```bash
uname -sr
```

#### 1.3.2 Add User to `plugdev` Group

Your user needs to be part of the `plugdev` group to access USB devices without root:

```bash
# Check current groups
groups $USER

# Add user to plugdev group if not already a member
sudo gpasswd -a $USER plugdev
```

**You will need to log out and log back in, or reboot, for this group change to take effect.**

### 1.4 Configure Linux USB Data Path (Performance)

These settings improve data streaming reliability.

#### 1.4.1 Increase USBFS Memory Buffer

**Temporary (for testing):**

```bash
sudo tee /sys/module/usbcore/parameters/usbfs_memory_mb >/dev/null <<<0
```

**Permanent (recommended):**

Create `/etc/rc.local`:

```bash
#!/bin/sh -e
# USB Buffer size for hyperspectral camera
echo 0 > /sys/module/usbcore/parameters/usbfs_memory_mb
exit 0
```

Save and make executable:

```bash
sudo chmod +x /etc/rc.local
```

**Note:** A value of `0` often means "unlimited" or a very large system-dependent default. Some XIMEA guides suggest `2000` or more if `0` is problematic. Test what works for your system.

**Symptom if not set correctly:** Error code 13 during `startAcquisition()`.

#### 1.4.2 Allow Applications Realtime Priority

Edit `/etc/security/limits.conf`:

```bash
sudo nano /etc/security/limits.conf
```

Add these lines:

```
*              -       rtprio          0
@realtime      -       rtprio          81
*              -       nice            0
@realtime      -       nice            -16
```

Create the `realtime` group and add your user:

```bash
sudo groupadd realtime
sudo gpasswd -a $USER realtime
```

**Re-login or reboot for these changes to apply.**

### 1.5 XIMEA API Buffer Configuration (In Code)

The OpenHSI `XimeaCamera` class usually handles these settings internally based on its configuration. The following are examples of xiAPI calls that can be made to optimize buffer handling:

```c++
// Example C API calls, OpenHSI Python wrapper would use equivalent methods
// xiSetParamInt(handle, XI_PRM_ACQ_TRANSPORT_BUFFER_COMMIT, 32);
// xiGetParamInt(handle, XI_PRM_ACQ_TRANSPORT_BUFFER_SIZE XI_PRM_INFO_MAX, &buffer_size);
// xiSetParamInt(handle, XI_PRM_ACQ_TRANSPORT_BUFFER_SIZE, buffer_size);
```

---

## 2. Lucid Vision Camera Setup

This section covers installation and configuration for Lucid Vision GigE hyperspectral line-scan cameras using the Arena SDK.

### 2.1 Install Arena SDK

The installation process differs based on your system architecture. Choose the appropriate section below.

#### 2.1.1 Determine Your System Architecture

Check your system architecture:

```bash
uname -m
```

- `x86_64` → Use the **x64 installation** (Section 2.1.2)
- `aarch64` or `arm64` → Use the **ARM installation** (Section 2.1.3)

#### 2.1.2 x64 Installation (Ubuntu Desktop/Laptop)

**Download the required files** from [Lucid Vision Labs Downloads](https://thinklucid.com/downloads-hub/) and save to `~/Downloads`:

1. **Arena SDK Linux x64** - `ArenaSDK_v0.1.104_Linux_x64.tar.gz`
   - Look for: *Arena SDK - x64 Ubuntu 18.04/20.04/22.04/24.04, 64-bit*
2. **Arena Python Package** - `arena_api-2.7.1-py3-none-any.zip`

**Run the x64 installation script:**

```bash
cd /media/logic/USamsung/ros2_ws/src/openhsi_ros2
./install_arena_sdk_x64.sh
```

#### 2.1.3 ARM Installation (Jetson Orin NX/AGX)

**Download the required files** from [Lucid Vision Labs Downloads](https://thinklucid.com/downloads-hub/) and save to `~/Downloads`:

1. **Arena SDK Linux ARM64** - `ArenaSDK_v0.1.78_Linux_ARM64.tar.gz`
   - Look for: *Arena SDK - ARM Ubuntu 22.04/24.04, 64-bit for Jetson Orin NX with JetPack 6.2*
2. **Arena Python Package** - `arena_api-2.7.1-py3-none-any.zip`

**Run the ARM installation script:**

```bash
cd /media/logic/USamsung/ros2_ws/src/openhsi_ros2
./install_arena_sdk_ARM.sh
```

#### 2.1.4 Uninstalling Arena SDK

If you need to remove an existing installation (e.g., to switch architectures):

```bash
cd /media/logic/USamsung/ros2_ws/src/openhsi_ros2
./uninstall_arena_sdk.sh
```

**Documentation:** [Arena SDK Documentation](https://support.thinklucid.com/arena-sdk-documentation/)

### 2.2 Configure Ethernet Adapter

GigE Vision cameras require specific network configuration for optimal performance.

#### 2.2.1 Set Up Link-Local Address (LLA)

Configure a static IP address in the 169.254.x.x range:

##### Option A: Using GUI (Desktop with Display)

1. Navigate to **Settings → Network → Ethernet → IPv4**
2. Select the **IPv4 Settings** tab
3. Choose **Manual** for Method
4. In the **Addresses** heading, click **Add** and enter:

| Field | Value |
|-------|-------|
| IP Address | 169.254.0.1 |
| Subnet Mask | 255.255.0.0 |

5. Click **Apply**

##### Option B: Using SSH/Command Line

```bash
# First, identify your ethernet interface and existing connection
nmcli device status
nmcli connection show

# Configure the ethernet connection (replace "Wired connection 1" and "eno1" with your actual connection name and interface)
sudo nmcli connection modify "Wired connection 1" \
  connection.interface-name eno1 \
  ipv4.method manual \
  ipv4.addresses 169.254.0.1/16 \
  ipv4.gateway ""

# Activate the connection
sudo nmcli connection up "Wired connection 1"

# Verify the configuration
nmcli connection show "Wired connection 1" | grep ipv4
```

#### 2.2.2 Enable Jumbo Frames

Jumbo frames improve throughput for high-bandwidth GigE cameras:

##### Option A: Using GUI (Desktop with Display)

1. Navigate to **Settings → Network → Ethernet → Identity**
2. Change **MTU** to **9000**
3. Click **Apply**

##### Option B: Using SSH/Command Line

```bash
# Add MTU 9000 to the existing connection configuration
sudo nmcli connection modify "Wired connection 1" \
  802-3-ethernet.mtu 9000

# Reactivate the connection to apply changes
sudo nmcli connection down "Wired connection 1"
sudo nmcli connection up "Wired connection 1"

# Verify MTU is set to 9000
ip addr show eno1 | grep mtu
```

**Expected output:**
```
4: eno1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 9000 qdisc mq state UP group default qlen 1000
```

#### 2.2.3 Adjust Receive Buffer Size

**Check maximum RX buffer size:**

```bash
# Find your ethernet interface name (e.g., eth0, eno1, enp0s31f6, etc.)
ip link show | grep mtu

# Check current and maximum ring buffer settings (replace eno1 with your interface)
sudo ethtool -g eno1
```

Example output:

```
Ring parameters for eno1:
Pre-set maximums:
RX:         1024
RX Mini:    n/a
RX Jumbo:   n/a
TX:         1024
Current hardware settings:
RX:         256
RX Mini:    n/a
RX Jumbo:   n/a
TX:         256
```

**Set RX buffer to maximum:**

```bash
# Replace eth0 with your interface and 1024 with your maximum RX value
sudo ethtool -G eno1 rx 1024

# Verify the change
sudo ethtool -g eno1
```

**Make permanent (using systemd):**

Create a systemd service to set the buffer size on boot:

```bash
sudo nano /etc/systemd/system/set-ethernet-buffers.service
```

Add the following content (replace `eno1` and `1024` with your values):

```ini
[Unit]
Description=Set Ethernet RX Buffer Size for GigE Camera
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/sbin/ethtool -G eno1 rx 1024
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

Enable the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable set-ethernet-buffers.service
sudo systemctl start set-ethernet-buffers.service
```

#### 2.2.4 Set Socket Buffer Size

Increase the receive buffer sizes for the network stack:

```bash
sudo sh -c "echo 'net.core.rmem_default=1048576' >> /etc/sysctl.conf"
sudo sh -c "echo 'net.core.rmem_max=1048576' >> /etc/sysctl.conf"
sudo sysctl -p
```

These changes are automatically permanent.

#### 2.2.5 Configure Reverse Path Filtering

Disable reverse path filtering for GigE Vision cameras:

**Temporary (for testing):**

```bash
sudo sysctl -w net.ipv4.conf.default.rp_filter=0
sudo sysctl -w net.ipv4.conf.all.rp_filter=0
sudo sysctl -w net.ipv4.conf.eno1.rp_filter=0  # Replace eth0 with your interface
```

**Make permanent:**

Edit the network security configuration:

```bash
sudo vim /etc/sysctl.d/10-network-security.conf
```

Comment out the following lines by adding `#` at the beginning:

```
# Turn on Source Address Verification in all interfaces to
# prevent some spoofing attacks
#net.ipv4.conf.default.rp_filter=2
#net.ipv4.conf.all.rp_filter=2
```

Apply the changes:

```bash
sudo sysctl -p /etc/sysctl.d/10-network-security.conf
```

---

## 3. Package Configuration

### 3.1 Camera Configuration Files

Camera-specific settings and calibration files are organized by camera type in the `config/` directory:

**Lucid Camera:**
- `config/lucid_calibration/cam_settings_lucid_phoenix_1_6_IMX273.json` - Camera settings (crop size, exposure, etc.)
- `config/lucid_calibration/*.nc` - Calibration data files (NetCDF format)

**Ximea Camera:**
- `config/ximea_calibration/cam_settings_ximea_MVCV-1082.json` - Camera settings
- `config/ximea_calibration/*.nc` - Calibration data files (NetCDF format)

### 3.2 Calibration File Format

Calibration data is stored in NetCDF format (`.nc` files).

**Calibration file structure:**
- `wavelengths` - Wavelength array (nm) for each pixel
- `flat_field_pic` - Flat field reference image for pixel sensitivity correction
- `smile_shifts` - Smile distortion correction data
- `rad_ref` - 4D radiance reference cube (cross_track × wavelength × exposure × luminance)
- `sfit_x`, `sfit_y` - Spectral radiance interpolation function
- `HgAr_pic` - HgAr calibration spectrum

**Creating calibration files:**

See [config/lucid_calibration/CALIBRATION_TUTORIAL.md](config/lucid_calibration/CALIBRATION_TUTORIAL.md) for detailed calibration procedures.

### 3.3 Install Python Dependencies

The calibration system requires xarray and netcdf4:

```bash
pip3 install xarray netcdf4 scipy --break-system-packages
```

### 3.4 Running the Hyperspectral Node

#### Basic Usage (No Calibration)

```bash
# Source your ROS2 workspace
source /media/logic/USamsung/ros2_ws/install/setup.bash

# Run with Ximea camera (raw data)
ros2 run openhsi_ros2 hyperspec_node --ros-args \
    -p camera_type:=ximea \
    -p config_file:=config/ximea_calibration/cam_settings_ximea_MVCV-1082.json \
    -p processing_lvl:=0 \
    -p cap_hz:=10.0 \
    -p exposure_ms:=10.0

# Run with Lucid camera (raw data)
ros2 run openhsi_ros2 hyperspec_node --ros-args \
    -p camera_type:=lucid \
    -p config_file:=config/lucid_calibration/cam_settings_lucid_phoenix_1_6_IMX273.json \
    -p processing_lvl:=0 \
    -p cap_hz:=10.0 \
    -p exposure_ms:=15.0
```

#### With Calibration (Lucid Camera)

```bashcam_settings_lucid.json
# Flat-field corrected data (processing_lvl=2)
ros2 run openhsi_ros2 hyperspec_node --ros-args \
    -p camera_type:=lucid \
    -p config_file:=config/lucid_calibration/cam_settings_lucid_phoenix_1_6_IMX273.json \
    -p calibration_file:=config/lucid_calibration/OpenHSI-06_calibration_Mono12_bin1.nc \
    -p processing_lvl:=2 \
    -p cap_hz:=10.0 \
    -p exposure_ms:=15.0

# Spectral radiance data (processing_lvl=3)
ros2 run openhsi_ros2 hyperspec_node --ros-args \
    -p camera_type:=lucid \
    -p config_file:=config/lucid_calibration/cam_settings_lucid_phoenix_1_6_IMX273.json \
    -p calibration_file:=config/lucid_calibration/OpenHSI-06_calibration_Mono12_bin1.nc \
    -p processing_lvl:=3 \
    -p cap_hz:=10.0 \
    -p exposure_ms:=15.0
```

#### Processing Levels

| Level | Description | Output Data Type |
|-------|-------------|------------------|
| `0` | **Raw** - Digital numbers from sensor (no corrections) | uint16 |
| `1` | **Dark-subtracted** - Dark current removed (not yet implemented) | uint16 |
| `2` | **Flat-field corrected** - Pixel sensitivity variations removed | float32 |
| `3` | **Spectral radiance** - Calibrated to μW/cm²/sr/nm | float32 |
| `4` | **Reflectance** - Requires reference panel (not yet implemented) | float32 |

**Recommended settings:**
- **Raw data collection**: `processing_lvl:=0` - Save raw data for later processing
- **Real-time visualization**: `processing_lvl:=2` - Flat-fielded data shows features clearly
- **Scientific analysis**: `processing_lvl:=3` - Calibrated radiance for quantitative analysis

---

## Troubleshooting

### Ximea Camera Issues

- **Error code 13 during acquisition:** Check USBFS memory buffer settings (Section 1.4.1)
- **Camera not detected:** Verify user is in `plugdev` group and Secure Boot is disabled
- **xiCamTool fails to launch:** Install Qt dependencies: `sudo apt install libxcb-cursor0`

### Lucid Camera Issues

- **Camera not discovered:** Verify Link-Local Address configuration and firewall settings
- **Dropped frames:** Increase RX buffer size and ensure jumbo frames are enabled
- **Slow frame rate:** Check MTU is set to 9000 and socket buffer sizes are configured

---

## Additional Resources

- [XIMEA Linux Software Package](https://www.ximea.com/support/wiki/apis/XIMEA_Linux_Software_Package)
- [Lucid Vision Arena SDK Documentation](https://support.thinklucid.com/arena-sdk-documentation/)
- [OpenHSI Documentation](https://github.com/openHSI)
- [GigE Vision Performance Optimization](https://support.thinklucid.com/knowledgebase/optimizing-gige-vision-performance/)

---

## License

[Add your license information here]
