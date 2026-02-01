import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { PanelExtensionContext, SettingsTreeAction, SettingsTreeNodes } from "@foxglove/extension";

import {
  ImageMessage,
  HyperspectralImageMessage,
  PanelSettings,
  DEFAULT_SETTINGS,
  RGB_PRESETS,
  SpectrumData,
} from "./types";
import {
  WaterfallBuffer,
  findRGBIndices,
  generateWavelengths,
  parseMono16Image,
} from "./spectralUtils";

/**
 * Build settings tree for the Foxglove settings panel sidebar
 */
function buildSettingsTree(settings: PanelSettings): SettingsTreeNodes {
  return {
    topics: {
      label: "Topics",
      fields: {
        useHyperspectralMsg: {
          label: "Use Combined Message",
          input: "boolean",
          value: settings.useHyperspectralMsg,
          help: "Use HyperspectralImage message (combined image + wavelengths)",
        },
        hyperspectralTopic: {
          label: "Hyperspectral Topic",
          input: "string",
          value: settings.hyperspectralTopic,
          disabled: !settings.useHyperspectralMsg,
        },
        imageTopic: {
          label: "Image Topic",
          input: "string",
          value: settings.imageTopic,
          disabled: settings.useHyperspectralMsg,
        },
        wavelengthTopic: {
          label: "Wavelength Topic",
          input: "string",
          value: settings.wavelengthTopic,
          disabled: settings.useHyperspectralMsg,
        },
      },
    },
    axis: {
      label: "Axis Configuration",
      fields: {
        manualAxisOrder: {
          label: "Axis Order",
          input: "select",
          value: settings.manualAxisOrder,
          options: [
            { label: "Auto (detect from WL count)", value: "auto" },
            { label: "spatial,spectral (XIMEA/ROS1)", value: "spatial,spectral" },
            { label: "spectral,spatial (Lucid)", value: "spectral,spatial" },
          ],
          disabled: settings.useHyperspectralMsg,
          help: "For separate topics mode only. Combined messages include axis order.",
        },
      },
    },
    waterfall: {
      label: "Waterfall Display",
      fields: {
        waterfallLines: {
          label: "Buffer Lines",
          input: "number",
          value: settings.waterfallLines,
          min: 32,
          max: 1024,
          step: 32,
          help: "Number of lines to keep in waterfall buffer",
        },
        flipVertical: {
          label: "Flip Vertical",
          input: "boolean",
          value: settings.flipVertical,
          help: "Mirror waterfall left-right (flip on vertical axis)",
        },
        flipHorizontal: {
          label: "Flip Horizontal",
          input: "boolean",
          value: settings.flipHorizontal,
          help: "Mirror waterfall top-bottom (flip on horizontal axis)",
        },
      },
    },
    rgb: {
      label: "RGB Composition",
      fields: {
        rgbPreset: {
          label: "RGB Preset",
          input: "select",
          value: settings.rgbPreset,
          options: RGB_PRESETS.map((p) => ({
            label: `${p.name} (${p.red}/${p.green}/${p.blue}nm)`,
            value: p.name,
          })),
        },
        customRedNm: {
          label: "Red (nm)",
          input: "number",
          value: settings.customRedNm,
          min: 350,
          max: 1100,
          disabled: settings.rgbPreset !== "custom",
        },
        customGreenNm: {
          label: "Green (nm)",
          input: "number",
          value: settings.customGreenNm,
          min: 350,
          max: 1100,
          disabled: settings.rgbPreset !== "custom",
        },
        customBlueNm: {
          label: "Blue (nm)",
          input: "number",
          value: settings.customBlueNm,
          min: 350,
          max: 1100,
          disabled: settings.rgbPreset !== "custom",
        },
      },
    },
    normalization: {
      label: "Image Normalization",
      fields: {
        autoNormalize: {
          label: "Auto Normalize",
          input: "boolean",
          value: settings.autoNormalize,
          help: "Automatically normalize using percentile clipping",
        },
        normalizePercentileLow: {
          label: "Low Percentile (%)",
          input: "number",
          value: settings.normalizePercentileLow,
          min: 0,
          max: 50,
          step: 0.5,
          disabled: !settings.autoNormalize,
        },
        normalizePercentileHigh: {
          label: "High Percentile (%)",
          input: "number",
          value: settings.normalizePercentileHigh,
          min: 50,
          max: 100,
          step: 0.5,
          disabled: !settings.autoNormalize,
        },
      },
    },
    spectrum: {
      label: "Spectrum Panel",
      fields: {
        showSpectrum: {
          label: "Show Spectrum",
          input: "boolean",
          value: settings.showSpectrum,
        },
        spectrumAutoScaleY: {
          label: "Auto Scale Y",
          input: "boolean",
          value: settings.spectrumAutoScaleY,
          disabled: !settings.showSpectrum,
        },
        spectrumYMax: {
          label: "Y-Axis Max",
          input: "number",
          value: settings.spectrumYMax,
          min: 1,
          max: 65535,
          disabled: !settings.showSpectrum || settings.spectrumAutoScaleY,
        },
      },
    },
  };
}

/**
 * Hypercube Waterfall Panel
 *
 * Displays hyperspectral line scan data as a scrolling RGB waterfall.
 * Click on the waterfall to view the spectrum at that point.
 */
export function HypercubePanel({
  context,
}: {
  context: PanelExtensionContext;
}): JSX.Element {
  // Debug: log that component mounted
  console.log("[HypercubePanel] Component mounting...");

  // Panel state
  const [settings, setSettings] = useState<PanelSettings>(() => {
    const saved = context.initialState as Partial<PanelSettings> | undefined;
    console.log("[HypercubePanel] Initial state:", saved);
    return { ...DEFAULT_SETTINGS, ...saved };
  });

  const [wavelengths, setWavelengths] = useState<number[] | null>(null);
  const [dimensions, setDimensions] = useState<{
    spatial: number;
    spectral: number;
  } | null>(null);
  const [selectedSpectrum, setSelectedSpectrum] = useState<SpectrumData | null>(
    null
  );
  const [messageCount, setMessageCount] = useState(0);
  const [lastError, setLastError] = useState<string | null>(null);

  // Refs
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const spectrumCanvasRef = useRef<HTMLCanvasElement>(null);
  const bufferRef = useRef<WaterfallBuffer | null>(null);
  const renderRequestRef = useRef<number | null>(null);

  // Save state when settings change
  useEffect(() => {
    context.saveState(settings);
  }, [context, settings]);

  // Handle settings changes from Foxglove sidebar
  const handleSettingsAction = useCallback((action: SettingsTreeAction) => {
    if (action.action === "update") {
      const { path, value } = action.payload;
      setSettings((prev) => {
        const newSettings = { ...prev };
        const key = path[1] as keyof PanelSettings;
        if (key in newSettings) {
          (newSettings as Record<string, unknown>)[key] = value;
        }
        return newSettings;
      });
    }
  }, []);

  // Update settings tree in Foxglove sidebar when settings change
  useEffect(() => {
    context.updatePanelSettingsEditor({
      actionHandler: handleSettingsAction,
      nodes: buildSettingsTree(settings),
    });
  }, [context, handleSettingsAction, settings]);

  // State for axis order from HyperspectralImage message or auto-detection
  const [axisOrder, setAxisOrder] = useState<string>("spatial,spectral");
  const [detectedAxisOrder, setDetectedAxisOrder] = useState<string | null>(null);

  // Subscribe to topics based on mode
  useEffect(() => {
    if (settings.useHyperspectralMsg) {
      // Subscribe to combined HyperspectralImage topic
      context.subscribe([{ topic: settings.hyperspectralTopic }]);
    } else {
      // Subscribe to separate image and wavelength topics
      context.subscribe([
        { topic: settings.imageTopic },
        { topic: settings.wavelengthTopic },
      ]);
    }
  }, [context, settings.useHyperspectralMsg, settings.hyperspectralTopic, settings.imageTopic, settings.wavelengthTopic]);

  // Get RGB indices
  const rgbIndices = useMemo(() => {
    if (!wavelengths) return null;

    const preset = RGB_PRESETS.find((p) => p.name === settings.rgbPreset);
    const redNm =
      settings.rgbPreset === "custom"
        ? settings.customRedNm
        : preset?.red ?? 650;
    const greenNm =
      settings.rgbPreset === "custom"
        ? settings.customGreenNm
        : preset?.green ?? 550;
    const blueNm =
      settings.rgbPreset === "custom"
        ? settings.customBlueNm
        : preset?.blue ?? 470;

    return findRGBIndices(wavelengths, redNm, greenNm, blueNm);
  }, [wavelengths, settings.rgbPreset, settings.customRedNm, settings.customGreenNm, settings.customBlueNm]);

  // Render waterfall to canvas
  const renderWaterfall = useCallback(() => {
    const canvas = canvasRef.current;
    const buffer = bufferRef.current;
    if (!canvas || !buffer || !rgbIndices) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const { rIdx, gIdx, bIdx } = rgbIndices;
    const lineCount = buffer.getLineCount();
    const dims = buffer.getDimensions();

    // Set canvas to ACTUAL data dimensions (not max buffer size)
    // This prevents stretching when buffer is partially filled
    // Width = spatial pixels (cross-track), Height = lines received so far
    const targetWidth = dims.nSpatial;
    const targetHeight = Math.max(1, lineCount);

    if (canvas.width !== targetWidth || canvas.height !== targetHeight) {
      canvas.width = targetWidth;
      canvas.height = targetHeight;
    }

    // Clear canvas
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    if (lineCount === 0) return;

    const imageData = buffer.toRGBImageData(
      rIdx,
      gIdx,
      bIdx,
      settings.autoNormalize,
      settings.normalizePercentileLow,
      settings.normalizePercentileHigh
    );

    // Draw image data directly - no stretching needed since canvas matches data size
    ctx.putImageData(imageData, 0, 0);
  }, [rgbIndices, settings.autoNormalize, settings.normalizePercentileLow, settings.normalizePercentileHigh]);

  // Render spectrum chart
  const renderSpectrum = useCallback(() => {
    const canvas = spectrumCanvasRef.current;
    if (!canvas || !selectedSpectrum || !wavelengths) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const { width, height } = canvas;
    const { intensities } = selectedSpectrum;

    // Clear
    ctx.fillStyle = "#1a1a2e";
    ctx.fillRect(0, 0, width, height);

    if (intensities.length === 0) return;

    // Determine Y-axis range based on settings
    let minVal: number;
    let maxVal: number;
    if (settings.spectrumAutoScaleY) {
      // Auto-scale to data range
      minVal = Math.min(...intensities);
      maxVal = Math.max(...intensities);
    } else {
      // Fixed range: 0 to spectrumYMax
      minVal = 0;
      maxVal = settings.spectrumYMax;
    }
    const range = maxVal - minVal || 1;

    // Draw grid with Y-axis labels
    ctx.strokeStyle = "#333";
    ctx.lineWidth = 1;
    ctx.fillStyle = "#666";
    ctx.font = "9px monospace";
    ctx.textAlign = "right";
    for (let i = 0; i <= 4; i++) {
      const y = (height * i) / 4;
      ctx.beginPath();
      ctx.moveTo(40, y);
      ctx.lineTo(width, y);
      ctx.stroke();
      // Y-axis label (inverted because canvas Y is top-down)
      const yValue = maxVal - (i / 4) * range;
      ctx.fillText(yValue.toFixed(0), 38, y + 3);
    }

    // Draw spectrum line
    ctx.strokeStyle = "#00ff88";
    ctx.lineWidth = 2;
    ctx.beginPath();

    const plotLeft = 42;
    const plotWidth = width - plotLeft - 5;
    const plotHeight = height - 25;
    const plotTop = 5;

    for (let i = 0; i < intensities.length; i++) {
      const x = plotLeft + (i / (intensities.length - 1)) * plotWidth;
      // Clamp values to range to prevent drawing outside canvas
      const clampedVal = Math.max(minVal, Math.min(maxVal, intensities[i]!));
      const y = plotTop + plotHeight - ((clampedVal - minVal) / range) * plotHeight;

      if (i === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.stroke();

    // Draw wavelength labels
    ctx.fillStyle = "#888";
    ctx.font = "10px monospace";
    ctx.textAlign = "center";

    const wlMin = wavelengths[0] ?? 0;
    const wlMax = wavelengths[wavelengths.length - 1] ?? 1000;
    ctx.fillText(`${wlMin.toFixed(0)}nm`, plotLeft + 20, height - 2);
    ctx.fillText(`${wlMax.toFixed(0)}nm`, width - 30, height - 2);

    // Draw RGB marker lines
    if (rgbIndices) {
      const drawMarker = (idx: number, color: string, label: string) => {
        const x = plotLeft + (idx / (wavelengths.length - 1)) * plotWidth;
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(x, plotTop);
        ctx.lineTo(x, plotTop + plotHeight);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = color;
        ctx.fillText(label, x, plotTop + 10);
      };

      drawMarker(rgbIndices.rIdx, "#ff4444", "R");
      drawMarker(rgbIndices.gIdx, "#44ff44", "G");
      drawMarker(rgbIndices.bIdx, "#4444ff", "B");
    }

    // Draw pixel info and scale mode
    ctx.fillStyle = "#fff";
    ctx.textAlign = "left";
    ctx.fillText(
      `Pixel: (${selectedSpectrum.pixelX}, ${selectedSpectrum.lineIndex})`,
      plotLeft + 5,
      plotTop + 10
    );
    // Show scale mode indicator
    ctx.fillStyle = "#666";
    ctx.textAlign = "right";
    ctx.fillText(
      settings.spectrumAutoScaleY ? "Auto" : `Fixed 0-${settings.spectrumYMax}`,
      width - 5,
      plotTop + 10
    );
  }, [selectedSpectrum, wavelengths, rgbIndices, settings.spectrumAutoScaleY, settings.spectrumYMax]);

  // Handle canvas click
  const handleCanvasClick = useCallback(
    (event: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      const buffer = bufferRef.current;
      if (!canvas || !buffer || !wavelengths) return;

      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;

      let x = Math.floor((event.clientX - rect.left) * scaleX);
      let y = Math.floor((event.clientY - rect.top) * scaleY);

      // Account for flip transforms - CSS transform affects visual but not click coords
      if (settings.flipVertical) {
        x = canvas.width - 1 - x;
      }
      if (settings.flipHorizontal) {
        y = canvas.height - 1 - y;
      }

      const lineCount = buffer.getLineCount();
      const dims = buffer.getDimensions();

      // Canvas height now matches lineCount, so y directly maps to display line
      // y=0 is newest (top), y=lineCount-1 is oldest (bottom)
      const displayLineIdx = Math.min(Math.max(0, y), lineCount - 1);
      // Convert from display order (newest at top) to buffer order (oldest at 0)
      const bufferLineIdx = lineCount - 1 - displayLineIdx;
      const spatialX = Math.min(Math.max(0, x), dims.nSpatial - 1);

      if (bufferLineIdx >= 0 && bufferLineIdx < lineCount && spatialX >= 0) {
        const spectrum = buffer.getSpectrum(bufferLineIdx, spatialX);
        setSelectedSpectrum({
          wavelengths: wavelengths,
          intensities: spectrum,
          pixelX: spatialX,
          lineIndex: displayLineIdx, // Use display index for UI
          timestamp: Date.now(),
        });
      }
    },
    [wavelengths, settings.flipVertical, settings.flipHorizontal]
  );

  // Helper function to process image data and add to buffer
  const processImageData = useCallback((
    imgMsg: ImageMessage,
    msgAxisOrder: string,
    msgWavelengths?: number[] | null
  ) => {
    if (imgMsg.encoding !== "mono16") {
      const errMsg = `Unsupported encoding: ${imgMsg.encoding}`;
      console.warn("[HypercubePanel]", errMsg);
      setLastError(errMsg);
      return;
    }

    // Determine spatial and spectral dimensions based on axis_order
    // axis_order tells us how the IMAGE is organized (after any transpose in the node)
    let spatial: number;
    let spectral: number;
    let effectiveAxisOrder = msgAxisOrder;

    // Auto-detect axis order from wavelength count if set to "auto"
    if (msgAxisOrder === "auto") {
      // Use wavelengths from message or from state
      const wlCount = msgWavelengths?.length ?? wavelengths?.length ?? 0;

      if (wlCount > 0) {
        // Compare wavelength count to image dimensions
        if (wlCount === imgMsg.width) {
          // Wavelengths match width → width=spectral, height=spatial
          effectiveAxisOrder = "spatial,spectral";
          console.log("[HypercubePanel] Auto-detected axis order: spatial,spectral (WL count", wlCount, "matches width)");
        } else if (wlCount === imgMsg.height) {
          // Wavelengths match height → height=spectral, width=spatial
          effectiveAxisOrder = "spectral,spatial";
          console.log("[HypercubePanel] Auto-detected axis order: spectral,spatial (WL count", wlCount, "matches height)");
        } else {
          // No match - fall back to spatial,spectral and warn
          effectiveAxisOrder = "spatial,spectral";
          console.warn("[HypercubePanel] Could not auto-detect axis order: WL count", wlCount,
            "doesn't match width", imgMsg.width, "or height", imgMsg.height, "- defaulting to spatial,spectral");
        }
        setDetectedAxisOrder(effectiveAxisOrder);
      } else {
        // No wavelengths yet - use default and wait for wavelength data
        effectiveAxisOrder = "spatial,spectral";
        console.log("[HypercubePanel] Auto-detect: waiting for wavelength data, using default spatial,spectral");
      }
    }

    if (effectiveAxisOrder === "spectral,spatial") {
      // height=spectral, width=spatial (Lucid after transpose)
      spectral = imgMsg.height;
      spatial = imgMsg.width;
    } else {
      // "spatial,spectral" - height=spatial, width=spectral (XIMEA default)
      spatial = imgMsg.height;
      spectral = imgMsg.width;
    }

    console.log("[HypercubePanel] Image:", imgMsg.width, "x", imgMsg.height,
      "axis_order:", effectiveAxisOrder, "→ spatial:", spatial, "spectral:", spectral);

    // Initialize or reinitialize buffer if dimensions change
    if (
      !bufferRef.current ||
      bufferRef.current.getDimensions().nSpatial !== spatial ||
      bufferRef.current.getDimensions().nSpectral !== spectral
    ) {
      console.log("[HypercubePanel] Creating buffer:", spatial, "x", spectral);
      bufferRef.current = new WaterfallBuffer(
        settings.waterfallLines,
        spatial,
        spectral
      );
      setDimensions({ spatial, spectral });
    }

    // Update wavelengths if provided
    if (msgWavelengths && msgWavelengths.length > 0) {
      setWavelengths(msgWavelengths);
    } else if (!wavelengths) {
      // Generate default wavelengths based on spectral dimension
      const defaultWl = generateWavelengths(spectral, 426.07, 0.895, 0);
      setWavelengths(defaultWl);
    }

    // Parse image data - parseMono16Image handles transpose based on axis order
    const lineData = parseMono16Image(
      imgMsg.data,
      imgMsg.width,
      imgMsg.height,
      imgMsg.is_bigendian,
      effectiveAxisOrder
    );
    bufferRef.current.addLine(lineData);
    setMessageCount((c) => c + 1);
    setLastError(null);
  }, [settings.waterfallLines, wavelengths]);

  // Process incoming messages
  useLayoutEffect(() => {
    console.log("[HypercubePanel] Setting up onRender callback");

    context.onRender = (renderState, done) => {
      try {
        if (renderState.currentFrame) {
          for (const message of renderState.currentFrame) {
            try {
              // Handle HyperspectralImage message (combined image + wavelengths)
              if (settings.useHyperspectralMsg && message.topic === settings.hyperspectralTopic) {
                const hyperMsg = message.message as HyperspectralImageMessage;
                console.log("[HypercubePanel] Received HyperspectralImage, axis_order:", hyperMsg.axis_order);

                // Extract wavelengths from message
                let wl: number[] | null = null;
                if (hyperMsg.wavelengths_nm) {
                  wl = Array.isArray(hyperMsg.wavelengths_nm)
                    ? hyperMsg.wavelengths_nm
                    : Array.from(hyperMsg.wavelengths_nm);
                  console.log("[HypercubePanel] Got", wl.length, "wavelengths from message:",
                    wl[0]?.toFixed(1), "-", wl[wl.length-1]?.toFixed(1), "nm");
                }

                // Update axis order from message
                if (hyperMsg.axis_order) {
                  setAxisOrder(hyperMsg.axis_order);
                }

                // Process the embedded image
                processImageData(hyperMsg.image, hyperMsg.axis_order || "spatial,spectral", wl);

              } else if (!settings.useHyperspectralMsg) {
                // Handle separate wavelength topic
                if (message.topic === settings.wavelengthTopic) {
                  const wlMsg = message.message as any;
                  console.log("[HypercubePanel] Received wavelength message:", Object.keys(wlMsg));

                  let wl: number[] | null = null;
                  if (wlMsg.wavelengths) {
                    wl = Array.isArray(wlMsg.wavelengths) ? wlMsg.wavelengths : Array.from(wlMsg.wavelengths);
                  } else if (wlMsg.data) {
                    wl = Array.isArray(wlMsg.data) ? wlMsg.data : Array.from(wlMsg.data);
                  }

                  if (wl && wl.length > 0) {
                    console.log("[HypercubePanel] Got", wl.length, "wavelengths");
                    setWavelengths(wl);
                  }
                }

                // Handle separate image topic
                if (message.topic === settings.imageTopic) {
                  const imgMsg = message.message as ImageMessage;
                  // Use manual axis order setting for separate topics mode (ROS1 bags)
                  processImageData(imgMsg, settings.manualAxisOrder, null);
                }
              }
            } catch (msgErr) {
              console.error("[HypercubePanel] Error processing message:", msgErr);
              setLastError(String(msgErr));
            }
          }
        }

        // Request render
        if (renderRequestRef.current) {
          cancelAnimationFrame(renderRequestRef.current);
        }
        renderRequestRef.current = requestAnimationFrame(() => {
          renderWaterfall();
          if (selectedSpectrum) {
            renderSpectrum();
          }
        });
      } catch (err) {
        console.error("[HypercubePanel] Error in onRender:", err);
        setLastError(String(err));
      }

      done();
    };

    context.watch("currentFrame");
  }, [context, settings, axisOrder, processImageData, renderWaterfall, renderSpectrum, selectedSpectrum]);

  // Render spectrum when selection changes
  useEffect(() => {
    if (selectedSpectrum) {
      renderSpectrum();
    }
  }, [selectedSpectrum, renderSpectrum]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        backgroundColor: "#1a1a2e",
        color: "#eee",
        fontFamily: "monospace",
        fontSize: "12px",
        overflow: "hidden",
      }}
    >
      {/* Header - Status info only */}
      <div
        style={{
          padding: "4px 8px",
          borderBottom: "1px solid #333",
          display: "flex",
          gap: "12px",
          alignItems: "center",
          fontSize: "11px",
          color: "#888",
        }}
      >
        <span>
          {dimensions
            ? `${dimensions.spatial}x${dimensions.spectral} | ${messageCount} frames`
            : "Waiting for data..."}
        </span>
        <span>
          {wavelengths
            ? `L: ${wavelengths[0]?.toFixed(0)}-${wavelengths[wavelengths.length - 1]?.toFixed(0)}nm (${wavelengths.length})`
            : ""}
        </span>
        <span style={{ marginLeft: "auto" }}>
          axis: {settings.useHyperspectralMsg
            ? axisOrder
            : settings.manualAxisOrder === "auto"
              ? (detectedAxisOrder ? `auto→${detectedAxisOrder}` : "auto (waiting)")
              : settings.manualAxisOrder}
        </span>
      </div>

      {/* Main content area - column layout: waterfall on top, spectrum below */}
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          minHeight: 0,
        }}
      >
        {/* Waterfall canvas */}
        <div
          style={{
            flex: settings.showSpectrum && selectedSpectrum ? "1 1 70%" : 1,
            position: "relative",
            overflow: "hidden",
            minHeight: 0,
          }}
        >
          <canvas
            ref={canvasRef}
            onClick={handleCanvasClick}
            style={{
              width: "100%",
              height: "100%",
              imageRendering: "pixelated",
              cursor: "crosshair",
              transform: `${settings.flipVertical ? "scaleX(-1)" : ""} ${settings.flipHorizontal ? "scaleY(-1)" : ""}`.trim() || undefined,
            }}
          />
          {!dimensions && (
            <div
              style={{
                position: "absolute",
                top: "50%",
                left: "50%",
                transform: "translate(-50%, -50%)",
                color: "#666",
              }}
            >
              Waiting for hyperspectral data...
            </div>
          )}
          {dimensions && !selectedSpectrum && (
            <div
              style={{
                position: "absolute",
                bottom: "8px",
                left: "50%",
                transform: "translateX(-50%)",
                color: "#666",
                fontSize: "11px",
                backgroundColor: "rgba(0,0,0,0.5)",
                padding: "4px 8px",
                borderRadius: "4px",
              }}
            >
              Click on waterfall to view spectrum
            </div>
          )}
        </div>

        {/* Spectrum panel - below waterfall */}
        {settings.showSpectrum && selectedSpectrum && (
          <div
            style={{
              flex: "0 0 30%",
              borderTop: "1px solid #333",
              display: "flex",
              flexDirection: "column",
              minHeight: "120px",
              maxHeight: "200px",
            }}
          >
            <div
              style={{
                padding: "4px 8px",
                borderBottom: "1px solid #333",
                backgroundColor: "#252538",
                fontSize: "11px",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <span>
                Spectrum at pixel ({selectedSpectrum.pixelX}, line {selectedSpectrum.lineIndex})
              </span>
              <span style={{ color: "#666" }}>
                {settings.spectrumAutoScaleY ? "Auto Y" : `Y: 0-${settings.spectrumYMax}`}
              </span>
            </div>
            <canvas
              ref={spectrumCanvasRef}
              width={800}
              height={150}
              style={{
                flex: 1,
                width: "100%",
                height: "100%",
              }}
            />
          </div>
        )}
      </div>

      {/* Error display */}
      {lastError && (
        <div
          style={{
            padding: "4px 8px",
            backgroundColor: "#442222",
            color: "#ff6666",
            fontSize: "11px",
            borderTop: "1px solid #663333",
          }}
        >
          Error: {lastError}
        </div>
      )}

    </div>
  );
}
