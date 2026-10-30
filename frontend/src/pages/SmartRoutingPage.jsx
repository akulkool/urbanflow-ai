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
  Route as RouteIcon,
  Navigation,
  HeartPulse,
  Truck,
  Car,
  Clock,
  ShieldCheck,
  AlertTriangle,
  RotateCcw,
  Sparkles,
  Info,
  Layers,
  ArrowRight,
  Maximize2,
} from 'lucide-react';
import {
  PageContainer,
  LoadingState,
  ErrorState,
  StatusBadge,
} from '../components';
import { routingService, trafficService } from '../services';
import { useConnection } from '../context';
import {
  BENGALURU_CENTER,
  DEFAULT_ZOOM,
  BENGALURU_JUNCTIONS,
  BENGALURU_HOSPITALS,
  BENGALURU_ROADS,
} from '../utils/mockTrafficData';
import {
  createJunctionIcon,
  createHospitalIcon,
  createIncidentIcon,
} from '../utils/leafletIcons';

// Route fitBounds helper
function RouteMapController({ coordinates }) {
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

function SmartRoutingPage() {
  const { isConnected } = useConnection();
  const [junctions, setJunctions] = useState(BENGALURU_JUNCTIONS);
  const [hospitals, setHospitals] = useState(BENGALURU_HOSPITALS);
  const [roads, setRoads] = useState(BENGALURU_ROADS);

  // Form Inputs
  const [originId, setOriginId] = useState('JN-01'); // Silk Board
  const [destinationType, setDestinationType] = useState('hospital'); // 'hospital' | 'junction'
  const [destinationJunctionId, setDestinationJunctionId] = useState('JN-02'); // Hebbal
  const [selectedHospitalId, setSelectedHospitalId] = useState('HOSP-01'); // Manipal
  const [transportMode, setTransportMode] = useState('emergency'); // 'emergency' | 'standard'
  const [avoidIncidents, setAvoidIncidents] = useState(true);

  // State
  const [isCalculating, setIsCalculating] = useState(false);
  const [routeResult, setRouteResult] = useState(null);
  const [calcError, setCalcError] = useState(null);
  const [activeRouteTab, setActiveRouteTab] = useState('primary'); // 'primary' | 'alternative'

  // Initial auto-calculation for immediate operator demonstration
  useEffect(() => {
    handleCalculateRoute();
  }, []);

  const handleCalculateRoute = async () => {
    setIsCalculating(true);
    setCalcError(null);

    const params = {
      originJunctionId: originId,
      destinationJunctionId: destinationType === 'junction' ? destinationJunctionId : null,
      hospitalId: destinationType === 'hospital' ? selectedHospitalId : null,
      transportMode,
      avoidIncidents,
    };

    const res = await routingService.calculateRoute(params);

    if (res.data && res.data.success) {
      setRouteResult(res.data);
      setActiveRouteTab('primary');
    } else {
      setRouteResult(null);
      setCalcError(res.data?.error || res.error || 'Failed to compute a valid route.');
    }
    setIsCalculating(false);
  };

  const handleReset = () => {
    setOriginId('JN-01');
    setDestinationType('hospital');
    setSelectedHospitalId('HOSP-01');
    setDestinationJunctionId('JN-02');
    setTransportMode('emergency');
    setAvoidIncidents(true);
    setCalcError(null);
    setRouteResult(null);
  };

  const primaryRoute = routeResult?.primaryRoute;
  const alternativeRoute = routeResult?.alternativeRoute;

  // Polyline bounds to fit
  const activeCoordinates =
    activeRouteTab === 'primary' ? primaryRoute?.coordinates : alternativeRoute?.coordinates || primaryRoute?.coordinates;

  return (
    <PageContainer className="smart-routing-page">
      {/* Module Title */}
      <div className="section-header">
        <div className="section-header__left">
          <div className="section-header__icon" style={{ backgroundColor: 'rgba(0, 212, 255, 0.15)', color: '#00d4ff' }}>
            <RouteIcon size={20} />
          </div>
          <div className="section-header__text">
            <h2>Smart Emergency Routing &amp; Corridor Navigation</h2>
            <p>
              Autonomous shortest-path graph optimization, real-time bottleneck avoidance, and trauma hospital corridors
            </p>
          </div>
        </div>

        <div className="section-header__actions">
          <span className="live-status-pill live-status-pill--demo">
            NetworkX / Dijkstra Graph Engine
          </span>
        </div>
      </div>

      {/* Main Grid: Left = Routing Controls & Results, Right = Leaflet Map */}
      <div className="routing-layout-grid">
        {/* LEFT COLUMN: Controls & Route Details */}
        <div className="routing-control-panel">
          {/* SECTION A: ROUTE INPUT PANEL */}
          <div className="routing-card">
            <h3 className="routing-card__title">Emergency Routing Parameters</h3>

            <div className="form-group" style={{ marginTop: 12 }}>
              <label>Origin Junction</label>
              <select value={originId} onChange={(e) => setOriginId(e.target.value)}>
                {junctions.map((j) => (
                  <option key={j.id} value={j.id}>
                    {j.name} ({j.id})
                  </option>
                ))}
              </select>
            </div>

            {/* Destination Mode Toggle */}
            <div className="form-group">
              <label>Destination Target</label>
              <div className="destination-type-toggle">
                <button
                  type="button"
                  className={`dest-btn ${destinationType === 'hospital' ? 'dest-btn--active' : ''}`}
                  onClick={() => setDestinationType('hospital')}
                >
                  <HeartPulse size={14} />
                  <span>Trauma Hospital</span>
                </button>
                <button
                  type="button"
                  className={`dest-btn ${destinationType === 'junction' ? 'dest-btn--active' : ''}`}
                  onClick={() => setDestinationType('junction')}
                >
                  <Navigation size={14} />
                  <span>Junction Corridor</span>
                </button>
              </div>
            </div>

            {/* Destination Selection */}
            {destinationType === 'hospital' ? (
              <div className="form-group">
                <label>Select Emergency Hospital</label>
                <select
                  value={selectedHospitalId}
                  onChange={(e) => setSelectedHospitalId(e.target.value)}
                >
                  {hospitals.map((h) => (
                    <option key={h.id} value={h.id}>
                      {h.name} — {h.area} ({h.emergencyUnits} Ambulances)
                    </option>
                  ))}
                </select>
              </div>
            ) : (
              <div className="form-group">
                <label>Select Destination Junction</label>
                <select
                  value={destinationJunctionId}
                  onChange={(e) => setDestinationJunctionId(e.target.value)}
                >
                  {junctions.map((j) => (
                    <option key={j.id} value={j.id}>
                      {j.name} ({j.id})
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Transport Mode */}
            <div className="form-group">
              <label>Vehicle Priority Profile</label>
              <div className="transport-mode-grid">
                <button
                  type="button"
                  className={`transport-btn ${transportMode === 'emergency' ? 'transport-btn--active' : ''}`}
                  onClick={() => setTransportMode('emergency')}
                >
                  <HeartPulse size={14} />
                  <span>Emergency (108)</span>
                </button>
                <button
                  type="button"
                  className={`transport-btn ${transportMode === 'standard' ? 'transport-btn--active' : ''}`}
                  onClick={() => setTransportMode('standard')}
                >
                  <Car size={14} />
                  <span>Standard Traffic</span>
                </button>
              </div>
            </div>

            {/* Avoid Incidents Checkbox */}
            <div className="checkbox-row">
              <input
                type="checkbox"
                id="avoidIncidentsCheckbox"
                checked={avoidIncidents}
                onChange={(e) => setAvoidIncidents(e.target.checked)}
              />
              <label htmlFor="avoidIncidentsCheckbox">
                Enforce critical incident and road closure avoidance
              </label>
            </div>

            {/* Action Buttons */}
            <div className="routing-actions-row">
              <button
                className="dashboard-btn dashboard-btn--primary"
                style={{ flex: 1, justifyContent: 'center' }}
                onClick={handleCalculateRoute}
                disabled={isCalculating}
              >
                <Sparkles size={15} />
                <span>{isCalculating ? 'Computing Optimal Path…' : 'Calculate Optimal Route'}</span>
              </button>
              <button className="dashboard-btn" onClick={handleReset} title="Reset to defaults">
                <RotateCcw size={15} />
              </button>
            </div>
          </div>

          {/* SECTION F: ERROR HANDLING */}
          {calcError && (
            <div className="alert-message alert-message--error" style={{ marginTop: 16 }}>
              <AlertTriangle size={18} />
              <div>
                <strong>Routing Failed:</strong> {calcError}
              </div>
            </div>
          )}

          {/* SECTION C & D: ROUTE RESULTS & ALTERNATIVES */}
          {routeResult && routeResult.success && primaryRoute && (
            <div className="route-results-panel">
              {/* Route Tabs: Primary vs Alternative */}
              <div className="route-tab-header">
                <button
                  className={`route-tab-btn ${activeRouteTab === 'primary' ? 'route-tab-btn--primary' : ''}`}
                  onClick={() => setActiveRouteTab('primary')}
                >
                  <span className="route-dot route-dot--cyan" />
                  <span>Primary Route</span>
                  <span className="route-dist-tag font-mono">{primaryRoute.totalDistanceKm} km</span>
                </button>

                {alternativeRoute && (
                  <button
                    className={`route-tab-btn ${activeRouteTab === 'alternative' ? 'route-tab-btn--purple' : ''}`}
                    onClick={() => setActiveRouteTab('alternative')}
                  >
                    <span className="route-dot route-dot--purple" />
                    <span>Alternative Route</span>
                    <span className="route-dist-tag font-mono">{alternativeRoute.totalDistanceKm} km</span>
                  </button>
                )}
              </div>

              {/* Metrics Summary Strip */}
              <div className="route-metrics-strip">
                <div className="route-metric-box">
                  <span className="route-metric-label">Total Distance</span>
                  <span className="route-metric-val font-mono">
                    {activeRouteTab === 'primary' ? primaryRoute.totalDistanceKm : alternativeRoute.totalDistanceKm} km
                  </span>
                </div>
                <div className="route-metric-box">
                  <span className="route-metric-label">Estimated Transit</span>
                  <span className="route-metric-val font-mono" style={{ color: '#00d4ff' }}>
                    {activeRouteTab === 'primary' ? primaryRoute.estimatedTimeMinutes : alternativeRoute.estimatedTimeMinutes} mins
                  </span>
                </div>
                <div className="route-metric-box">
                  <span className="route-metric-label">Modeled Cost</span>
                  <span className="route-metric-val font-mono">
                    {activeRouteTab === 'primary' ? primaryRoute.modeledCost : alternativeRoute.modeledCost}
                  </span>
                </div>
                <div className="route-metric-box">
                  <span className="route-metric-label">Compute Latency</span>
                  <span className="route-metric-val font-mono text-muted">
                    {routeResult.computationTimeMs} ms
                  </span>
                </div>
              </div>

              {/* Route Explanation */}
              <div className="route-explanation-card">
                <div className="explanation-title">
                  <Info size={14} />
                  <span>Route Selection Rationale</span>
                </div>
                <p>{routeResult.explanation}</p>
                <div className="explanation-tags">
                  <StatusBadge label={routeResult.validity} variant="success" />
                  <StatusBadge label="0 Blocked Edges Traversed" variant="info" />
                  {avoidIncidents && <StatusBadge label="Incidents Bypassed" variant="neutral" />}
                </div>
              </div>

              {/* Ordered Road Segments List */}
              <div className="route-segments-card">
                <div className="segments-title">
                  Traversed Road Corridors (
                  {activeRouteTab === 'primary' ? primaryRoute.roadSegments.length : alternativeRoute.roadSegments.length} Segments)
                </div>
                <div className="segments-list">
                  {(activeRouteTab === 'primary' ? primaryRoute.roadSegments : alternativeRoute.roadSegments).map(
                    (road, idx) => (
                      <div key={`${road.id}-${idx}`} className="segment-row">
                        <span className="segment-step font-mono">{idx + 1}</span>
                        <div className="segment-info">
                          <div className="segment-name">{road.name}</div>
                          <div className="segment-meta">
                            <span>{road.distanceKm} km</span>
                            <span>•</span>
                            <span style={{ color: road.status === 'open' ? '#10b981' : '#f59e0b' }}>
                              {road.currentSpeed} km/h ({road.status.toUpperCase()})
                            </span>
                          </div>
                        </div>
                        <span className="segment-id font-mono">{road.id}</span>
                      </div>
                    )
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* RIGHT COLUMN: SECTION E: INTERACTIVE ROUTE MAP */}
        <div className="routing-map-card">
          <div className="routing-map-card__header">
            <div className="routing-map-title">
              <Navigation size={15} style={{ color: '#00d4ff' }} />
              <span>Synthesized Route Geometry on Bengaluru GIS</span>
            </div>
            <div className="map-legend-pills">
              <span className="map-legend-pill map-legend-pill--primary">Primary Path (Cyan)</span>
              {alternativeRoute && (
                <span className="map-legend-pill map-legend-pill--alt">Alternative (Purple)</span>
              )}
              <span className="map-legend-pill map-legend-pill--closed">Closed Corridors (Red)</span>
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

              <RouteMapController coordinates={activeCoordinates} />

              {/* Base Road Network (Dimmed) */}
              {roads.map((road) => (
                <Polyline
                  key={`bg-${road.id}`}
                  positions={road.coordinates}
                  pathOptions={{
                    color: road.status === 'closed' ? '#ef4444' : '#1e3a5f',
                    weight: road.status === 'closed' ? 4 : 2,
                    opacity: road.status === 'closed' ? 0.9 : 0.4,
                    dashArray: road.status === 'closed' ? '6, 6' : null,
                  }}
                />
              ))}

              {/* Alternative Route Polyline (Purple) */}
              {alternativeRoute && (
                <Polyline
                  positions={alternativeRoute.coordinates}
                  pathOptions={{
                    color: '#a855f7',
                    weight: activeRouteTab === 'alternative' ? 7 : 4,
                    opacity: activeRouteTab === 'alternative' ? 1.0 : 0.7,
                    dashArray: '8, 8',
                  }}
                >
                  <Popup className="custom-leaflet-popup">
                    <div className="map-popup-card">
                      <div className="map-popup-title" style={{ color: '#a855f7' }}>
                        Alternative Route Option
                      </div>
                      <div className="map-popup-row">
                        <span>Distance:</span>
                        <span className="font-mono">{alternativeRoute.totalDistanceKm} km</span>
                      </div>
                      <div className="map-popup-row">
                        <span>Est. Travel Time:</span>
                        <span className="font-mono">{alternativeRoute.estimatedTimeMinutes} mins</span>
                      </div>
                    </div>
                  </Popup>
                </Polyline>
              )}

              {/* Primary Route Polyline (Cyan/Blue) */}
              {primaryRoute && (
                <Polyline
                  positions={primaryRoute.coordinates}
                  pathOptions={{
                    color: '#00d4ff',
                    weight: activeRouteTab === 'primary' ? 7 : 4,
                    opacity: activeRouteTab === 'primary' ? 1.0 : 0.7,
                  }}
                >
                  <Popup className="custom-leaflet-popup">
                    <div className="map-popup-card">
                      <div className="map-popup-title" style={{ color: '#00d4ff' }}>
                        Primary Recommended Route
                      </div>
                      <div className="map-popup-row">
                        <span>Distance:</span>
                        <span className="font-mono">{primaryRoute.totalDistanceKm} km</span>
                      </div>
                      <div className="map-popup-row">
                        <span>Transit Time:</span>
                        <span className="font-mono">{primaryRoute.estimatedTimeMinutes} mins</span>
                      </div>
                      <div className="map-popup-row">
                        <span>Corridors:</span>
                        <span>{primaryRoute.roadSegments.length} segments</span>
                      </div>
                    </div>
                  </Popup>
                </Polyline>
              )}

              {/* Origin Marker */}
              {routeResult?.originJunction && (
                <Marker
                  position={routeResult.originJunction.coordinates}
                  icon={createJunctionIcon(routeResult.originJunction.name, true)}
                >
                  <Popup className="custom-leaflet-popup">
                    <div className="map-popup-card">
                      <div className="map-popup-title" style={{ color: '#10b981' }}>
                        🟢 Route Origin: {routeResult.originJunction.name}
                      </div>
                    </div>
                  </Popup>
                </Marker>
              )}

              {/* Destination Marker (Junction or Hospital) */}
              {destinationType === 'hospital' && routeResult?.targetHospital ? (
                <Marker
                  position={routeResult.targetHospital.coordinates}
                  icon={createHospitalIcon()}
                >
                  <Popup className="custom-leaflet-popup">
                    <div className="map-popup-card">
                      <div className="map-popup-title" style={{ color: '#ef4444' }}>
                        🏥 Destination Trauma Center: {routeResult.targetHospital.name}
                      </div>
                      <div className="map-popup-row">
                        <span>Emergency Fleet:</span>
                        <span>{routeResult.targetHospital.emergencyUnits} Ambulances Available</span>
                      </div>
                    </div>
                  </Popup>
                </Marker>
              ) : routeResult?.destinationJunction ? (
                <Marker
                  position={routeResult.destinationJunction.coordinates}
                  icon={createJunctionIcon(routeResult.destinationJunction.name, true)}
                >
                  <Popup className="custom-leaflet-popup">
                    <div className="map-popup-card">
                      <div className="map-popup-title" style={{ color: '#00d4ff' }}>
                        🏁 Destination: {routeResult.destinationJunction.name}
                      </div>
                    </div>
                  </Popup>
                </Marker>
              ) : null}
            </MapContainer>
          </div>
        </div>
      </div>
    </PageContainer>
  );
}

export default SmartRoutingPage;
