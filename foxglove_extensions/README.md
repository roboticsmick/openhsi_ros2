# Foxglove Hypercube Waterfall Panel

A Foxglove Studio extension for real-time visualization of hyperspectral pushbroom camera data. Renders line scan images as scrolling RGB waterfall displays with interactive spectrum analysis.

**Version:** 1.2.1
**Author:** Michael Venz
**License:** MIT

---

## Features

- **RGB Waterfall Display**: Converts hyperspectral line scans to false-color RGB in real-time
- **HyperspectralImage Support**: Automatic wavelength and axis configuration from ROS2 messages
- **Multiple RGB Presets**: Visible, vegetation, water, coral, and custom wavelength mappings
- **Interactive Spectrum Viewer**: Click anywhere on waterfall to view full spectral signature
- **Automatic Normalization**: Percentile-based dynamic range adjustment
- **Multi-Camera Support**: Works with both Lucid and XIMEA hyperspectral cameras
- **Axis Order Handling**: Automatically interprets `spectral,spatial` or `spatial,spectral` layouts

---

## Quick Start

### Installation

```bash
cd foxglove-hypercube-panel
npm install
npm run package
```

In Foxglove Studio:
1. Go to **Settings** (gear icon) → **Extensions**
2. Click **"Install local extension..."**
3. Select `rangerbot.foxglove-hypercube-panel-1.2.0.foxe`

### Basic Usage

1. Start your hyperspectral camera node (see [openhsi_ros2](../openhsi_ros2/))
2. Start Foxglove bridge: `ros2 launch foxglove_bridge foxglove_bridge_launch.xml`
3. Open Foxglove Studio and connect to `ws://localhost:8765`
4. Add panel: Click **"+"** → search **"Hypercube Waterfall"**
5. Enable **"Combined msg"** checkbox and set topic to `/hyperspec/hyperspectral_image`

---

## Configuration

### Topic Modes

The panel supports two modes for receiving hyperspectral data:

#### Combined Message Mode (Recommended)

Uses the `openhsi_msgs/HyperspectralImage` message which bundles image data with wavelength calibration:

| Setting | Value |
|---------|-------|
| ☑️ Combined msg | Enabled |
| Topic | `/hyperspec/hyperspectral_image` |

**Advantages:**
- Wavelengths automatically extracted from message
- Axis order (`spectral,spatial` or `spatial,spectral`) read from message
- Single topic subscription
- Works with any camera without manual configuration

#### Separate Topics Mode (Legacy)

For systems not publishing `HyperspectralImage`:

| Setting | Value |
|---------|-------|
| ☐ Combined msg | Disabled |
| Image | `/hyperspec/image_raw` |
| WL | `/hyperspec/wavelengths` |

### RGB Presets

| Preset | Red | Green | Blue | Application |
|--------|-----|-------|------|-------------|
| **visible** | 650nm | 550nm | 470nm | Natural true-color |
| **vegetation** | 800nm | 670nm | 550nm | Plant health (NIR-Red-Green) |
| **water** | 560nm | 490nm | 440nm | Water column analysis |
| **coral** | 680nm | 570nm | 480nm | Coral pigmentation |
| **custom** | User | User | User | Any wavelength combination |

### Panel Settings

| Setting | Range | Description |
|---------|-------|-------------|
| Lines | 32-1024 | Number of scan lines in waterfall buffer |
| Show Spectrum | on/off | Toggle spectrum viewer panel |
| Auto Normalize | on/off | Percentile-based dynamic range |
| Auto Y | on/off | Auto-scale spectrum Y-axis to data range |
| Y Max | 1-65535 | Fixed Y-axis maximum when Auto Y is off (4095 for Mono12, 65535 for Mono16) |

---

## Data Format

### HyperspectralImage Message (openhsi_msgs)

```
std_msgs/Header header
sensor_msgs/Image image           # mono16 encoded line scan
float64[] wavelengths_nm          # Wavelength per spectral band
float64 wavelength_start_nm       # First wavelength (e.g., 426.07)
float64 wavelength_end_nm         # Last wavelength (e.g., 897.69)
float64 pixel_dispersion_nm_px    # nm per pixel (e.g., 0.895)
string axis_order                 # "spectral,spatial" or "spatial,spectral"
float64 exposure_ms
float64 sensor_temperature_c
```

### Image Layout

The `axis_order` field determines how image dimensions are interpreted:

| axis_order | height (rows) | width (cols) | Camera |
|------------|---------------|--------------|--------|
| `spectral,spatial` | Wavelength bands | Spatial pixels | Lucid (after transpose) |
| `spatial,spectral` | Spatial pixels | Wavelength bands | XIMEA (default) |

### Supported Encodings

- **mono16**: 16-bit unsigned (0-65535 for Mono16, 0-4095 for Mono12)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                  Foxglove Hypercube Panel v1.2.0                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                     Settings Bar                          │   │
│  │  [☑ Combined msg] [Topic: /hyperspec/hyperspectral_image]│   │
│  │  [RGB: visible ▼] [Lines: 256] [448x532 | 150 frames]    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌────────────────────────────────┬─────────────────────────┐   │
│  │      Waterfall Canvas          │    Spectrum Canvas      │   │
│  │  ┌──────────────────────────┐  │  ┌───────────────────┐  │   │
│  │  │  Newest line (top)       │  │  │ Intensity         │  │   │
│  │  │  ████████████████████    │  │  │    ∧              │  │   │
│  │  │  ████████████████████    │  │  │   /│\    /\       │  │   │
│  │  │  ████████████████████    │◄─┼──┤  / │ \  /  \      │  │   │
│  │  │  ████████████████████    │  │  │ /  │  \/    \     │  │   │
│  │  │  Oldest line (bottom)    │  │  │/   R  G     B\    │  │   │
│  │  └──────────────────────────┘  │  └───────────────────┘  │   │
│  │     Click to select pixel      │   426nm ────────► 898nm │   │
│  └────────────────────────────────┴─────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  WL: 426-898nm (532)  │  axis: spectral,spatial  │ [☑ Show]│
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Component Overview

```
src/
├── index.ts              # Extension registration
├── HypercubePanel.tsx    # Main React component
│   ├── Topic subscription logic
│   ├── HyperspectralImage message parsing
│   ├── Waterfall canvas rendering
│   └── Spectrum canvas rendering
├── spectralUtils.ts      # Data processing utilities
│   ├── WaterfallBuffer   # Circular buffer for line storage
│   ├── parseMono16Image  # Binary parsing with transpose
│   ├── findRGBIndices    # Wavelength → band index mapping
│   └── generateWavelengths # Default calibration
└── types.ts              # TypeScript interfaces
    ├── ImageMessage
    ├── HyperspectralImageMessage
    ├── PanelSettings
    └── SpectrumData
```

### Data Flow

```
ROS2 Topic                    Foxglove Panel
─────────────────────────────────────────────────────────────────

/hyperspec/hyperspectral_image
        │
        ▼
┌───────────────────┐         ┌─────────────────────────────────┐
│ HyperspectralImage│────────▶│ onRender callback               │
│   - image         │         │   ├─ Extract wavelengths_nm     │
│   - wavelengths_nm│         │   ├─ Extract axis_order         │
│   - axis_order    │         │   └─ processImageData()         │
└───────────────────┘         └─────────────┬───────────────────┘
                                            │
                                            ▼
                              ┌─────────────────────────────────┐
                              │ parseMono16Image()              │
                              │   - Parse bytes (little-endian) │
                              │   - Transpose if needed         │
                              │   - Return Uint16Array          │
                              └─────────────┬───────────────────┘
                                            │
                                            ▼
                              ┌─────────────────────────────────┐
                              │ WaterfallBuffer.addLine()       │
                              │   - Circular buffer storage     │
                              │   - Stores [spatial][spectral]  │
                              └─────────────┬───────────────────┘
                                            │
                                            ▼
                              ┌─────────────────────────────────┐
                              │ renderWaterfall()               │
                              │   - toRGBImageData(r,g,b idx)   │
                              │   - Percentile normalization    │
                              │   - putImageData to canvas      │
                              └─────────────────────────────────┘
```

---

## Development

### Prerequisites

- Node.js 18+
- npm 9+

### Commands

```bash
# Install dependencies
npm install

# Development build with watch
npm run dev

# Production build
npm run build

# Create installable .foxe package
npm run package

# Clean build artifacts
npm run clean
```

### Development Mode

For live development with hot reload:

```bash
npm run dev
```

In Foxglove Studio:
1. **Settings** → **Extensions**
2. Enable **"Load extensions from local development server"**
3. Panel auto-reloads on source changes

### Project Structure

```
foxglove-hypercube-panel/
├── package.json            # Dependencies and npm scripts
├── tsconfig.json           # TypeScript configuration
├── src/
│   ├── index.ts            # Extension entry point & registration
│   ├── HypercubePanel.tsx  # Main panel React component (750 lines)
│   ├── spectralUtils.ts    # Buffer, parsing, wavelength utilities
│   └── types.ts            # TypeScript interfaces & defaults
├── dist/                   # Build output (generated)
└── *.foxe                  # Packaged extension (generated)
```

---

## Troubleshooting

### "Waiting for hyperspectral data..."

1. Verify camera node is running: `ros2 topic list | grep hyperspec`
2. Check Foxglove bridge is running: `ros2 launch foxglove_bridge foxglove_bridge_launch.xml`
3. Confirm topic name matches panel settings
4. Verify "Combined msg" checkbox matches your topic type

### Waterfall shows stretched/distorted image

1. Check `axis_order` in footer matches your camera
2. For Lucid cameras: should show `spectral,spatial`
3. For XIMEA cameras: should show `spatial,spectral`

### Wrong wavelength range displayed

1. Ensure using Combined msg mode with HyperspectralImage topic
2. Check camera config has correct `wavelength_start_nm`, `wavelength_end_nm`
3. Verify `num_spectral_bands` matches actual band count

### Colors appear washed out or clipped

1. Try different RGB presets
2. Adjust normalization percentiles (default: 1%-99%)
3. Check exposure settings on camera

### Spectrum shows unexpected values

1. Click on a brighter region of the waterfall
2. Verify wavelength calibration is correct
3. Check that clicked position is within valid data bounds

### Spectrum Y-axis clipped with bright light

1. Uncheck "Auto Y" in the spectrum panel header to use fixed scaling
2. Set "Y Max" to match your camera's bit depth:
   - Mono12 cameras: 4095
   - Mono16 cameras: 65535
3. Or keep "Auto Y" enabled and the plot will scale to fit the current data range

---

## Related Packages

| Package | Description |
|---------|-------------|
| [openhsi_ros2](../openhsi_ros2/) | ROS2 node for Lucid/XIMEA hyperspectral cameras |
| [openhsi_msgs](../openhsi_msgs/) | Custom ROS2 messages (HyperspectralImage) |

---

## Version History

### v1.2.1 (2024-12)

- Added spectrum Y-axis scaling controls (Auto Y / Fixed Y Max)
- Added Y-axis value labels to spectrum plot
- Fixed spectrum clipping with bright light sources

### v1.2.0 (2024-12)
- Added HyperspectralImage message support
- Added axis_order handling for multi-camera support
- Added Combined msg mode toggle
- Added axis_order display in footer
- Improved wavelength extraction from messages

### v1.1.0 (2024-12)
- Fixed waterfall stretching issue
- Added proper canvas sizing
- Improved mono16 parsing with transpose

### v1.0.0 (2024-11)
- Initial release
- Basic waterfall display
- RGB preset support
- Spectrum viewer

---

## License

MIT License - See [LICENSE](LICENSE) for details.
