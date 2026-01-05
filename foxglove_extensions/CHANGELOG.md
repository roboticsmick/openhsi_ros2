# Changelog

## 1.0.5 (2025-12-23)

### Features

- Waterfall now scrolls down like a true waterfall (newest at top)
- Spectrum panel positioned below waterfall instead of side
- Improved noise filtering using 1-99 percentile clipping per RGB channel

### Fixes

- Fixed click handler to correctly map display position to buffer line
- Improved UI hints for empty states

## 1.0.4 (2025-12-23)

### Fixes

- Fixed spatial/spectral axis interpretation (height=spatial, width=spectral)
- Topic names now use leading `/` for Foxglove bridge compatibility

## 1.0.3 (2025-12-23)

### Fixes

- Added leading `/` back to topic names for Foxglove bridge

## 1.0.2 (2025-12-23)

### Fixes

- Fixed React initialization in extension entry point
- Added debug logging to console for troubleshooting
- Added error display in panel UI
- Improved error handling in message processing

## 1.0.1 (2025-12-23)

### Fixes

- Fixed default topic names for ROS2 (removed leading slash)
- Added wavelength topic input to UI settings

## 1.0.0 (2025-12-22)

Initial release.

### Features

- RGB waterfall visualization from hyperspectral line scan images
- Multiple RGB presets: visible, vegetation, water, coral, custom
- Click-to-view spectrum at any point on the waterfall
- Automatic percentile-based normalization
- Configurable topic names and buffer size
- Works with ROS1 and ROS2 rosbags
