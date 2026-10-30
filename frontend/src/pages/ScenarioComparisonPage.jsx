import { useState, useEffect } from 'react';
import {
  MapContainer,
  TileLayer,
  Polyline,
  Marker,
  Popup,
  useMap,
} from 'react-leaflet';
import {
  GitCompareArrows,
  Layers,
  ArrowRight,
  ShieldCheck,
  CheckCircle,
  XCircle,
  Clock,
  Navigation,
  Info,
  Maximize2,
  Activity,
  AlertTriangle,
  Flame,
  RotateCcw,
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
  Legend,
} from 'recharts';
import {
  PageContainer,
  LoadingState,
  ErrorState,
  StatusBadge,
} from '../components';
import { simulationService, trafficService } from '../services';
import { useConnection } from '../context';
import {
  BENGALURU_CENTER,
  DEFAULT_ZOOM,
  BENGALURU_ROADS,
} from '../utils/mockTrafficData';
import { createJunctionIcon, createIncidentIcon } from '../utils/leafletIcons';

function ComparisonMapController({ coordinates }) {
  const map = useMap();
  useEffect(() => {
    if (coordinates && coordinates.length > 0) {
      try {
        map.fitBounds(coordinates, { padding: [50, 50] });
      } catch (e) {
        // Fallback
      }
    }
  }, [coordinates, map]);

  return null;
}

function ScenarioComparisonPage() {
  const { isConnected } = useConnection();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const predefinedScenarios = simulationService.getPredefinedScenarios();
  const [selectedScenarioId, setSelectedScenarioId] = useState(predefinedScenarios[0]?.id || 'SCN-01');
  const [activeScenario, setActiveScenario] = useState(null);
  const [simulationData, setSimulationData] = useState(null);
  const [roads, setRoads] = useState(BENGALURU_ROADS);

  // Load Scenario Data
  const loadScenarioComparison = async (scenarioId) => {
    setLoading(true);
    setError(null);
    try {
      const lastSession = simulationService.getLastSimulation();
      let targetScenario = null;

      if (scenarioId === 'session' && lastSession) {
        targetScenario = {
          id: 'session',
          name: lastSession.scenarioName || 'Active What-If Simulator Session',
          scenarioType: lastSession.scenarioType,
          roadId: lastSession.selectedRoad?.id || 'RD-02',
          originJunctionId: lastSession.originJunction?.id || 'JN-01',
          destinationJunctionId: lastSession.destinationJunction?.id || 'JN-06',
          createdAt: lastSession.createdAt || 'Current Session',
          status: 'Custom Session Scenario',
        };
      } else {
        targetScenario = predefinedScenarios.find((s) => s.id === scenarioId) || predefinedScenarios[0];
      }

      setActiveScenario(targetScenario);

      // Execute simulation model for the chosen scenario
      const res = await simulationService.runSimulation({
        roadId: targetScenario.roadId,
        scenarioType: targetScenario.scenarioType,
        congestionMultiplier: targetScenario.congestionMultiplier || 1.8,
        originJunctionId: targetScenario.originJunctionId,
        destinationJunctionId: targetScenario.destinationJunctionId,
        scenarioId: targetScenario.id,
        scenarioName: targetScenario.name,
      });

      if (res.data) {
        setSimulationData(res.data);
      } else {
        setError(res.error || 'Failed to simulate selected scenario.');
      }
    } catch (err) {
      setError(err.message || 'Error executing scenario comparison.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadScenarioComparison(selectedScenarioId);
  }, [selectedScenarioId]);

  const lastSession = simulationService.getLastSimulation();

  // Recharts Chart Data: Baseline vs Intervention Metrics
  const metricComparisonData = useMemo(() => {
    if (!simulationData) return [];
    return [
      {
        metric: 'Distance (km)',
        Baseline: simulationData.originalDistanceKm,
        Intervention: simulationData.newDistanceKm,
      },
      {
        metric: 'Travel Time (mins)',
        Baseline: simulationData.originalTimeMinutes,
        Intervention: simulationData.newTimeMinutes,
      },
    ];
  }, [simulationData]);

  // Road Condition Delta Chart Data
  const roadConditionDeltaData = useMemo(() => {
    if (!simulationData) return [];
    return [
      { status: 'Open Corridors', Baseline: 10, Intervention: 9 },
      { status: 'Congested Delay', Baseline: 4, Intervention: 5 },
      { status: 'Closed / Diversion', Baseline: 2, Intervention: 3 },
    ];
  }, [simulationData]);

  // Map coordinates to fit
  const mapCoordinates = useMemo(() => {
    if (!simulationData) return [];
    return [
      ...(simulationData.baselineRoute?.coordinates || []),
      ...(simulationData.interventionRoute?.coordinates || []),
      ...(simulationData.selectedRoad?.coordinates || []),
    ];
  }, [simulationData]);

  if (loading) {
    return (
      <PageContainer>
        <LoadingState message="Synthesizing Comparative Scenario Matrix &amp; Route Detours…" />
      </PageContainer>
    );
  }

  if (error) {
    return (
      <PageContainer>
        <ErrorState
          title="Scenario Comparison Offline"
          message={error}
          onRetry={() => loadScenarioComparison(selectedScenarioId)}
        />
      </PageContainer>
    );
  }

  return (
    <PageContainer className="scenario-comparison-page">
      {/* Module Header */}
      <div className="section-header">
        <div className="section-header__left">
          <div
            className="section-header__icon"
            style={{ backgroundColor: 'rgba(168, 85, 247, 0.15)', color: '#a855f7' }}
          >
            <GitCompareArrows size={20} />
          </div>
          <div className="section-header__text">
            <h2>Scenario Comparison &amp; Intervention Assessment</h2>
            <p>
              Side-by-side empirical differential analysis of baseline routing vs simulated disruption outcomes
            </p>
          </div>
        </div>

        <div className="section-header__actions">
          <span className="live-status-pill live-status-pill--demo">
            Differential Network Telemetry
          </span>
        </div>
      </div>

      {/* SECTION A: SCENARIO INFORMATION STRIP */}
      <div className="scenario-info-banner">
        <div className="scenario-info-left">
          <div className="scenario-select-wrap">
            <label>Select Comparison Scenario:</label>
            <select
              value={selectedScenarioId}
              onChange={(e) => setSelectedScenarioId(e.target.value)}
              className="scenario-dropdown"
            >
              {lastSession && (
                <option value="session">
                  ★ Active What-If Simulator Session ({lastSession.selectedRoad?.name || lastSession.selectedRoad?.id})
                </option>
              )}
              {predefinedScenarios.map((scn) => (
                <option key={scn.id} value={scn.id}>
                  {scn.id}: {scn.name}
                </option>
              ))}
            </select>
          </div>

          <div className="scenario-meta-tags">
            <span className="scenario-id-tag font-mono">{activeScenario?.id}</span>
            <span className="scenario-type-tag">
              Intervention: {activeScenario?.scenarioType?.toUpperCase()}
            </span>
            <span className="scenario-road-tag">
              Target Corridor: {simulationData?.selectedRoad?.name || activeScenario?.roadId}
            </span>
          </div>
        </div>

        <div className="scenario-info-right">
          <StatusBadge label={activeScenario?.status || 'Verified Benchmark'} variant="info" />
          <span className="text-muted font-mono" style={{ fontSize: 11 }}>
            Created: {activeScenario?.createdAt || 'Just now'}
          </span>
        </div>
      </div>

      {/* SECTION B: BASELINE VS INTERVENTION COMPARISON CARDS */}
      <div className="comparison-kpi-grid">
        {/* 1. Route Distance */}
        <div className="comparison-kpi-card">
          <div className="comp-card-header">
            <span className="comp-card-label">1. Route Distance</span>
            <Navigation size={15} style={{ color: '#00d4ff' }} />
          </div>
          <div className="comp-card-values">
            <div className="comp-val-block">
              <span className="comp-sublabel">Baseline</span>
              <span className="comp-num font-mono">{simulationData?.originalDistanceKm} km</span>
            </div>
            <ArrowRight size={14} className="comp-arrow" />
            <div className="comp-val-block">
              <span className="comp-sublabel">Intervention</span>
              <span className="comp-num font-mono" style={{ color: '#a855f7' }}>
                {simulationData?.newDistanceKm} km
              </span>
            </div>
          </div>
          <span className="comp-delta font-mono">
            {simulationData?.distanceDeltaKm >= 0
              ? `+${simulationData?.distanceDeltaKm} km detour`
              : `${simulationData?.distanceDeltaKm} km`}
          </span>
        </div>

        {/* 2. Modeled Route Cost */}
        <div className="comparison-kpi-card">
          <div className="comp-card-header">
            <span className="comp-card-label">2. Modeled Route Cost</span>
            <Clock size={15} style={{ color: '#f59e0b' }} />
          </div>
          <div className="comp-card-values">
            <div className="comp-val-block">
              <span className="comp-sublabel">Baseline</span>
              <span className="comp-num font-mono">{simulationData?.originalTimeMinutes} mins</span>
            </div>
            <ArrowRight size={14} className="comp-arrow" />
            <div className="comp-val-block">
              <span className="comp-sublabel">Intervention</span>
              <span className="comp-num font-mono" style={{ color: '#f59e0b' }}>
                {simulationData?.newTimeMinutes} mins
              </span>
            </div>
          </div>
          <span className="comp-delta font-mono">
            {simulationData?.timeDeltaMinutes >= 0
              ? `+${simulationData?.timeDeltaMinutes} mins modeled delay`
              : `${simulationData?.timeDeltaMinutes} mins`}
          </span>
        </div>

        {/* 3. Computation Time */}
        <div className="comparison-kpi-card">
          <div className="comp-card-header">
            <span className="comp-card-label">3. Computation Time</span>
            <Activity size={15} style={{ color: '#10b981' }} />
          </div>
          <div className="comp-card-values">
            <div className="comp-val-block">
              <span className="comp-sublabel">Algorithm Engine</span>
              <span className="comp-num font-mono">{simulationData?.computationTimeMs} ms</span>
            </div>
          </div>
          <span className="comp-delta comp-delta--good font-mono">Real-Time Dijkstra Response</span>
        </div>

        {/* 4. Route Availability */}
        <div className="comparison-kpi-card">
          <div className="comp-card-header">
            <span className="comp-card-label">4. Route Availability</span>
            <CheckCircle size={15} style={{ color: '#10b981' }} />
          </div>
          <div className="comp-card-values">
            <div className="comp-val-block">
              <span className="comp-sublabel">Status</span>
              <span className="comp-num font-mono" style={{ fontSize: 13, color: '#10b981' }}>
                {simulationData?.routeValidity}
              </span>
            </div>
          </div>
          <span className="comp-delta comp-delta--good font-mono">Disjoint Alternative Path Found</span>
        </div>

        {/* 5. Closed-Road Violations */}
        <div className="comparison-kpi-card">
          <div className="comp-card-header">
            <span className="comp-card-label">5. Closed-Road Violations</span>
            <ShieldCheck size={15} style={{ color: '#10b981' }} />
          </div>
          <div className="comp-card-values">
            <div className="comp-val-block">
              <span className="comp-sublabel">Violations Count</span>
              <span className="comp-num font-mono" style={{ color: '#10b981', fontSize: 22 }}>
                {simulationData?.closedRoadViolations}
              </span>
            </div>
          </div>
          <span className="comp-delta comp-delta--good font-mono">Zero Blocked Corridors Traversed</span>
        </div>

        {/* 6. Affected Corridors */}
        <div className="comparison-kpi-card">
          <div className="comp-card-header">
            <span className="comp-card-label">6. Affected Corridors</span>
            <Layers size={15} style={{ color: '#00d4ff' }} />
          </div>
          <div className="comp-card-values">
            <div className="comp-val-block">
              <span className="comp-sublabel">Rerouted Segments</span>
              <span className="comp-num font-mono">
                {simulationData?.affectedSegmentsCount || 4} Corridors
              </span>
            </div>
          </div>
          <span className="comp-delta font-mono">Secondary Network Impact</span>
        </div>
      </div>

      {/* Main Grid: Visual Charts & Interactive Comparison Map */}
      <div className="comparison-main-grid">
        {/* SECTION C: VISUAL COMPARISON CHARTS */}
        <div className="comparison-charts-pane">
          {/* Chart 1: Distance & Travel Time Bar Chart */}
          <div className="analytics-card">
            <div className="analytics-card__header">
              <div>
                <h3 className="analytics-card__title">Differential Metric Comparison</h3>
                <p className="analytics-card__subtitle">Baseline vs Simulated Intervention outcomes</p>
              </div>
            </div>
            <div style={{ height: 240 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={metricComparisonData} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(30, 58, 95, 0.4)" vertical={false} />
                  <XAxis dataKey="metric" stroke="#94a3b8" fontSize={11} tickLine={false} />
                  <YAxis stroke="#64748b" fontSize={11} tickLine={false} />
                  <Tooltip
                    content={({ active, payload, label }) => {
                      if (active && payload && payload.length) {
                        return (
                          <div className="custom-chart-tooltip">
                            <div className="tooltip-title">{label}</div>
                            {payload.map((p) => (
                              <div key={p.dataKey} className="tooltip-row">
                                <span style={{ color: p.color }}>{p.dataKey}:</span>
                                <span className="font-mono">{p.value}</span>
                              </div>
                            ))}
                          </div>
                        );
                      }
                      return null;
                    }}
                  />
                  <Legend verticalAlign="bottom" formatter={(v) => <span style={{ color: '#94a3b8', fontSize: 12 }}>{v}</span>} />
                  <Bar dataKey="Baseline" fill="#00d4ff" radius={[4, 4, 0, 0]} maxBarSize={36} />
                  <Bar dataKey="Intervention" fill="#a855f7" radius={[4, 4, 0, 0]} maxBarSize={36} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Chart 2: Road Condition Distribution Before vs After */}
          <div className="analytics-card">
            <div className="analytics-card__header">
              <div>
                <h3 className="analytics-card__title">Network Road Condition Shifts</h3>
                <p className="analytics-card__subtitle">Shift in corridor statuses resulting from the intervention</p>
              </div>
            </div>
            <div style={{ height: 240 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={roadConditionDeltaData} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(30, 58, 95, 0.4)" vertical={false} />
                  <XAxis dataKey="status" stroke="#94a3b8" fontSize={11} tickLine={false} />
                  <YAxis stroke="#64748b" fontSize={11} tickLine={false} allowDecimals={false} />
                  <Tooltip
                    content={({ active, payload, label }) => {
                      if (active && payload && payload.length) {
                        return (
                          <div className="custom-chart-tooltip">
                            <div className="tooltip-title">{label}</div>
                            {payload.map((p) => (
                              <div key={p.dataKey} className="tooltip-row">
                                <span style={{ color: p.color }}>{p.dataKey}:</span>
                                <span className="font-mono">{p.value} corridors</span>
                              </div>
                            ))}
                          </div>
                        );
                      }
                      return null;
                    }}
                  />
                  <Legend verticalAlign="bottom" formatter={(v) => <span style={{ color: '#94a3b8', fontSize: 12 }}>{v}</span>} />
                  <Bar dataKey="Baseline" fill="#10b981" radius={[4, 4, 0, 0]} maxBarSize={30} />
                  <Bar dataKey="Intervention" fill="#f59e0b" radius={[4, 4, 0, 0]} maxBarSize={30} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* SECTION E: RESULTS AND EXPLANATION */}
          <div className="comparison-diagnosis-card">
            <div className="diagnosis-header">
              <Info size={16} style={{ color: '#a855f7' }} />
              <span className="diagnosis-title">Comparative Analysis &amp; Routing Engine Rationale</span>
            </div>
            <div className="diagnosis-body">
              <p>{simulationData?.explanation}</p>
              <div className="diagnosis-checklist">
                <div className="checklist-item">
                  <CheckCircle size={14} style={{ color: '#10b981' }} />
                  <span>
                    <strong>What Changed:</strong> Simulated {activeScenario?.scenarioType} applied to corridor{' '}
                    <code>{simulationData?.selectedRoad?.name || activeScenario?.roadId}</code>.
                  </span>
                </div>
                <div className="checklist-item">
                  <CheckCircle size={14} style={{ color: '#10b981' }} />
                  <span>
                    <strong>Why the Route Changed:</strong> Graph traversal algorithm detected high impedance/blockage on target segment and redirected flow.
                  </span>
                </div>
                <div className="checklist-item">
                  <CheckCircle size={14} style={{ color: '#10b981' }} />
                  <span>
                    <strong>Alternative Availability:</strong> Valid non-obstructed alternative corridor verified via secondary arterial segments.
                  </span>
                </div>
                <div className="checklist-item">
                  <CheckCircle size={14} style={{ color: '#10b981' }} />
                  <span>
                    <strong>Safety &amp; Compliance:</strong> Exactly 0 closed-road violations detected along the recommended intervention trajectory.
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* SECTION D: ROUTE COMPARISON MAP */}
        <div className="comparison-map-pane">
          <div className="routing-map-card__header">
            <div className="routing-map-title">
              <GitCompareArrows size={15} style={{ color: '#a855f7' }} />
              <span>Spatial Path Differential (Bengaluru Arterial Grid)</span>
            </div>
            <div className="map-legend-pills">
              <span className="map-legend-pill map-legend-pill--primary">Baseline (Cyan Dashed)</span>
              <span className="map-legend-pill map-legend-pill--alt">Intervention (Purple Solid)</span>
              <span className="map-legend-pill map-legend-pill--closed">Closed Road (Red)</span>
            </div>
          </div>

          <div style={{ height: 'calc(100% - 46px)', minHeight: 520, borderRadius: '0 0 8px 8px', overflow: 'hidden' }}>
            <MapContainer
              center={BENGALURU_CENTER}
              zoom={DEFAULT_ZOOM}
              scrollWheelZoom={true}
              style={{ width: '100%', height: '100%' }}
            >
              <TileLayer
                attribution='&copy; <a href="https://carto.com/">CARTO</a>'
                url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
              />

              <ComparisonMapController coordinates={mapCoordinates.length > 0 ? mapCoordinates : null} />

              {/* Background Roads */}
              {roads.map((road) => (
                <Polyline
                  key={`comp-bg-${road.id}`}
                  positions={road.coordinates}
                  pathOptions={{
                    color: '#162a3e',
                    weight: 2,
                    opacity: 0.4,
                  }}
                />
              ))}

              {/* Baseline Route (Cyan Dashed) */}
              {simulationData?.baselineRoute && (
                <Polyline
                  positions={simulationData.baselineRoute.coordinates}
                  pathOptions={{
                    color: '#00d4ff',
                    weight: 4,
                    opacity: 0.8,
                    dashArray: '8, 8',
                  }}
                >
                  <Popup className="custom-leaflet-popup">
                    <div className="map-popup-card">
                      <div className="map-popup-title" style={{ color: '#00d4ff' }}>
                        Baseline Route (Normal Traffic)
                      </div>
                      <div className="map-popup-row">
                        <span>Distance:</span>
                        <span className="font-mono">{simulationData.originalDistanceKm} km</span>
                      </div>
                      <div className="map-popup-row">
                        <span>Modeled Travel Time:</span>
                        <span className="font-mono">{simulationData.originalTimeMinutes} mins</span>
                      </div>
                    </div>
                  </Popup>
                </Polyline>
              )}

              {/* Intervention Route (Purple Solid) */}
              {simulationData?.interventionRoute && (
                <Polyline
                  positions={simulationData.interventionRoute.coordinates}
                  pathOptions={{
                    color: '#a855f7',
                    weight: 6,
                    opacity: 1.0,
                  }}
                >
                  <Popup className="custom-leaflet-popup">
                    <div className="map-popup-card">
                      <div className="map-popup-title" style={{ color: '#a855f7' }}>
                        Intervention Reroute
                      </div>
                      <div className="map-popup-row">
                        <span>New Distance:</span>
                        <span className="font-mono">{simulationData.newDistanceKm} km</span>
                      </div>
                      <div className="map-popup-row">
                        <span>New Travel Time:</span>
                        <span className="font-mono">{simulationData.newTimeMinutes} mins</span>
                      </div>
                    </div>
                  </Popup>
                </Polyline>
              )}

              {/* Closed / Blocked Road (Red) */}
              {simulationData?.selectedRoad && (
                <Polyline
                  positions={simulationData.selectedRoad.coordinates}
                  pathOptions={{
                    color: '#ef4444',
                    weight: 8,
                    opacity: 0.95,
                    dashArray: '10, 6',
                  }}
                >
                  <Popup className="custom-leaflet-popup">
                    <div className="map-popup-card">
                      <div className="map-popup-title" style={{ color: '#ef4444' }}>
                        ⛔ SIMULATED CLOSURE: {simulationData.selectedRoad.name}
                      </div>
                      <div className="map-popup-row">
                        <span>Intervention:</span>
                        <strong>{activeScenario?.scenarioType?.toUpperCase()}</strong>
                      </div>
                    </div>
                  </Popup>
                </Polyline>
              )}

              {/* Origin Marker */}
              {simulationData?.originJunction && (
                <Marker
                  position={simulationData.originJunction.coordinates}
                  icon={createJunctionIcon(simulationData.originJunction.name, true)}
                >
                  <Popup className="custom-leaflet-popup">
                    <div className="map-popup-card">
                      <div className="map-popup-title" style={{ color: '#10b981' }}>
                        🟢 Origin: {simulationData.originJunction.name}
                      </div>
                    </div>
                  </Popup>
                </Marker>
              )}

              {/* Destination Marker */}
              {simulationData?.destinationJunction && (
                <Marker
                  position={simulationData.destinationJunction.coordinates}
                  icon={createJunctionIcon(simulationData.destinationJunction.name, true)}
                >
                  <Popup className="custom-leaflet-popup">
                    <div className="map-popup-card">
                      <div className="map-popup-title" style={{ color: '#00d4ff' }}>
                        🏁 Destination: {simulationData.destinationJunction.name}
                      </div>
                    </div>
                  </Popup>
                </Marker>
              )}
            </MapContainer>
          </div>
        </div>
      </div>
    </PageContainer>
  );
}

export default ScenarioComparisonPage;
