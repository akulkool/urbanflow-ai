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
  FlaskConical,
  Play,
  RotateCcw,
  AlertTriangle,
  Flame,
  Activity,
  ArrowRight,
  CheckCircle,
  XCircle,
  Clock,
  Navigation,
  Sparkles,
  Info,
  ShieldCheck,
  Maximize2,
} from 'lucide-react';
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
  BENGALURU_JUNCTIONS,
} from '../utils/mockTrafficData';
import { createIncidentIcon, createJunctionIcon } from '../utils/leafletIcons';

function SimMapController({ coordinates }) {
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

function WhatIfSimulatorPage() {
  const { isConnected } = useConnection();
  const [roads, setRoads] = useState(BENGALURU_ROADS);
  const [junctions, setJunctions] = useState(BENGALURU_JUNCTIONS);

  // Simulation Controls Form State
  const [selectedRoadId, setSelectedRoadId] = useState('RD-02'); // Outer Ring Road (Silk Board to Marathahalli)
  const [scenarioType, setScenarioType] = useState('closure'); // 'closure' | 'accident' | 'congestion'
  const [originId, setOriginId] = useState('JN-01'); // Silk Board
  const [destinationId, setDestinationId] = useState('JN-06'); // Marathahalli Bridge
  const [congestionMultiplier, setCongestionMultiplier] = useState(2.0);

  // Simulation Status
  const [isRunning, setIsRunning] = useState(false);
  const [simulationResult, setSimulationResult] = useState(null);
  const [simError, setSimError] = useState(null);

  // Run initial baseline simulation on mount
  useEffect(() => {
    handleRunSimulation();
  }, []);

  const handleRunSimulation = async () => {
    setIsRunning(true);
    setSimError(null);

    const params = {
      roadId: selectedRoadId,
      scenarioType,
      congestionMultiplier,
      originJunctionId: originId,
      destinationJunctionId: destinationId,
    };

    const res = await simulationService.runSimulation(params);

    if (res.data) {
      setSimulationResult(res.data);
    } else {
      setSimError(res.error || 'Failed to simulate scenario.');
    }
    setIsRunning(false);
  };

  const handleReset = () => {
    setSelectedRoadId('RD-02');
    setScenarioType('closure');
    setOriginId('JN-01');
    setDestinationId('JN-06');
    setCongestionMultiplier(2.0);
    setSimulationResult(null);
    setSimError(null);
  };

  const selectedRoad = roads.find((r) => r.id === selectedRoadId);

  // All coordinates to fit bounds
  const mapCoordinatesToFit = [
    ...(simulationResult?.baselineRoute?.coordinates || []),
    ...(simulationResult?.interventionRoute?.coordinates || []),
    ...(selectedRoad?.coordinates || []),
  ];

  return (
    <PageContainer className="simulator-page">
      {/* Module Header */}
      <div className="section-header">
        <div className="section-header__left">
          <div className="section-header__icon" style={{ backgroundColor: 'rgba(168, 85, 247, 0.15)', color: '#a855f7' }}>
            <FlaskConical size={20} />
          </div>
          <div className="section-header__text">
            <h2>What-If Traffic Simulator &amp; Disruption Sandbox</h2>
            <p>
              Hypothetical road closure modeling, simulated collision impact, dynamic re-routing, and capacity stress-testing
            </p>
          </div>
        </div>

        <div className="section-header__actions">
          <span className="live-status-pill live-status-pill--demo">
            Hero Feature • Predictive Simulation Engine
          </span>
        </div>
      </div>

      {/* Main Grid: Left Controls & Comparison, Right Map */}
      <div className="simulator-layout-grid">
        {/* LEFT COLUMN: Controls & Comparative Metrics */}
        <div className="simulator-control-column">
          {/* Simulation Configuration Card */}
          <div className="sim-card">
            <h3 className="sim-card__title">Scenario Intervention Setup</h3>

            {/* Step 1: Select Road Segment */}
            <div className="form-group" style={{ marginTop: 12 }}>
              <label>1. Target Road Corridor</label>
              <select
                value={selectedRoadId}
                onChange={(e) => setSelectedRoadId(e.target.value)}
              >
                {roads.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.id}: {r.name} ({r.distanceKm} km, {r.status.toUpperCase()})
                  </option>
                ))}
              </select>
            </div>

            {/* Step 2: Scenario Intervention Type */}
            <div className="form-group">
              <label>2. Intervention Scenario Type</label>
              <div className="scenario-btn-grid">
                <button
                  type="button"
                  className={`scenario-btn ${scenarioType === 'closure' ? 'scenario-btn--active' : ''}`}
                  onClick={() => setScenarioType('closure')}
                >
                  <XCircle size={15} />
                  <span>Road Closure</span>
                </button>
                <button
                  type="button"
                  className={`scenario-btn ${scenarioType === 'accident' ? 'scenario-btn--active' : ''}`}
                  onClick={() => setScenarioType('accident')}
                >
                  <AlertTriangle size={15} />
                  <span>Major Accident</span>
                </button>
                <button
                  type="button"
                  className={`scenario-btn ${scenarioType === 'congestion' ? 'scenario-btn--active' : ''}`}
                  onClick={() => setScenarioType('congestion')}
                >
                  <Activity size={15} />
                  <span>Congestion Surge</span>
                </button>
              </div>
            </div>

            {/* Step 3: Origin & Destination Corridor */}
            <div className="form-row-2">
              <div className="form-group">
                <label>Origin Junction</label>
                <select value={originId} onChange={(e) => setOriginId(e.target.value)}>
                  {junctions.map((j) => (
                    <option key={j.id} value={j.id}>
                      {j.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label>Destination Junction</label>
                <select value={destinationId} onChange={(e) => setDestinationId(e.target.value)}>
                  {junctions.map((j) => (
                    <option key={j.id} value={j.id}>
                      {j.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Congestion Multiplier Slider (if Congestion Surge) */}
            {scenarioType === 'congestion' && (
              <div className="form-group">
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                  <label>Traffic Density Spike</label>
                  <span className="font-mono" style={{ color: '#f59e0b' }}>
                    +{Math.round((congestionMultiplier - 1) * 100)}% Volume Delay
                  </span>
                </div>
                <input
                  type="range"
                  min="1.2"
                  max="3.5"
                  step="0.1"
                  value={congestionMultiplier}
                  onChange={(e) => setCongestionMultiplier(Number(e.target.value))}
                  style={{ width: '100%', marginTop: 6 }}
                />
              </div>
            )}

            {/* Run Button */}
            <div className="routing-actions-row">
              <button
                className="dashboard-btn dashboard-btn--primary"
                style={{ flex: 1, justifyContent: 'center' }}
                onClick={handleRunSimulation}
                disabled={isRunning}
              >
                <Play size={15} />
                <span>{isRunning ? 'Synthesizing Network Disruption…' : 'Execute What-If Simulation'}</span>
              </button>
              <button className="dashboard-btn" onClick={handleReset} title="Restore baseline conditions">
                <RotateCcw size={15} />
                <span>Reset</span>
              </button>
            </div>
          </div>

          {/* Error Notice */}
          {simError && (
            <div className="alert-message alert-message--error">
              <AlertTriangle size={18} />
              <span>{simError}</span>
            </div>
          )}

          {/* SECTION D: SIMULATION COMPARISON RESULTS */}
          {simulationResult && (
            <div className="simulation-results-pane">
              {/* Comparative Metrics Card */}
              <div className="sim-comparison-card">
                <div className="comparison-header">
                  <div>
                    <h4 className="comparison-title">Baseline vs Intervention Impact</h4>
                    <span className="text-muted" style={{ fontSize: 11 }}>
                      Simulated {simulationResult.scenarioType.toUpperCase()} on {simulationResult.selectedRoad?.id}
                    </span>
                  </div>
                  <StatusBadge label={simulationResult.routeValidity} variant="success" />
                </div>

                <div className="comparison-delta-grid">
                  {/* Distance Comparison */}
                  <div className="delta-card">
                    <span className="delta-label">Route Distance</span>
                    <div className="delta-values-row">
                      <span className="delta-orig font-mono">{simulationResult.originalDistanceKm} km</span>
                      <ArrowRight size={14} className="delta-arrow" />
                      <span className="delta-new font-mono">{simulationResult.newDistanceKm} km</span>
                    </div>
                    <span
                      className={`delta-tag font-mono ${
                        simulationResult.distanceDeltaKm > 0 ? 'delta-tag--warning' : 'delta-tag--good'
                      }`}
                    >
                      {simulationResult.distanceDeltaKm >= 0
                        ? `+${simulationResult.distanceDeltaKm} km detour`
                        : `${simulationResult.distanceDeltaKm} km`}
                    </span>
                  </div>

                  {/* Travel Time Comparison */}
                  <div className="delta-card">
                    <span className="delta-label">Modeled Travel Time</span>
                    <div className="delta-values-row">
                      <span className="delta-orig font-mono">{simulationResult.originalTimeMinutes} mins</span>
                      <ArrowRight size={14} className="delta-arrow" />
                      <span className="delta-new font-mono" style={{ color: '#00d4ff' }}>
                        {simulationResult.newTimeMinutes} mins
                      </span>
                    </div>
                    <span
                      className={`delta-tag font-mono ${
                        simulationResult.timeDeltaMinutes > 0 ? 'delta-tag--warning' : 'delta-tag--good'
                      }`}
                    >
                      {simulationResult.timeDeltaMinutes >= 0
                        ? `+${simulationResult.timeDeltaMinutes} mins delay`
                        : `${simulationResult.timeDeltaMinutes} mins`}
                    </span>
                  </div>

                  {/* Safety & Compliance */}
                  <div className="delta-card">
                    <span className="delta-label">Closed-Road Violations</span>
                    <span className="delta-new font-mono" style={{ color: '#10b981', fontSize: 20 }}>
                      {simulationResult.closedRoadViolations}
                    </span>
                    <span className="delta-tag delta-tag--good font-mono">100% Avoidance Verified</span>
                  </div>

                  {/* Latency */}
                  <div className="delta-card">
                    <span className="delta-label">Inference Latency</span>
                    <span className="delta-new font-mono" style={{ fontSize: 20 }}>
                      {simulationResult.computationTimeMs} ms
                    </span>
                    <span className="delta-tag font-mono text-muted">Simulated Engine</span>
                  </div>
                </div>

                {/* SECTION G: SIMULATION EXPLANATION */}
                <div className="sim-explanation-box">
                  <div className="sim-explanation-header">
                    <Info size={14} style={{ color: '#00d4ff' }} />
                    <strong>Automated Routing Engine Diagnosis:</strong>
                  </div>
                  <p className="sim-explanation-text">{simulationResult.explanation}</p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* RIGHT COLUMN: SECTION E: MAP VISUALIZATION */}
        <div className="simulator-map-card">
          <div className="routing-map-card__header">
            <div className="routing-map-title">
              <FlaskConical size={15} style={{ color: '#a855f7' }} />
              <span>Spatial Simulation Topology (Live GIS Comparison)</span>
            </div>
            <div className="map-legend-pills">
              <span className="map-legend-pill map-legend-pill--primary">Baseline Route (Cyan)</span>
              <span className="map-legend-pill map-legend-pill--alt">Rerouted Intervention (Purple)</span>
              <span className="map-legend-pill map-legend-pill--closed">Simulated Blockage (Red)</span>
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

              <SimMapController coordinates={mapCoordinatesToFit.length > 0 ? mapCoordinatesToFit : null} />

              {/* Background Network (Dimmed) */}
              {roads.map((road) => (
                <Polyline
                  key={`bg-sim-${road.id}`}
                  positions={road.coordinates}
                  pathOptions={{
                    color: '#162a3e',
                    weight: 2,
                    opacity: 0.4,
                  }}
                />
              ))}

              {/* 1. Original Baseline Route (Cyan, dashed) */}
              {simulationResult?.baselineRoute && (
                <Polyline
                  positions={simulationResult.baselineRoute.coordinates}
                  pathOptions={{
                    color: '#00d4ff',
                    weight: 4,
                    opacity: 0.7,
                    dashArray: '8, 8',
                  }}
                >
                  <Popup className="custom-leaflet-popup">
                    <div className="map-popup-card">
                      <div className="map-popup-title" style={{ color: '#00d4ff' }}>
                        Baseline Route (Normal Conditions)
                      </div>
                      <div className="map-popup-row">
                        <span>Original Distance:</span>
                        <span className="font-mono">{simulationResult.originalDistanceKm} km</span>
                      </div>
                      <div className="map-popup-row">
                        <span>Original Travel Time:</span>
                        <span className="font-mono">{simulationResult.originalTimeMinutes} mins</span>
                      </div>
                    </div>
                  </Popup>
                </Polyline>
              )}

              {/* 2. New Re-routed Intervention Route (Solid Purple) */}
              {simulationResult?.interventionRoute && (
                <Polyline
                  positions={simulationResult.interventionRoute.coordinates}
                  pathOptions={{
                    color: '#a855f7',
                    weight: 6,
                    opacity: 1.0,
                  }}
                >
                  <Popup className="custom-leaflet-popup">
                    <div className="map-popup-card">
                      <div className="map-popup-title" style={{ color: '#a855f7' }}>
                        Intervention Reroute (Detour Applied)
                      </div>
                      <div className="map-popup-row">
                        <span>New Distance:</span>
                        <span className="font-mono">{simulationResult.newDistanceKm} km</span>
                      </div>
                      <div className="map-popup-row">
                        <span>New Transit Time:</span>
                        <span className="font-mono">{simulationResult.newTimeMinutes} mins</span>
                      </div>
                    </div>
                  </Popup>
                </Polyline>
              )}

              {/* 3. The Intervened/Closed Road Segment (Red pulsating line) */}
              {selectedRoad && (
                <Polyline
                  positions={selectedRoad.coordinates}
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
                        ⛔ SIMULATED DISRUPTION: {selectedRoad.name}
                      </div>
                      <div className="map-popup-row">
                        <span>Intervention:</span>
                        <strong>{scenarioType.toUpperCase()}</strong>
                      </div>
                      <div className="map-popup-row">
                        <span>Status:</span>
                        <span>Corridor Blocked to Traffic</span>
                      </div>
                    </div>
                  </Popup>
                </Polyline>
              )}

              {/* Simulated Accident Marker if scenario is accident */}
              {scenarioType === 'accident' && selectedRoad?.coordinates[1] && (
                <Marker
                  position={selectedRoad.coordinates[1]}
                  icon={createIncidentIcon('critical')}
                >
                  <Popup className="custom-leaflet-popup">
                    <div className="map-popup-card">
                      <div className="map-popup-title" style={{ color: '#ef4444' }}>
                        ⚠️ Simulated Incident Location
                      </div>
                    </div>
                  </Popup>
                </Marker>
              )}

              {/* Origin Marker */}
              {simulationResult?.originJunction && (
                <Marker
                  position={simulationResult.originJunction.coordinates}
                  icon={createJunctionIcon(simulationResult.originJunction.name, true)}
                >
                  <Popup className="custom-leaflet-popup">
                    <div className="map-popup-card">
                      <div className="map-popup-title" style={{ color: '#10b981' }}>
                        🟢 Journey Origin: {simulationResult.originJunction.name}
                      </div>
                    </div>
                  </Popup>
                </Marker>
              )}

              {/* Destination Marker */}
              {simulationResult?.destinationJunction && (
                <Marker
                  position={simulationResult.destinationJunction.coordinates}
                  icon={createJunctionIcon(simulationResult.destinationJunction.name, true)}
                >
                  <Popup className="custom-leaflet-popup">
                    <div className="map-popup-card">
                      <div className="map-popup-title" style={{ color: '#00d4ff' }}>
                        🏁 Journey Destination: {simulationResult.destinationJunction.name}
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

export default WhatIfSimulatorPage;
