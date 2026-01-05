import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { PanelExtensionContext } from "@foxglove/extension";

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

  // State for axis order from HyperspectralImage message
  const [axisOrder, setAxisOrder] = useState<string>("spatial,spectral");

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

      const x = Math.floor((event.clientX - rect.left) * scaleX);
      const y = Math.floor((event.clientY - rect.top) * scaleY);

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
    [wavelengths]
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

    if (msgAxisOrder === "spectral,spatial") {
      // height=spectral, width=spatial (Lucid after transpose)
      spectral = imgMsg.height;
      spatial = imgMsg.width;
    } else {
      // "spatial,spectral" - height=spatial, width=spectral (XIMEA default)
      spatial = imgMsg.height;
      spectral = imgMsg.width;
    }

    console.log("[HypercubePanel] Image:", imgMsg.width, "x", imgMsg.height,
      "axis_order:", msgAxisOrder, "→ spatial:", spatial, "spectral:", spectral);

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

    // Parse image data - parseMono16Image handles the transpose internally
    // based on the assumption that height=spectral, width=spatial after node transpose
    const lineData = parseMono16Image(
      imgMsg.data,
      imgMsg.width,
      imgMsg.height,
      imgMsg.is_bigendian
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
                  // Use current axis order state for separate image messages
                  processImageData(imgMsg, axisOrder, null);
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

  // Settings panel
  const updateSetting = <K extends keyof PanelSettings>(
    key: K,
    value: PanelSettings[K]
  ) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

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
      {/* Header / Settings */}
      <div
        style={{
          padding: "8px",
          borderBottom: "1px solid #333",
          display: "flex",
          flexWrap: "wrap",
          gap: "8px",
          alignItems: "center",
        }}
      >
        {/* Topic mode toggle */}
        <label style={{ display: "flex", alignItems: "center", gap: "4px" }}>
          <input
            type="checkbox"
            checked={settings.useHyperspectralMsg}
            onChange={(e) => updateSetting("useHyperspectralMsg", e.target.checked)}
          />
          Combined msg
        </label>

        {settings.useHyperspectralMsg ? (
          /* Combined HyperspectralImage topic */
          <label>
            Topic:
            <input
              type="text"
              value={settings.hyperspectralTopic}
              onChange={(e) => updateSetting("hyperspectralTopic", e.target.value)}
              style={{
                marginLeft: "4px",
                padding: "2px 4px",
                backgroundColor: "#2a2a3e",
                border: "1px solid #444",
                color: "#eee",
                width: "200px",
              }}
            />
          </label>
        ) : (
          /* Separate Image and Wavelength topics */
          <>
            <label>
              Image:
              <input
                type="text"
                value={settings.imageTopic}
                onChange={(e) => updateSetting("imageTopic", e.target.value)}
                style={{
                  marginLeft: "4px",
                  padding: "2px 4px",
                  backgroundColor: "#2a2a3e",
                  border: "1px solid #444",
                  color: "#eee",
                  width: "140px",
                }}
              />
            </label>

            <label>
              WL:
              <input
                type="text"
                value={settings.wavelengthTopic}
                onChange={(e) => updateSetting("wavelengthTopic", e.target.value)}
                style={{
                  marginLeft: "4px",
                  padding: "2px 4px",
                  backgroundColor: "#2a2a3e",
                  border: "1px solid #444",
                  color: "#eee",
                  width: "140px",
                }}
              />
            </label>
          </>
        )}

        <label>
          RGB:
          <select
            value={settings.rgbPreset}
            onChange={(e) => updateSetting("rgbPreset", e.target.value)}
            style={{
              marginLeft: "4px",
              padding: "2px",
              backgroundColor: "#2a2a3e",
              border: "1px solid #444",
              color: "#eee",
            }}
          >
            {RGB_PRESETS.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name} ({p.red}/{p.green}/{p.blue}nm)
              </option>
            ))}
          </select>
        </label>

        {settings.rgbPreset === "custom" && (
          <>
            <label>
              R:
              <input
                type="number"
                value={settings.customRedNm}
                onChange={(e) =>
                  updateSetting("customRedNm", parseFloat(e.target.value))
                }
                style={{
                  marginLeft: "2px",
                  width: "50px",
                  padding: "2px",
                  backgroundColor: "#2a2a3e",
                  border: "1px solid #444",
                  color: "#ff6666",
                }}
              />
            </label>
            <label>
              G:
              <input
                type="number"
                value={settings.customGreenNm}
                onChange={(e) =>
                  updateSetting("customGreenNm", parseFloat(e.target.value))
                }
                style={{
                  marginLeft: "2px",
                  width: "50px",
                  padding: "2px",
                  backgroundColor: "#2a2a3e",
                  border: "1px solid #444",
                  color: "#66ff66",
                }}
              />
            </label>
            <label>
              B:
              <input
                type="number"
                value={settings.customBlueNm}
                onChange={(e) =>
                  updateSetting("customBlueNm", parseFloat(e.target.value))
                }
                style={{
                  marginLeft: "2px",
                  width: "50px",
                  padding: "2px",
                  backgroundColor: "#2a2a3e",
                  border: "1px solid #444",
                  color: "#6666ff",
                }}
              />
            </label>
          </>
        )}

        <label>
          Lines:
          <input
            type="number"
            value={settings.waterfallLines}
            onChange={(e) =>
              updateSetting("waterfallLines", parseInt(e.target.value, 10))
            }
            min={32}
            max={1024}
            style={{
              marginLeft: "4px",
              width: "60px",
              padding: "2px",
              backgroundColor: "#2a2a3e",
              border: "1px solid #444",
              color: "#eee",
            }}
          />
        </label>

        <span style={{ marginLeft: "auto", color: "#888" }}>
          {dimensions
            ? `${dimensions.spatial}x${dimensions.spectral} | ${messageCount} frames`
            : "Waiting for data..."}
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
                gap: "12px",
              }}
            >
              <span>
                Spectrum at pixel ({selectedSpectrum.pixelX}, line {selectedSpectrum.lineIndex})
              </span>
              <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
                <label style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                  <input
                    type="checkbox"
                    checked={settings.spectrumAutoScaleY}
                    onChange={(e) => updateSetting("spectrumAutoScaleY", e.target.checked)}
                  />
                  Auto Y
                </label>
                {!settings.spectrumAutoScaleY && (
                  <label style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                    Y Max:
                    <input
                      type="number"
                      value={settings.spectrumYMax}
                      onChange={(e) => updateSetting("spectrumYMax", parseInt(e.target.value, 10) || 4095)}
                      min={1}
                      max={65535}
                      style={{
                        width: "60px",
                        padding: "2px 4px",
                        backgroundColor: "#2a2a3e",
                        border: "1px solid #444",
                        color: "#eee",
                        fontSize: "11px",
                      }}
                    />
                  </label>
                )}
              </div>
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

      {/* Footer / Status */}
      <div
        style={{
          padding: "4px 8px",
          borderTop: "1px solid #333",
          fontSize: "10px",
          color: "#666",
          display: "flex",
          justifyContent: "space-between",
          gap: "12px",
        }}
      >
        <span>
          {wavelengths
            ? `WL: ${wavelengths[0]?.toFixed(0)}-${wavelengths[wavelengths.length - 1]?.toFixed(0)}nm (${wavelengths.length})`
            : "Wavelengths: waiting..."}
        </span>
        <span style={{ color: "#888" }}>
          axis: {axisOrder}
        </span>
        <label style={{ marginLeft: "auto" }}>
          <input
            type="checkbox"
            checked={settings.showSpectrum}
            onChange={(e) => updateSetting("showSpectrum", e.target.checked)}
          />
          Show Spectrum Panel
        </label>
      </div>
    </div>
  );
}
