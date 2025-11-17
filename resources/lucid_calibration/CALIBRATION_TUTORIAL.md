# OpenHSI Camera Calibration Tutorial

**⚠️ Warning:** This is not for general use. Requires technical expertise and specialized hardware.

## Required Equipment

- **Integrating sphere** - We use a SpectraPT from LabSphere
- **HgAr lamp** - Mercury-Argon calibration lamp for wavelength calibration
- **Lucid Vision hyperspectral camera**

## Overview

This tutorial walks through the complete calibration process for a Lucid Vision hyperspectral line-scan camera. The calibration enables:

1. **Geometric correction** - Determining the illuminated sensor area and optimal crop region
2. **Wavelength calibration** - Mapping pixel index to wavelength using HgAr emission lines
3. **Smile correction** - Correcting spectral line curvature across the detector
4. **Radiometric calibration** - Converting digital numbers to spectral radiance/irradiance

## Calibration File Structure

The calibration process generates two types of files:

### Settings File (JSON)
`OpenHSI-{model_number}_settings_{pixel_format}_bin{binning}.json`

Contains camera configuration:
- Camera ID and model number
- Sensor window (resolution, offset, cropping)
- Pixel format and binning
- Exposure time and FWHM
- Date of calibration

### Calibration File (NetCDF)
`OpenHSI-{model_number}_calibration_{pixel_format}_bin{binning}.nc`

Contains calibration data:
- `wavelengths` - Wavelength array (nm) for each pixel column
- `wavelengths_linear` - Linear fit of wavelengths
- `smile_shifts` - Pixel shifts to correct smile distortion
- `flat_field_pic` - Flat field reference image
- `HgAr_pic` - Arc lamp spectrum for wavelength calibration
- `rad_ref` - 4D radiance reference cube (cross_track × wavelength × exposure × luminance)
- `sfit_x`, `sfit_y` - Spectral radiance interpolation function data
- `spec_rad_ref_luminance` - Reference luminance for integrating sphere

---

## Step 1: Find Illuminated Sensor Area

The vertical direction (y-axis) of the detector array corresponds to the across-track direction. If the slit image is shorter than the sensor height, we can crop the top and bottom to save bandwidth and disk space.

### 1.1 Setup

```python
import os
import numpy as np
import holoviews as hv
import panel as pn
from openhsi.calibrate import SettingsBuilderMixin, SpectraPTController
from openhsi.cameras import LucidCamera

hv.extension("bokeh", logo=False)

class CalibrateCamera(SettingsBuilderMixin, LucidCamera):
    pass

# Configuration
modelno = 18  # Your camera model number
json_path_template = "../cals/cam_settings_lucid_template.json"
json_path_target = f"../cals/OpenHSI-{modelno:02d}/OpenHSI-{modelno:02d}_settings_Mono8_bin1.json"
cal_path_target = f"../cals/OpenHSI-{modelno:02d}/OpenHSI-{modelno:02d}_calibration_Mono8_bin1.pkl"

# Create output directory
if not os.path.isdir(os.path.dirname(json_path_target)):
    os.mkdir(os.path.dirname(json_path_target))

# Initialize integrating sphere controller
spt = SpectraPTController()
```

### 1.2 Take Flat Field Image

Provide uniform illumination to the slit using the integrating sphere or halogen lamp.

```python
# Set integrating sphere to 10000 Cd/m²
spt.selectPreset(10000)

with CalibrateCamera(
    json_path=json_path_template,
    cal_path="",
    processing_lvl=-1,  # Raw data, no processing
    exposure_ms=20
) as cam:

    # Capture flat field image
    hvim_flat = cam.retake_flat_field(show=True)
    hvim_flat.opts(width=600, height=600, axiswise=True)

    # Find edges of illuminated region
    hvim_row_minmax = cam.update_row_minmax(edgezone=0)
    hvim_row_minmax.opts(width=600, height=600, axiswise=True)

    # Calculate window height (must be multiple of 4 for Lucid cameras)
    windowheight = int(
        np.ceil((cam.settings["row_slice"][1] - cam.settings["row_slice"][0]) / 4.0) * 4
    )
    print(f"Window height: {windowheight}")

    # Update camera settings with optimal window
    cam.settings["win_resolution"] = [windowheight + 16, cam.settings["resolution"][1]]
    cam.settings["win_offset"] = [
        int(np.ceil((cam.settings["row_slice"][0]) / 4.0) * 4) - 8,
        cam.settings["win_offset"][1],
    ]
    cam.settings["row_slice"] = [16, windowheight - 8]
    cam.settings["resolution"] = cam.settings["win_resolution"]

    # Save settings
    cam.dump(json_path=json_path_target, cal_path=cal_path_target)

# Display results
pn.Column(hvim_row_minmax, hvim_flat)
```

### 1.3 Verify Window Settings

```python
with CalibrateCamera(
    n_lines=50,
    processing_lvl=0,
    cal_path=cal_path_target,
    json_path=json_path_target,
    exposure_ms=10,
) as cam:
    cam.start_cam()
    img = cam.get_img()
    img = cam.crop(img)
    cam.stop_cam()

# Check the window looks correct
hv.Image(img, bounds=(0, 0, *img.shape)).opts(
    xlabel="wavelength index",
    ylabel="cross-track",
    cmap="gray",
    title="test frame",
    width=400,
    height=400,
)
```

---

## Step 2: Wavelength Calibration with HgAr Lamp

Use a Mercury-Argon (HgAr) arc lamp to calibrate the wavelength scale and determine the spectral window (e.g., 430-900 nm).

### 2.1 Capture HgAr Spectrum

```python
with CalibrateCamera(
    json_path=json_path_target,
    cal_path="",
    processing_lvl=-1
) as cam:

    # Set camera gain for arc lamp (Lucid cameras only)
    cam.deviceSettings["Gain"].value = 10.0

    # Capture HgAr spectrum (average 18 frames)
    hvimg = cam.retake_HgAr(show=True, nframes=18)
    hvimg.opts(width=600, height=600)

    print(f"Max pixel value: {cam.calibration['HgAr_pic'].max()}")

    # Calculate smile correction shifts
    smile_fit_hv = cam.update_smile_shifts()

    # Reset smile shifts (optional, for testing)
    cam.calibration["smile_shifts"] = cam.calibration["smile_shifts"] * 0

    # Perform wavelength calibration using known HgAr lines
    wavefit_hv = cam.fit_HgAr_lines(
        top_k=15,  # Use top 15 brightest peaks
        brightest_peaks=[546.96, 435.833, (579.960 + 579.066) / 2, 763.511],
        find_peaks_height=10,
        prominence=1,
        width=1.5,
        interactive_peak_id=True,  # Allows manual verification of peaks
    )

    # Define desired wavelength range
    waveminmax = [430, 900]  # nm

    # Find corresponding pixel indices
    waveminmax_ind = [
        np.argmin(np.abs(cam.calibration["wavelengths_linear"] - λ))
        for λ in waveminmax
    ]

    # Calculate window parameters (must be multiple of 4)
    window_width = int(np.ceil((waveminmax_ind[1] - waveminmax_ind[0] + 8) / 4.0) * 4)
    offset_x = int(np.floor((waveminmax_ind[0] - 4) / 4.0) * 4)
    print(f"Window Width: {window_width}, Offset X: {offset_x}")

    # Update settings with wavelength window
    cam.settings["win_resolution"][1] = window_width
    cam.settings["win_offset"][1] = offset_x
    cam.settings["resolution"] = cam.settings["win_resolution"]

    # Display calibration results
    pn.Column(
        hvimg,
        smile_fit_hv,
        wavefit_hv.opts(xlim=(390, 1000), ylim=(-10, 255)).opts(shared_axes=False),
    )
```

### 2.2 Save Wavelength Calibration

```python
# Save wavelength calibration if results look good
cam.dump(json_path=json_path_target, cal_path=cal_path_target)
```

---

## Step 3: Retake Calibration with Windows Set

Now that we've determined the optimal sensor windows (spatial and spectral), retake the flat field and arc lamp images.

### 3.1 Retake Flat Field

```python
spt.selectPreset(10000)

with CalibrateCamera(
    json_path=json_path_target,
    cal_path=cal_path_target,
    processing_lvl=-1
) as cam:
    # Retake flat field with windows applied
    hvim_flat = cam.retake_flat_field(show=True)
    hvim_flat.opts(width=600, height=600, axiswise=True)

    # Update row min/max with edge buffer
    hvim_row_minmax = cam.update_row_minmax(edgezone=8)
    hvim_row_minmax.opts(width=600, height=600, axiswise=True)

    cam.update_resolution()
    cam.dump(json_path=json_path_target, cal_path=cal_path_target)

spt.turnOffLamp()

# Verify results
hvim_row_minmax + hvim_flat
```

### 3.2 Redo Arc Calibration with Window

```python
with CalibrateCamera(
    json_path=json_path_target,
    cal_path=cal_path_target,
    processing_lvl=-1
) as cam:
    # Adjust gain for windowed capture
    cam.deviceSettings["Gain"].value = 15.0

    # Retake HgAr spectrum
    hvimg = cam.retake_HgAr(show=True)
    hvimg.opts(width=400, height=400)
    print(f"Max pixel value: {cam.calibration['HgAr_pic'].max()}")

    # Recalculate smile shifts
    smile_fit_hv = cam.update_smile_shifts()

    # Redo wavelength fit with windowed data
    wavefit_hv = cam.fit_HgAr_lines(
        top_k=12,
        brightest_peaks=[546.96, 435.833, (579.960 + 579.066) / 2, 871.66, 763.511],
        find_peaks_height=10,
        prominence=1,
        width=1.5,
        max_match_error=2,
        interactive_peak_id=True,
    )

    # Update integrating sphere radiance fit
    cam.update_intsphere_fit()

    # Save final calibration
    cam.dump(json_path=json_path_target, cal_path=cal_path_target)

# Display results
(hvimg + smile_fit_hv + wavefit_hv.opts(xlim=(400, 900), ylim=(-10, 255))).opts(
    shared_axes=False
)
```

---

## Step 4: Radiometric Calibration

Collect a 4D datacube of integrating sphere images across different luminances and exposures. This enables conversion from digital numbers to spectral radiance.

### 4.1 Collect Radiance Reference Cube

```python
# Define calibration grid
luminances = np.fromiter(lum_preset_dict.keys(), dtype=int)  # Cd/m²
exposures = [0, 5, 8, 10, 15, 20]  # ms

with CalibrateCamera(
    json_path=json_path_target,
    cal_path=cal_path_target,
    processing_lvl=-1
) as cam:

    # Collect 4D calibration cube
    # Dimensions: (cross_track, wavelength_index, exposure, luminance)
    cam.calibration["rad_ref"] = cam.update_intsphere_cube(
        exposures,
        luminances,
        nframes=50,  # Average 50 frames per setting
        lum_chg_func=spt.selectPreset
    )

    # Remove saturated images
    cam.calibration["rad_ref"] = cam.calibration["rad_ref"].where(
        ~(
            np.sum((cam.calibration["rad_ref"][:, :, :, :, :] == 255), axis=(1, 2))
            > 1000
        )
    )

    cam.dump(json_path=json_path_target, cal_path=cal_path_target)

spt.turnOffLamp()
```

### 4.2 Visualize Radiance Reference

```python
# Plot radiance reference cube
cam.calibration["rad_ref"].plot(
    y="cross_track",
    x="wavelength_index",
    col="exposure",
    row="luminance",
    cmap="gray"
)

# Check file size
print(f"rad_ref is {cam.calibration['rad_ref'].size / 1024 / 1024 * 4} MB")
```

### 4.3 Fit Spectral Radiance Function

```python
cam.update_intsphere_fit()
cam.dump(json_path=json_path_target, cal_path=cal_path_target)
```

---

## Understanding Processing Levels

When using the calibrated camera, you can specify different processing levels:

| Level | Processing | Output |
|-------|-----------|---------|
| `-1` | Raw | Digital numbers from sensor (no corrections) |
| `0` | Dark subtraction | Remove dark current noise |
| `1` | Flat field correction | Correct for pixel-to-pixel sensitivity variations |
| `2` | Radiometric calibration | Convert to spectral radiance (μW/cm²/sr/nm) |
| `3` | Reflectance | Convert to reflectance using reference panel |

---

## Converting Calibration Files to NetCDF

If you have old `.pkl` calibration files, convert them to `.nc` format:

```python
import pickle
import xarray as xr
import numpy as np

# Load pickle file
with open('calibration.pkl', 'rb') as f:
    cal_data = pickle.load(f)

# Create xarray Dataset
ds = xr.Dataset(
    data_vars={
        'wavelengths': (['wavelength_index'], cal_data['wavelengths']),
        'wavelengths_linear': (['wavelength_index'], cal_data['wavelengths_linear']),
        'smile_shifts': (['cross_track'], cal_data['smile_shifts']),
        'flat_field_pic': (['cross_track', 'wavelength_index'], cal_data['flat_field_pic']),
        'HgAr_pic': (['cross_track', 'wavelength_index'], cal_data['HgAr_pic']),
        'rad_ref': (['cross_track', 'wavelength_index', 'exposure', 'luminance'],
                    cal_data['rad_ref'].values),
        'sfit_x': (['sfit_points'], cal_data['sfit'].x),
        'sfit_y': (['sfit_points'], cal_data['sfit'].y),
    },
    coords={
        'cross_track': np.arange(cal_data['flat_field_pic'].shape[0]),
        'wavelength_index': np.arange(cal_data['wavelengths'].shape[0]),
        'exposure': cal_data['rad_ref'].coords['exposure'].values,
        'luminance': cal_data['rad_ref'].coords['luminance'].values,
    },
    attrs={
        'spec_rad_ref_luminance': cal_data.get('spec_rad_ref_luminance', 52020.0),
        'sfit_kind': 'cubic',
        'calibration_date': cal_data.get('datetime_str', 'unknown'),
    }
)

# Save as NetCDF
ds.to_netcdf('calibration.nc', mode='w', format='NETCDF4', engine='netcdf4')
print(f"Saved calibration to calibration.nc")
```

---

## Using Calibration in ROS2 Node

To use calibration data with your ROS2 hyperspectral node:

```bash
ros2 run openhsi_ros2 hyperspec_node --ros-args \
    -p camera_type:=lucid \
    -p config_file:=/path/to/cam_settings_lucid.json \
    -p cal_file:=/path/to/calibration.nc \
    -p processing_lvl:=2 \
    -p exposure_ms:=15.0
```

Where `processing_lvl`:
- `0` = Raw digital numbers
- `1` = Dark-subtracted
- `2` = Flat-fielded
- `3` = Radiance calibrated
- `4` = Reflectance (requires reference panel)

---

## Known HgAr Emission Lines

For reference, the HgAr lamp has strong emission lines at (nm):

```
404.656, 407.783, 435.833, 546.074, 576.960, 579.066,
696.543, 706.722, 727.294, 738.393, 750.387, 763.511,
772.376, 794.818, 800.616, 811.531, 826.452, 842.465, 912.297
```

The brightest lines typically used for calibration are:
- **435.833 nm** (Blue)
- **546.074 nm** (Green)
- **579.0 nm** (Yellow - doublet average)
- **763.511 nm** (Red)

---

## Troubleshooting

### Saturated HgAr Images
- Reduce camera gain
- Use fewer frames for averaging
- Reduce arc lamp intensity

### Poor Wavelength Fit
- Ensure HgAr lamp is warmed up (>5 minutes)
- Check that brightest peaks are correctly identified
- Try adjusting `find_peaks_height` and `prominence` parameters

### Integrating Sphere Issues
- Wait for sphere to stabilize at each luminance (2+ seconds)
- Verify sphere calibration is current
- Check for light leaks

---

## File Naming Convention

- Settings: `OpenHSI-{model:02d}_settings_{pixel_format}_bin{binning}.json`
- Calibration: `OpenHSI-{model:02d}_calibration_{pixel_format}_bin{binning}.nc`

Example for Camera #06, Mono12, binning=1:
- `OpenHSI-06_settings_Mono12_bin1.json`
- `OpenHSI-06_calibration_Mono12_bin1.nc`

---

## Additional Resources

- [OpenHSI Documentation](https://github.com/openHSI)
- [Lucid Arena SDK](https://thinklucid.com/downloads-hub/)
- [LabSphere SpectraPT Manual](https://www.labsphere.com/)
- [NIST Spectral Line Database](https://www.nist.gov/pml/atomic-spectra-database)
