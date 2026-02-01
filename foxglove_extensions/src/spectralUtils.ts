/**
 * Spectral processing utilities for hypercube data
 */

/**
 * Find the index of the closest wavelength to the target
 */
export function findWavelengthIndex(
  wavelengths: number[],
  targetNm: number
): number {
  let minDiff = Infinity;
  let minIndex = 0;

  for (let i = 0; i < wavelengths.length; i++) {
    const diff = Math.abs(wavelengths[i] - targetNm);
    if (diff < minDiff) {
      minDiff = diff;
      minIndex = i;
    }
  }

  return minIndex;
}

/**
 * Find RGB band indices from wavelengths
 */
export function findRGBIndices(
  wavelengths: number[],
  redNm: number,
  greenNm: number,
  blueNm: number
): { rIdx: number; gIdx: number; bIdx: number } {
  return {
    rIdx: findWavelengthIndex(wavelengths, redNm),
    gIdx: findWavelengthIndex(wavelengths, greenNm),
    bIdx: findWavelengthIndex(wavelengths, blueNm),
  };
}

/**
 * Generate default wavelengths from config parameters
 */
export function generateWavelengths(
  numBands: number,
  pixel0Wavelength: number,
  dispersionNmPerPx: number,
  spectralOffset: number = 0
): number[] {
  const wavelengths: number[] = [];
  for (let i = 0; i < numBands; i++) {
    const pixelIndex = spectralOffset + i;
    wavelengths.push(pixel0Wavelength + pixelIndex * dispersionNmPerPx);
  }
  return wavelengths;
}

/**
 * Calculate percentile of an array
 */
export function percentile(arr: number[], p: number): number {
  if (arr.length === 0) return 0;
  const sorted = [...arr].sort((a, b) => a - b);
  const index = (p / 100) * (sorted.length - 1);
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  if (lower === upper) return sorted[lower]!;
  return sorted[lower]! + (sorted[upper]! - sorted[lower]!) * (index - lower);
}

/**
 * Normalize a value to 0-255 range using percentile clipping
 */
export function normalizeValue(
  value: number,
  pLow: number,
  pHigh: number
): number {
  if (pHigh <= pLow) return 0;
  const normalized = (value - pLow) / (pHigh - pLow);
  return Math.max(0, Math.min(255, Math.round(normalized * 255)));
}

/**
 * Circular buffer for accumulating spectral lines
 */
export class WaterfallBuffer {
  private buffer: Uint16Array[];
  private writePointer: number = 0;
  private isFull: boolean = false;
  private readonly nLines: number;
  private readonly nSpatial: number;
  private readonly nSpectral: number;

  constructor(nLines: number, nSpatial: number, nSpectral: number) {
    this.nLines = nLines;
    this.nSpatial = nSpatial;
    this.nSpectral = nSpectral;
    this.buffer = [];

    // Pre-allocate buffer
    for (let i = 0; i < nLines; i++) {
      this.buffer.push(new Uint16Array(nSpatial * nSpectral));
    }
  }

  /**
   * Add a new line to the buffer
   */
  addLine(lineData: Uint16Array): void {
    if (lineData.length !== this.nSpatial * this.nSpectral) {
      console.warn(
        `Line data size mismatch: expected ${this.nSpatial * this.nSpectral}, got ${lineData.length}`
      );
      return;
    }

    this.buffer[this.writePointer]!.set(lineData);
    this.writePointer++;

    if (this.writePointer >= this.nLines) {
      this.writePointer = 0;
      this.isFull = true;
    }
  }

  /**
   * Get the number of valid lines in the buffer
   */
  getLineCount(): number {
    return this.isFull ? this.nLines : this.writePointer;
  }

  /**
   * Get a specific line in chronological order (0 = oldest)
   */
  getLine(index: number): Uint16Array | null {
    const lineCount = this.getLineCount();
    if (index < 0 || index >= lineCount) return null;

    if (this.isFull) {
      // Unwrap circular buffer
      const actualIndex = (this.writePointer + index) % this.nLines;
      return this.buffer[actualIndex]!;
    } else {
      return this.buffer[index]!;
    }
  }

  /**
   * Get pixel value at specific position
   */
  getPixel(lineIndex: number, spatialX: number, spectralBand: number): number {
    const line = this.getLine(lineIndex);
    if (!line) return 0;

    const idx = spatialX * this.nSpectral + spectralBand;
    return line[idx] ?? 0;
  }

  /**
   * Get full spectrum at a spatial position for a line
   */
  getSpectrum(lineIndex: number, spatialX: number): number[] {
    const line = this.getLine(lineIndex);
    if (!line) return [];

    const spectrum: number[] = [];
    const startIdx = spatialX * this.nSpectral;
    for (let i = 0; i < this.nSpectral; i++) {
      spectrum.push(line[startIdx + i] ?? 0);
    }
    return spectrum;
  }

  /**
   * Convert buffer to RGB image data
   * Renders with newest lines at TOP (y=0), scrolling downward like a waterfall
   */
  toRGBImageData(
    rIdx: number,
    gIdx: number,
    bIdx: number,
    normalize: boolean = true,
    pLow: number = 1,
    pHigh: number = 99
  ): ImageData {
    const lineCount = this.getLineCount();
    const imageData = new ImageData(this.nSpatial, lineCount);

    if (lineCount === 0) return imageData;

    // Collect all R, G, B values for normalization
    let rValues: number[] = [];
    let gValues: number[] = [];
    let bValues: number[] = [];

    if (normalize) {
      for (let y = 0; y < lineCount; y++) {
        const line = this.getLine(y)!;
        for (let x = 0; x < this.nSpatial; x++) {
          const baseIdx = x * this.nSpectral;
          rValues.push(line[baseIdx + rIdx]!);
          gValues.push(line[baseIdx + gIdx]!);
          bValues.push(line[baseIdx + bIdx]!);
        }
      }
    }

    // Calculate percentiles for each channel (clips outliers/noise)
    const rPLow = normalize ? percentile(rValues, pLow) : 0;
    const rPHigh = normalize ? percentile(rValues, pHigh) : 65535;
    const gPLow = normalize ? percentile(gValues, pLow) : 0;
    const gPHigh = normalize ? percentile(gValues, pHigh) : 65535;
    const bPLow = normalize ? percentile(bValues, pLow) : 0;
    const bPHigh = normalize ? percentile(bValues, pHigh) : 65535;

    // Fill image data - REVERSED: newest line (lineCount-1) at y=0, oldest at bottom
    for (let y = 0; y < lineCount; y++) {
      // Flip: display row y gets data from line (lineCount - 1 - y)
      const sourceLineIdx = lineCount - 1 - y;
      const line = this.getLine(sourceLineIdx)!;
      for (let x = 0; x < this.nSpatial; x++) {
        const baseIdx = x * this.nSpectral;
        const r = line[baseIdx + rIdx]!;
        const g = line[baseIdx + gIdx]!;
        const b = line[baseIdx + bIdx]!;

        const pixelIdx = (y * this.nSpatial + x) * 4;
        imageData.data[pixelIdx] = normalizeValue(r, rPLow, rPHigh);
        imageData.data[pixelIdx + 1] = normalizeValue(g, gPLow, gPHigh);
        imageData.data[pixelIdx + 2] = normalizeValue(b, bPLow, bPHigh);
        imageData.data[pixelIdx + 3] = 255; // Alpha
      }
    }

    return imageData;
  }

  /**
   * Clear the buffer
   */
  clear(): void {
    this.writePointer = 0;
    this.isFull = false;
    for (const line of this.buffer) {
      line.fill(0);
    }
  }

  /**
   * Get dimensions
   */
  getDimensions(): { nLines: number; nSpatial: number; nSpectral: number } {
    return {
      nLines: this.nLines,
      nSpatial: this.nSpatial,
      nSpectral: this.nSpectral,
    };
  }
}

/**
 * Parse mono16 image data from ROS Image message
 *
 * The WaterfallBuffer expects data in (spatial, spectral) order:
 *   - data[spatial * nSpectral + spectral] = pixel value
 *
 * Depending on axis_order:
 *   - "spectral,spatial": height=spectral, width=spatial → needs transpose
 *   - "spatial,spectral": height=spatial, width=spectral → direct copy
 */
export function parseMono16Image(
  data: Uint8Array | ArrayBuffer,
  width: number,
  height: number,
  isBigEndian: boolean,
  axisOrder: string = "spectral,spatial"
): Uint16Array {
  const bytes = data instanceof ArrayBuffer ? new Uint8Array(data) : data;

  let nSpatial: number;
  let nSpectral: number;

  if (axisOrder === "spectral,spatial") {
    // height=spectral, width=spatial (Lucid after transpose)
    nSpectral = height;
    nSpatial = width;
  } else {
    // "spatial,spectral" - height=spatial, width=spectral (XIMEA)
    nSpatial = height;
    nSpectral = width;
  }

  const result = new Uint16Array(nSpatial * nSpectral);

  if (axisOrder === "spectral,spatial") {
    // Transpose from (spectral, spatial) row-major to (spatial, spectral) order
    // Input: data[spectral_row * width + spatial_col]
    // Output: result[spatial * nSpectral + spectral]
    for (let spectral = 0; spectral < nSpectral; spectral++) {
      for (let spatial = 0; spatial < nSpatial; spatial++) {
        const srcIdx = spectral * nSpatial + spatial;
        const byteIdx = srcIdx * 2;

        let pixelValue: number;
        if (isBigEndian) {
          pixelValue = (bytes[byteIdx]! << 8) | bytes[byteIdx + 1]!;
        } else {
          pixelValue = bytes[byteIdx]! | (bytes[byteIdx + 1]! << 8);
        }

        // Store in transposed order: (spatial, spectral)
        const dstIdx = spatial * nSpectral + spectral;
        result[dstIdx] = pixelValue;
      }
    }
  } else {
    // "spatial,spectral" - direct copy, data is already in correct order
    // Input: data[spatial_row * width + spectral_col]
    // Output: result[spatial * nSpectral + spectral]
    for (let spatial = 0; spatial < nSpatial; spatial++) {
      for (let spectral = 0; spectral < nSpectral; spectral++) {
        const srcIdx = spatial * nSpectral + spectral;
        const byteIdx = srcIdx * 2;

        let pixelValue: number;
        if (isBigEndian) {
          pixelValue = (bytes[byteIdx]! << 8) | bytes[byteIdx + 1]!;
        } else {
          pixelValue = bytes[byteIdx]! | (bytes[byteIdx + 1]! << 8);
        }

        result[srcIdx] = pixelValue;
      }
    }
  }

  return result;
}
