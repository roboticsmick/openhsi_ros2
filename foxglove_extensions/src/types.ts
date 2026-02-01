/**
 * Type definitions for hyperspectral data
 */

/**
 * ROS sensor_msgs/Image message structure
 */
export interface ImageMessage {
  header: {
    stamp: { sec: number; nsec: number };
    frame_id: string;
  };
  height: number;
  width: number;
  encoding: string;
  is_bigendian: boolean;
  step: number;
  data: Uint8Array | ArrayBuffer;
}

/**
 * Wavelength calibration message (hyperspecWavelengths)
 */
export interface WavelengthMessage {
  header: {
    stamp: { sec: number; nsec: number };
    frame_id: string;
  };
  wavelengths: number[] | Float64Array;
  pixel_dispersion_nm: number;
  spectral_range_start: number;
  spectral_range_end: number;
  num_spectral_bands: number;
}

/**
 * HyperspectralImage message (openhsi_msgs/HyperspectralImage)
 * Bundles image with wavelength calibration metadata
 */
export interface HyperspectralImageMessage {
  header: {
    stamp: { sec: number; nsec: number };
    frame_id: string;
  };
  image: ImageMessage;
  wavelengths_nm: number[] | Float64Array;
  wavelength_start_nm: number;
  wavelength_end_nm: number;
  pixel_dispersion_nm_px: number;
  axis_order: string;  // "spatial,spectral" or "spectral,spatial"
  exposure_ms: number;
  sensor_temperature_c: number;
}

/**
 * RGB wavelength preset configuration
 */
export interface RGBPreset {
  name: string;
  red: number;
  green: number;
  blue: number;
  description: string;
}

/**
 * Panel settings stored in Foxglove layout
 */
export interface PanelSettings {
  imageTopic: string;
  wavelengthTopic: string;
  hyperspectralTopic: string;  // Combined HyperspectralImage topic
  useHyperspectralMsg: boolean; // Whether to use HyperspectralImage or separate topics
  manualAxisOrder: string;      // Axis order for separate topics mode ("auto", "spatial,spectral" or "spectral,spatial")
  waterfallLines: number;
  rgbPreset: string;
  customRedNm: number;
  customGreenNm: number;
  customBlueNm: number;
  autoNormalize: boolean;
  normalizePercentileLow: number;
  normalizePercentileHigh: number;
  showSpectrum: boolean;
  selectedPixelX: number | null;
  selectedPixelY: number | null;
  // Spectrum Y-axis settings
  spectrumAutoScaleY: boolean;  // Auto-scale Y axis to data range
  spectrumYMax: number;         // Fixed Y maximum when not auto-scaling (e.g., 4095 for 12-bit)
  // Waterfall display transforms
  flipVertical: boolean;        // Flip waterfall on vertical axis (mirror left-right)
  flipHorizontal: boolean;      // Flip waterfall on horizontal axis (mirror top-bottom)
}

/**
 * Default settings
 */
export const DEFAULT_SETTINGS: PanelSettings = {
  imageTopic: "/hyperspec/image_raw",
  wavelengthTopic: "/hyperspec/wavelengths",
  hyperspectralTopic: "/hyperspec/hyperspectral_image",
  useHyperspectralMsg: true,  // Prefer HyperspectralImage by default
  manualAxisOrder: "auto",  // Auto-detect from wavelength count vs image dimensions
  waterfallLines: 256,
  rgbPreset: "visible",
  customRedNm: 650,
  customGreenNm: 550,
  customBlueNm: 470,
  autoNormalize: true,
  normalizePercentileLow: 1,  // Clip bottom 1% (noise floor)
  normalizePercentileHigh: 99, // Clip top 1% (outliers)
  showSpectrum: true,
  selectedPixelX: null,
  selectedPixelY: null,
  spectrumAutoScaleY: true,   // Auto-scale by default
  spectrumYMax: 4095,         // 12-bit max (Mono12 cameras)
  flipVertical: false,        // No flip by default
  flipHorizontal: false,      // No flip by default
};

/**
 * Available RGB presets
 */
export const RGB_PRESETS: RGBPreset[] = [
  {
    name: "visible",
    red: 650,
    green: 550,
    blue: 470,
    description: "Natural color (visible spectrum)",
  },
  {
    name: "vegetation",
    red: 800,
    green: 670,
    blue: 550,
    description: "NIR-Red-Green for plant health",
  },
  {
    name: "water",
    red: 560,
    green: 490,
    blue: 440,
    description: "Water column analysis",
  },
  {
    name: "coral",
    red: 680,
    green: 570,
    blue: 480,
    description: "Coral pigmentation",
  },
  {
    name: "custom",
    red: 650,
    green: 550,
    blue: 470,
    description: "Custom wavelengths",
  },
];

/**
 * Spectrum data for a selected pixel
 */
export interface SpectrumData {
  wavelengths: number[];
  intensities: number[];
  pixelX: number;
  lineIndex: number;
  timestamp: number;
}
