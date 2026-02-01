# HyperspectralImage.msg
# Bundles hyperspectral line scan image with wavelength calibration metadata
#
# This message combines a mono16 image with wavelength calibration data,
# allowing subscribers to interpret spectral information without needing
# to correlate multiple topics.
#
# Image layout (after transpose in capture node):
#   - height (rows) = spatial (cross-track pixels)
#   - width (cols) = spectral (wavelength bands)
#   - Each pixel value is the intensity at that spatial position and wavelength
#
# Axis order: "spatial,spectral" means:
#   - Row index corresponds to spatial position (cross-track)
#   - Column index corresponds to wavelength band

std_msgs/Header header

# The hyperspectral line scan image (mono16 encoding)
sensor_msgs/Image image

# Wavelength calibration for each column (spectral axis)
# Length should match image.width (number of spectral bands)
float64[] wavelengths_nm

# Wavelength range metadata
float64 wavelength_start_nm      # First wavelength (e.g., 400.0)
float64 wavelength_end_nm        # Last wavelength (e.g., 1000.0)
float64 pixel_dispersion_nm_px   # Wavelength spacing per pixel (e.g., 1.75)

# Axis interpretation
# "spatial,spectral" = rows are spatial, cols are spectral (default)
string axis_order

# Sensor metadata
uint8 bit_depth                  # Effective bit depth (12 for Mono12, 16 for Mono16)
float64 exposure_ms              # Exposure time in milliseconds
float64 sensor_temperature_c     # Sensor temperature in Celsius
