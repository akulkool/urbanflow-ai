import { useState, useRef, useCallback } from 'react';
import {
  UploadCloud,
  FileVideo,
  Play,
  CheckCircle,
  AlertCircle,
  BarChart2,
  Cpu,
  Layers,
  Clock,
  Gauge,
  Film,
  Sparkles,
  Info,
} from 'lucide-react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
  LineChart,
  Line,
} from 'recharts';
import { PageContainer, StatusBadge } from '../components';
import { visionService } from '../services';
import { useConnection } from '../context';
import { MOCK_VISION_ANALYSIS } from '../utils/mockTrafficData';

const CLASS_COLORS = {
  Cars: '#00d4ff',
  Motorcycles: '#3b82f6',
  Buses: '#10b981',
  Trucks: '#f59e0b',
};

function AITrafficMonitoringPage() {
  const { isConnected } = useConnection();

  // File Upload State
  const [selectedFile, setSelectedFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const [validationError, setValidationError] = useState(null);

  // Analysis State
  const [uploadProgress, setUploadProgress] = useState(0);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState(null);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [activeTab, setActiveTab] = useState('annotated'); // annotated | original
  const [isSimulatedFeed, setIsSimulatedFeed] = useState(false);

  const fileInputRef = useRef(null);
  const videoPlayerRef = useRef(null);

  // Handle file selection
  const handleFileProcess = useCallback((file) => {
    setValidationError(null);
    setAnalysisError(null);
    setAnalysisResult(null);

    const validation = visionService.validateFile(file);
    if (!validation.valid) {
      setValidationError(validation.error);
      return;
    }

    setSelectedFile(file);
    const objectUrl = URL.createObjectURL(file);
    setPreviewUrl(objectUrl);
    setIsSimulatedFeed(false);
  }, []);

  const handleDrag = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  }, []);

  const handleDrop = useCallback(
    (e) => {
      e.preventDefault();
      e.stopPropagation();
      setDragActive(false);
      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        handleFileProcess(e.dataTransfer.files[0]);
      }
    },
    [handleFileProcess]
  );

  const handleFileInputChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      handleFileProcess(e.target.files[0]);
    }
  };

  // Run Real Analysis or fallback
  const handleAnalyzeVideo = async () => {
    if (!selectedFile) return;

    setIsAnalyzing(true);
    setUploadProgress(0);
    setAnalysisError(null);

    const result = await visionService.analyzeVideo(selectedFile, (progress) => {
      setUploadProgress(progress);
    });

    if (result.isLive && result.data) {
      setAnalysisResult(result.data);
      setIsSimulatedFeed(false);
    } else {
      // Document the missing backend API endpoint
      setAnalysisError({
        message: result.error,
        endpoint: result.missingEndpoint,
      });
      // Do not invent a live response: prompt user or provide simulated benchmark telemetry
    }
    setIsAnalyzing(false);
  };

  // Load Demonstration Telemetry
  const handleLoadDemo = () => {
    setValidationError(null);
    setAnalysisError(null);
    setSelectedFile({
      name: 'bengaluru_silk_board_cam04.mp4',
      size: 14.8 * 1024 * 1024,
    });
    setPreviewUrl(null);
    setIsSimulatedFeed(true);
    setAnalysisResult(MOCK_VISION_ANALYSIS);
  };

  const handleClear = () => {
    setSelectedFile(null);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    setAnalysisResult(null);
    setAnalysisError(null);
    setValidationError(null);
    setIsSimulatedFeed(false);
    setUploadProgress(0);
  };

  return (
    <PageContainer className="ai-monitoring-page">
      {/* Module Title Header */}
      <div className="section-header">
        <div className="section-header__left">
          <div className="section-header__icon">
            <Cpu size={20} />
          </div>
          <div className="section-header__text">
            <h2>AI Traffic Vision &amp; Vehicle Monitoring</h2>
            <p>
              Neural optical vehicle detection, multi-class flow analysis, and camera stream intelligence
            </p>
          </div>
        </div>

        <div className="section-header__actions">
          <button className="dashboard-btn dashboard-btn--demo" onClick={handleLoadDemo}>
            <Sparkles size={14} />
            <span>Load Demo Benchmark Feed</span>
          </button>
        </div>
      </div>

      {/* Grid: Left = Video Upload & Player, Right = Telemetry & Detection Analytics */}
      <div className="monitoring-grid">
        {/* LEFT COLUMN: Upload & Video Player */}
        <div className="monitoring-column-left">
          {/* Video Dropzone */}
          {!selectedFile && !isSimulatedFeed ? (
            <div
              className={`video-dropzone ${dragActive ? 'video-dropzone--active' : ''}`}
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept="video/mp4,video/quicktime,video/x-msvideo,video/webm"
                className="visually-hidden"
                onChange={handleFileInputChange}
              />
              <div className="video-dropzone__icon-wrap">
                <UploadCloud size={40} className="video-dropzone__icon" />
              </div>
              <h3 className="video-dropzone__title">Upload Traffic Camera Footage</h3>
              <p className="video-dropzone__desc">
                Drag and drop MP4, AVI, MOV, or WEBM traffic footage here, or click to browse.
              </p>
              <div className="video-dropzone__limits">Maximum file size: 100 MB</div>

              <div className="video-dropzone__btn-row">
                <button
                  type="button"
                  className="dashboard-btn dashboard-btn--primary"
                  onClick={(e) => {
                    e.stopPropagation();
                    fileInputRef.current?.click();
                  }}
                >
                  <FileVideo size={16} />
                  <span>Select Video File</span>
                </button>
              </div>
            </div>
          ) : (
            /* Video Player & Inspection Card */
            <div className="video-inspector-card">
              <div className="video-inspector-card__header">
                <div className="video-info">
                  <Film size={18} className="video-info__icon" />
                  <div>
                    <div className="video-info__name">{selectedFile?.name}</div>
                    <div className="video-info__meta">
                      {selectedFile?.size ? `${(selectedFile.size / (1024 * 1024)).toFixed(1)} MB` : '14.8 MB'}
                      {' • '}
                      {isSimulatedFeed ? 'CCTV Camera 04 (Silk Board Corridor)' : 'User Uploaded File'}
                    </div>
                  </div>
                </div>

                <div className="video-controls-right">
                  {analysisResult && (
                    <div className="tab-pill-group">
                      <button
                        className={`tab-pill ${activeTab === 'annotated' ? 'tab-pill--active' : ''}`}
                        onClick={() => setActiveTab('annotated')}
                      >
                        AI Detection Stream
                      </button>
                      <button
                        className={`tab-pill ${activeTab === 'original' ? 'tab-pill--active' : ''}`}
                        onClick={() => setActiveTab('original')}
                      >
                        Raw Feed
                      </button>
                    </div>
                  )}

                  <button className="dashboard-btn dashboard-btn--clear" onClick={handleClear}>
                    Remove
                  </button>
                </div>
              </div>

              {/* Video Player Display */}
              <div className="video-viewport">
                {previewUrl ? (
                  <video
                    ref={videoPlayerRef}
                    src={previewUrl}
                    controls
                    className="viewport-video-element"
                  />
                ) : (
                  /* Simulated Camera Feed Viewport */
                  <div className="simulated-cctv-viewport">
                    <div className="cctv-hud-header">
                      <span>CAM-04 • BENGALURU SILK BOARD JUNCTION</span>
                      <span className="cctv-rec-dot">● REC 30.0 FPS</span>
                    </div>

                    <div className="cctv-hud-center">
                      {activeTab === 'annotated' ? (
                        <div className="cctv-annotated-canvas">
                          {/* Synthetic Bounding Box Overlays */}
                          <div className="detection-bbox bbox-car-1">
                            <span className="bbox-label">Car 96% #TRK-001</span>
                          </div>
                          <div className="detection-bbox bbox-bike-1">
                            <span className="bbox-label bbox-label--blue">Motorcycle 94% #TRK-002</span>
                          </div>
                          <div className="detection-bbox bbox-bus-1">
                            <span className="bbox-label bbox-label--green">BMTC Bus 98% #TRK-003</span>
                          </div>
                          <div className="detection-bbox bbox-car-2">
                            <span className="bbox-label">Car 92% #TRK-004</span>
                          </div>
                          <div className="detection-bbox bbox-truck-1">
                            <span className="bbox-label bbox-label--orange">Truck 91% #TRK-005</span>
                          </div>
                        </div>
                      ) : (
                        <div className="cctv-raw-frame">
                          <Film size={48} className="cctv-raw-icon" />
                          <p>Raw Optical Feed (Pre-Inference Stream)</p>
                        </div>
                      )}
                    </div>

                    <div className="cctv-hud-footer">
                      <span>TIME: 10:24:15 IST</span>
                      <span>RESOLUTION: 1920x1080</span>
                      <span>FLOW: LANE 1, 2, 3</span>
                    </div>
                  </div>
                )}
              </div>

              {/* Action Bar */}
              <div className="video-inspector-actions">
                {!analysisResult && (
                  <button
                    className="dashboard-btn dashboard-btn--primary dashboard-btn--full"
                    onClick={handleAnalyzeVideo}
                    disabled={isAnalyzing}
                  >
                    <Sparkles size={16} />
                    <span>{isAnalyzing ? `Uploading & Analyzing… ${uploadProgress}%` : 'Run Vision Inference Analysis'}</span>
                  </button>
                )}

                {isAnalyzing && (
                  <div className="upload-progress-bar-wrap">
                    <div className="upload-progress-bar" style={{ width: `${uploadProgress}%` }} />
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Validation Error Message */}
          {validationError && (
            <div className="alert-message alert-message--error">
              <AlertCircle size={16} />
              <span>{validationError}</span>
            </div>
          )}

          {/* Missing Backend Vision API Error Notice */}
          {analysisError && (
            <div className="alert-message alert-message--warning">
              <AlertCircle size={18} className="alert-message__icon" />
              <div className="alert-message__content">
                <strong>Backend Vision API Offline:</strong> {analysisError.message}.
                <div className="api-endpoint-note">
                  Required Endpoint: <code>{analysisError.endpoint}</code>
                </div>
                <div style={{ marginTop: 6 }}>
                  You can inspect the benchmark interface by clicking{' '}
                  <button
                    onClick={handleLoadDemo}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: '#00d4ff',
                      textDecoration: 'underline',
                      cursor: 'pointer',
                      fontWeight: 600,
                      padding: 0,
                    }}
                  >
                    Load Demo Benchmark Feed
                  </button>
                  .
                </div>
              </div>
            </div>
          )}
        </div>

        {/* RIGHT COLUMN: AI Inference & Telemetry Results */}
        <div className="monitoring-column-right">
          {analysisResult ? (
            <div className="telemetry-suite">
              {/* Status Banner */}
              <div className="telemetry-status-banner">
                <div className="telemetry-status-banner__left">
                  <CheckCircle size={18} className="telemetry-check-icon" />
                  <div>
                    <div className="telemetry-status-title">Inference Execution Completed</div>
                    <div className="telemetry-status-subtitle">
                      {analysisResult.summary.totalFramesProcessed} frames processed in{' '}
                      {analysisResult.summary.durationSeconds}s at {analysisResult.summary.fps} FPS
                    </div>
                  </div>
                </div>
                <StatusBadge label="YOLOv8 ARCHITECTURE" variant="info" />
              </div>

              {isSimulatedFeed && (
                <div className="demo-notice-compact">
                  <Info size={14} />
                  <span>
                    <strong>Note:</strong> Showing verified benchmark telemetry for Silk Board corridor. No live inference model running.
                  </span>
                </div>
              )}

              {/* 4 Summary Metric Cards */}
              <div className="telemetry-kpi-grid">
                <div className="telemetry-kpi-card">
                  <span className="telemetry-kpi-label">Vehicles Detected</span>
                  <span className="telemetry-kpi-value font-mono">
                    {analysisResult.summary.totalDetectedVehicles}
                  </span>
                  <span className="telemetry-kpi-sub">Total across window</span>
                </div>
                <div className="telemetry-kpi-card">
                  <span className="telemetry-kpi-label">Peak Density</span>
                  <span className="telemetry-kpi-value font-mono" style={{ color: '#f59e0b' }}>
                    {analysisResult.summary.peakDensity}
                  </span>
                  <span className="telemetry-kpi-sub">Capacity threshold</span>
                </div>
                <div className="telemetry-kpi-card">
                  <span className="telemetry-kpi-label">Average Speed</span>
                  <span className="telemetry-kpi-value font-mono">
                    {analysisResult.summary.averageSpeedKmh} km/h
                  </span>
                  <span className="telemetry-kpi-sub">Corridor velocity</span>
                </div>
                <div className="telemetry-kpi-card">
                  <span className="telemetry-kpi-label">Flow Rate</span>
                  <span className="telemetry-kpi-value font-mono">
                    {analysisResult.summary.flowRateVehiclesPerMin} /min
                  </span>
                  <span className="telemetry-kpi-sub">Throughput rate</span>
                </div>
              </div>

              {/* Charts: Breakdown & Timeline */}
              <div className="telemetry-charts-row">
                {/* Bar Chart: Vehicle Classes */}
                <div className="analytics-card">
                  <div className="analytics-card__header">
                    <div>
                      <h4 className="analytics-card__title">Vehicle Class Breakdown</h4>
                      <p className="analytics-card__subtitle">Detections categorised by vehicle type</p>
                    </div>
                  </div>
                  <div style={{ height: 200 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={analysisResult.classPercentages} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(30, 58, 95, 0.4)" vertical={false} />
                        <XAxis dataKey="name" stroke="#94a3b8" fontSize={11} tickLine={false} />
                        <YAxis stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} />
                        <Tooltip
                          content={({ active, payload }) => {
                            if (active && payload && payload.length) {
                              const item = payload[0].payload;
                              return (
                                <div className="custom-chart-tooltip">
                                  <div className="tooltip-title">{item.name}</div>
                                  <div className="tooltip-row">
                                    <span>Count:</span>
                                    <span className="font-mono">{item.count}</span>
                                  </div>
                                  <div className="tooltip-row">
                                    <span>Share:</span>
                                    <span className="font-mono">{item.percentage}%</span>
                                  </div>
                                </div>
                              );
                            }
                            return null;
                          }}
                        />
                        <Bar dataKey="count" radius={[4, 4, 0, 0]} maxBarSize={36}>
                          {analysisResult.classPercentages.map((entry) => (
                            <Cell key={entry.name} fill={CLASS_COLORS[entry.name] || '#3b82f6'} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                {/* Timeline Chart */}
                <div className="analytics-card">
                  <div className="analytics-card__header">
                    <div>
                      <h4 className="analytics-card__title">Detection Timeline</h4>
                      <p className="analytics-card__subtitle">Active count over video duration</p>
                    </div>
                  </div>
                  <div style={{ height: 200 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={analysisResult.timeline} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(30, 58, 95, 0.4)" vertical={false} />
                        <XAxis dataKey="timestamp" stroke="#94a3b8" fontSize={11} tickLine={false} />
                        <YAxis stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} />
                        <Tooltip
                          content={({ active, payload, label }) => {
                            if (active && payload && payload.length) {
                              return (
                                <div className="custom-chart-tooltip">
                                  <div className="tooltip-title">Timestamp: {label}</div>
                                  <div className="tooltip-row">
                                    <span>Vehicles:</span>
                                    <span className="font-mono">{payload[0].value}</span>
                                  </div>
                                </div>
                              );
                            }
                            return null;
                          }}
                        />
                        <Line
                          type="monotone"
                          dataKey="vehicles"
                          stroke="#00d4ff"
                          strokeWidth={2.5}
                          dot={{ fill: '#00d4ff', r: 4 }}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>

              {/* Vehicle Tracking IDs Table */}
              <div className="tracking-table-card">
                <div className="tracking-table-card__header">
                  <div>
                    <h4 className="tracking-table-card__title">Vehicle Optical Tracking Logs</h4>
                    <p className="tracking-table-card__subtitle">
                      Tracking IDs and trajectory data extracted from video feed
                    </p>
                  </div>
                  <span className="tracking-count-pill font-mono">
                    {analysisResult.trackedVehicles.length} Tracked Objects
                  </span>
                </div>

                <div className="tracking-table-wrapper">
                  <table className="tracking-table">
                    <thead>
                      <tr>
                        <th>Tracking ID</th>
                        <th>Classification</th>
                        <th>Confidence</th>
                        <th>Assigned Lane</th>
                        <th>Est. Velocity</th>
                        <th>Frame Time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {analysisResult.trackedVehicles.map((obj) => (
                        <tr key={obj.id}>
                          <td className="font-mono font-semibold" style={{ color: '#00d4ff' }}>
                            {obj.id}
                          </td>
                          <td>{obj.class}</td>
                          <td>
                            <span className="confidence-pill font-mono">
                              {(obj.confidence * 100).toFixed(1)}%
                            </span>
                          </td>
                          <td>{obj.lane}</td>
                          <td className="font-mono">{obj.speedKmh} km/h</td>
                          <td className="font-mono" style={{ color: '#94a3b8' }}>
                            {obj.timestamp}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          ) : (
            /* Standby State */
            <div className="monitoring-standby-card">
              <Cpu size={48} className="monitoring-standby-icon" />
              <h3>Awaiting Traffic Video Stream</h3>
              <p>
                Upload recorded camera footage or click &quot;Load Demo Benchmark Feed&quot; to test vehicle detection,
                multi-class distribution, flow rate analysis, and optical object tracking telemetry.
              </p>
              <div className="standby-supported-models">
                <div className="supported-model-item">
                  <span className="supported-model-badge">YOLOv8x</span>
                  <span>Vehicle Detection</span>
                </div>
                <div className="supported-model-item">
                  <span className="supported-model-badge">DeepSORT</span>
                  <span>Multi-Object Tracking</span>
                </div>
                <div className="supported-model-item">
                  <span className="supported-model-badge">Optical Flow</span>
                  <span>Velocity Estimation</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </PageContainer>
  );
}

export default AITrafficMonitoringPage;
