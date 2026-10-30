import { useState, useEffect, useRef } from 'react';
import {
  MapContainer,
  TileLayer,
  Polyline,
  Marker,
  Popup,
  useMap,
} from 'react-leaflet';
import {
  Map as MapIcon,
  Layers,
  Filter,
  Maximize2,
  AlertTriangle,
  HeartPulse,
  Navigation,
  Info,
  RefreshCw,
} from 'lucide-react';
import {
  PageContainer,
  LoadingState,
  ErrorState,
  StatusBadge,
} from '../components';
import { trafficService, incidentService } from '../services';
import { useConnection } from '../context';
import {
  BENGALURU_CENTER,
  DEFAULT_ZOOM,
  BENGALURU_ROADS,
  BENGALURU_JUNCTIONS,
  BENGALURU_HOSPITALS,
  BENGALURU_INCIDENTS,
} from '../utils/mockTrafficData';
import {
  createJunctionIcon,
  createHospitalIcon,
  createIncidentIcon,
} from '../utils/leafletIcons';

const ROAD_COLORS = {
  open: '#10b981',
  congested: '#f59e0b',
  closed: '#ef4444',
};

// Map controller component for fit bounds and programmatical flyTo
function MapController({ center, zoom, bounds }) {
  const map = useMap();

  useEffect(() => {
    if (bounds && bounds.length > 0) {
      try {
        map.fitBounds(bounds, { padding: [40, 40] });
      } catch (e) {
        map.setView(center, zoom);
      }
    } else {
      map.setView(center, zoom);
    }
  }, [center, zoom, bounds, map]);

  return null;
}

function InteractiveMapPage() {
  const { isConnected } = useConnection();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Map Data
  const [roads, setRoads] = useState([]);
  const [junctions, setJunctions] = useState([]);
  const [hospitals, setHospitals] = useState([]);
  const [incidents, setIncidents] = useState([]);

  // Layer Visibility Controls
  const [showRoads, setShowRoads] = useState(true);
  const [showJunctions, setShowJunctions] = useState(true);
  const [showHospitals, setShowHospitals] = useState(true);
  const [showIncidents, setShowIncidents] = useState(true);

  // Status Filter
  const [roadFilter, setRoadFilter] = useState('all'); // all | open | congested | closed

  // Selected Entity for Detail Drawer
  const [selectedEntity, setSelectedEntity] = useState(null);

  const loadMapData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [roadsRes, junctionsRes, hospitalsRes, incidentsRes] = await Promise.all([
        trafficService.getRoads(),
        trafficService.getJunctions(),
        trafficService.getHospitals(),
        incidentService.getIncidents(),
      ]);

      setRoads(roadsRes.data || BENGALURU_ROADS);
      setJunctions(junctionsRes.data || BENGALURU_JUNCTIONS);
      setHospitals(hospitalsRes.data || BENGALURU_HOSPITALS);
      setIncidents(incidentsRes.data || BENGALURU_INCIDENTS);
    } catch (err) {
      console.warn('Map data load error, using simulated Bengaluru network:', err);
      setRoads(BENGALURU_ROADS);
      setJunctions(BENGALURU_JUNCTIONS);
      setHospitals(BENGALURU_HOSPITALS);
      setIncidents(BENGALURU_INCIDENTS);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMapData();
  }, []);

  // Filter roads based on user choice
  const filteredRoads = roads.filter((r) => {
    if (roadFilter === 'all') return true;
    return r.status.toLowerCase() === roadFilter.toLowerCase();
  });

  // Calculate network bounds for fitBounds
  const allCoordinates = roads.flatMap((r) => r.coordinates || []);
  const networkBounds = allCoordinates.length > 0 ? allCoordinates : null;

  const handleFitNetwork = () => {
    setSelectedEntity(null);
    setRoadFilter('all');
  };

  if (loading) {
    return (
      <PageContainer>
        <LoadingState message="Rendering Bengaluru Traffic GIS Network…" />
      </PageContainer>
    );
  }

  if (error) {
    return (
      <PageContainer>
        <ErrorState
          title="Interactive Map Offline"
          message={error}
          onRetry={loadMapData}
        />
      </PageContainer>
    );
  }

  return (
    <PageContainer className="interactive-map-page">
      {/* Top Map Toolbar */}
      <div className="map-toolbar">
        <div className="map-toolbar__title-group">
          <div className="map-toolbar__icon-box">
            <MapIcon size={20} />
          </div>
          <div>
            <div className="map-toolbar__title-row">
              <h1 className="map-toolbar__title">Interactive Traffic GIS Network</h1>
              <span className="live-status-pill live-status-pill--demo">
                Bengaluru-Inspired Simulated Network
              </span>
            </div>
            <p className="map-toolbar__subtitle">
              Live spatial routing GIS, road condition telemetry, junction phases, and emergency hospital access
            </p>
          </div>
        </div>

        {/* Toolbar Controls */}
        <div className="map-toolbar__actions">
          {/* Status Filter */}
          <div className="map-filter-group">
            <Filter size={14} className="map-filter-icon" />
            <select
              value={roadFilter}
              onChange={(e) => setRoadFilter(e.target.value)}
              className="map-filter-select"
            >
              <option value="all">All Corridors ({roads.length})</option>
              <option value="open">Open Corridors ({roads.filter((r) => r.status === 'open').length})</option>
              <option value="congested">Congested ({roads.filter((r) => r.status === 'congested').length})</option>
              <option value="closed">Closed / Diversion ({roads.filter((r) => r.status === 'closed').length})</option>
            </select>
          </div>

          {/* Layer Toggles */}
          <div className="layer-toggle-group">
            <button
              className={`layer-btn ${showRoads ? 'layer-btn--active' : ''}`}
              onClick={() => setShowRoads((v) => !v)}
              title="Toggle Road Polylines"
            >
              Roads
            </button>
            <button
              className={`layer-btn ${showJunctions ? 'layer-btn--active' : ''}`}
              onClick={() => setShowJunctions((v) => !v)}
              title="Toggle Signal Junctions"
            >
              Junctions
            </button>
            <button
              className={`layer-btn ${showHospitals ? 'layer-btn--active' : ''}`}
              onClick={() => setShowHospitals((v) => !v)}
              title="Toggle Emergency Hospitals"
            >
              Hospitals
            </button>
            <button
              className={`layer-btn ${showIncidents ? 'layer-btn--active' : ''}`}
              onClick={() => setShowIncidents((v) => !v)}
              title="Toggle Incidents"
            >
              Incidents
            </button>
          </div>

          <button className="map-btn map-btn--fit" onClick={handleFitNetwork} title="Fit network view">
            <Maximize2 size={14} />
            <span>Fit Bounds</span>
          </button>

          <button className="map-btn map-btn--refresh" onClick={loadMapData} title="Reload GIS layers">
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      {/* Main Map + Details Split View */}
      <div className="interactive-map-layout">
        <div className="interactive-map-canvas-card">
          <MapContainer
            center={BENGALURU_CENTER}
            zoom={DEFAULT_ZOOM}
            scrollWheelZoom={true}
            className="full-leaflet-container"
          >
            <TileLayer
              attribution='&copy; <a href="https://carto.com/">CARTO</a>'
              url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
            />

            <MapController center={BENGALURU_CENTER} zoom={DEFAULT_ZOOM} bounds={networkBounds} />

            {/* 1. Road Polylines */}
            {showRoads &&
              filteredRoads.map((road) => {
                const isSelected = selectedEntity?.type === 'road' && selectedEntity?.data?.id === road.id;
                return (
                  <Polyline
                    key={road.id}
                    positions={road.coordinates}
                    eventHandlers={{
                      click: () => setSelectedEntity({ type: 'road', data: road }),
                    }}
                    pathOptions={{
                      color: ROAD_COLORS[road.status] || '#3b82f6',
                      weight: isSelected ? 8 : road.status === 'closed' ? 6 : 5,
                      opacity: isSelected ? 1 : 0.85,
                      dashArray: road.status === 'closed' ? '8, 8' : null,
                    }}
                  >
                    <Popup className="custom-leaflet-popup">
                      <div className="map-popup-card">
                        <div className="map-popup-title">{road.name}</div>
                        <div className="map-popup-row">
                          <span>Status:</span>
                          <strong style={{ color: ROAD_COLORS[road.status] }}>
                            {road.status.toUpperCase()}
                          </strong>
                        </div>
                        <div className="map-popup-row">
                          <span>Corridor Length:</span>
                          <span>{road.distanceKm} km</span>
                        </div>
                        <div className="map-popup-row">
                          <span>Current Speed:</span>
                          <span>{road.currentSpeed} km/h (Limit: {road.speedLimit} km/h)</span>
                        </div>
                        <div className="map-popup-row">
                          <span>Congestion Density:</span>
                          <span>{road.congestionLevel}</span>
                        </div>
                        <div className="map-popup-row">
                          <span>Capacity / Lanes:</span>
                          <span>{road.lanes} lanes</span>
                        </div>
                      </div>
                    </Popup>
                  </Polyline>
                );
              })}

            {/* 2. Junction Markers */}
            {showJunctions &&
              junctions.map((junction) => (
                <Marker
                  key={junction.id}
                  position={junction.coordinates}
                  icon={createJunctionIcon(
                    junction.name,
                    selectedEntity?.type === 'junction' && selectedEntity?.data?.id === junction.id
                  )}
                  eventHandlers={{
                    click: () => setSelectedEntity({ type: 'junction', data: junction }),
                  }}
                >
                  <Popup className="custom-leaflet-popup">
                    <div className="map-popup-card">
                      <div className="map-popup-title" style={{ color: '#00d4ff' }}>
                        🚦 {junction.name}
                      </div>
                      <div className="map-popup-row">
                        <span>Junction ID:</span>
                        <span className="font-mono">{junction.id}</span>
                      </div>
                      <div className="map-popup-row">
                        <span>Cycle Duration:</span>
                        <span>{junction.signalCycleSec} sec</span>
                      </div>
                      <div className="map-popup-row">
                        <span>Current Wait Time:</span>
                        <strong style={{ color: junction.currentWaitSec > 60 ? '#ef4444' : '#10b981' }}>
                          {junction.currentWaitSec} sec
                        </strong>
                      </div>
                      <div className="map-popup-row">
                        <span>Operating Phase:</span>
                        <span>{junction.status.replace('_', ' ').toUpperCase()}</span>
                      </div>
                    </div>
                  </Popup>
                </Marker>
              ))}

            {/* 3. Hospital Markers */}
            {showHospitals &&
              hospitals.map((hospital) => (
                <Marker
                  key={hospital.id}
                  position={hospital.coordinates}
                  icon={createHospitalIcon()}
                  eventHandlers={{
                    click: () => setSelectedEntity({ type: 'hospital', data: hospital }),
                  }}
                >
                  <Popup className="custom-leaflet-popup">
                    <div className="map-popup-card">
                      <div className="map-popup-title" style={{ color: '#ef4444' }}>
                        🏥 {hospital.name}
                      </div>
                      <div className="map-popup-row">
                        <span>Zone:</span>
                        <span>{hospital.area}</span>
                      </div>
                      <div className="map-popup-row">
                        <span>Emergency Ambulances:</span>
                        <span>{hospital.emergencyUnits} available</span>
                      </div>
                      <div className="map-popup-row">
                        <span>Trauma Center:</span>
                        <span>{hospital.traumaCenter ? 'Yes (Level 1)' : 'Standard'}</span>
                      </div>
                      <div className="map-popup-row">
                        <span>Access Status:</span>
                        <strong style={{ color: hospital.accessStatus === 'clear' ? '#10b981' : '#f59e0b' }}>
                          {hospital.accessStatus.replace('_', ' ').toUpperCase()}
                        </strong>
                      </div>
                    </div>
                  </Popup>
                </Marker>
              ))}

            {/* 4. Incident Markers */}
            {showIncidents &&
              incidents.map((incident) => (
                <Marker
                  key={incident.id}
                  position={incident.coordinates}
                  icon={createIncidentIcon(incident.severity)}
                  eventHandlers={{
                    click: () => setSelectedEntity({ type: 'incident', data: incident }),
                  }}
                >
                  <Popup className="custom-leaflet-popup">
                    <div className="map-popup-card">
                      <div className="map-popup-title" style={{ color: '#ef4444' }}>
                        ⚠️ {incident.type}
                      </div>
                      <div className="map-popup-row">
                        <span>Incident ID:</span>
                        <span className="font-mono">{incident.id}</span>
                      </div>
                      <div className="map-popup-row">
                        <span>Location:</span>
                        <span>{incident.location}</span>
                      </div>
                      <div className="map-popup-row">
                        <span>Severity:</span>
                        <strong style={{ color: incident.severity === 'critical' ? '#ef4444' : '#f59e0b' }}>
                          {incident.severity.toUpperCase()}
                        </strong>
                      </div>
                      <div className="map-popup-row">
                        <span>Clearance ETA:</span>
                        <span>{incident.estimatedClearance}</span>
                      </div>
                    </div>
                  </Popup>
                </Marker>
              ))}
          </MapContainer>

          {/* Floating Map Legend Overlay */}
          <div className="floating-map-legend">
            <div className="floating-map-legend__title">Map Legend</div>
            <div className="legend-row">
              <span className="legend-line legend-line--open" />
              <span>Open Corridor (Free Flow)</span>
            </div>
            <div className="legend-row">
              <span className="legend-line legend-line--congested" />
              <span>Congested Corridor</span>
            </div>
            <div className="legend-row">
              <span className="legend-line legend-line--closed" />
              <span>Closed Road / Diversion</span>
            </div>
            <div className="legend-row">
              <span className="legend-marker-box legend-marker-box--hosp">+</span>
              <span>Emergency Hospital</span>
            </div>
            <div className="legend-row">
              <span className="legend-marker-box legend-marker-box--junc" />
              <span>Traffic Signal Junction</span>
            </div>
            <div className="legend-row">
              <span className="legend-marker-box legend-marker-box--inc">⚠️</span>
              <span>Active Incident</span>
            </div>
          </div>
        </div>

        {/* Selected Entity Details Side Panel */}
        <div className="map-details-sidebar">
          {selectedEntity ? (
            <div className="map-entity-card">
              <div className="map-entity-card__header">
                <span className="map-entity-tag font-mono">
                  {selectedEntity.type.toUpperCase()} TELEMETRY
                </span>
                <button
                  className="map-entity-close"
                  onClick={() => setSelectedEntity(null)}
                  title="Close inspector"
                >
                  ✕
                </button>
              </div>

              {selectedEntity.type === 'road' && (
                <div className="entity-content">
                  <h3 className="entity-title">{selectedEntity.data.name}</h3>
                  <div className="entity-status-badge-row">
                    <StatusBadge
                      label={selectedEntity.data.status.toUpperCase()}
                      variant={
                        selectedEntity.data.status === 'open'
                          ? 'success'
                          : selectedEntity.data.status === 'congested'
                          ? 'warning'
                          : 'danger'
                      }
                    />
                    <span className="entity-id-tag font-mono">{selectedEntity.data.id}</span>
                  </div>

                  <div className="entity-meta-grid">
                    <div className="entity-meta-item">
                      <span className="meta-label">Length</span>
                      <span className="meta-val">{selectedEntity.data.distanceKm} km</span>
                    </div>
                    <div className="entity-meta-item">
                      <span className="meta-label">Speed</span>
                      <span className="meta-val font-mono">{selectedEntity.data.currentSpeed} km/h</span>
                    </div>
                    <div className="entity-meta-item">
                      <span className="meta-label">Speed Limit</span>
                      <span className="meta-val font-mono">{selectedEntity.data.speedLimit} km/h</span>
                    </div>
                    <div className="entity-meta-item">
                      <span className="meta-label">Congestion</span>
                      <span className="meta-val font-mono" style={{ color: selectedEntity.data.density > 0.7 ? '#ef4444' : '#10b981' }}>
                        {selectedEntity.data.congestionLevel}
                      </span>
                    </div>
                    <div className="entity-meta-item">
                      <span className="meta-label">Lanes</span>
                      <span className="meta-val">{selectedEntity.data.lanes} Dual Lanes</span>
                    </div>
                    <div className="entity-meta-item">
                      <span className="meta-label">Est. Vehicles</span>
                      <span className="meta-val font-mono">{selectedEntity.data.vehicleCount?.toLocaleString()}</span>
                    </div>
                  </div>

                  <div className="entity-recommendation">
                    <div className="recommendation-title">Dynamic Route Advice:</div>
                    <p>
                      {selectedEntity.data.status === 'closed'
                        ? 'Corridor closed. Active emergency diversion routing active via Outer Ring Road.'
                        : selectedEntity.data.status === 'congested'
                        ? 'High vehicle density detected. Adaptive signal green-time extended by +25s at adjacent junctions.'
                        : 'Traffic moving smoothly within normal design speed thresholds.'}
                    </p>
                  </div>
                </div>
              )}

              {selectedEntity.type === 'incident' && (
                <div className="entity-content">
                  <h3 className="entity-title" style={{ color: '#ef4444' }}>
                    {selectedEntity.data.type}
                  </h3>
                  <div className="entity-status-badge-row">
                    <StatusBadge
                      label={selectedEntity.data.severity.toUpperCase()}
                      variant={selectedEntity.data.severity === 'critical' ? 'danger' : 'warning'}
                    />
                    <span className="entity-id-tag font-mono">{selectedEntity.data.id}</span>
                  </div>

                  <div className="entity-meta-grid">
                    <div className="entity-meta-item entity-meta-item--full">
                      <span className="meta-label">Location</span>
                      <span className="meta-val">{selectedEntity.data.location}</span>
                    </div>
                    <div className="entity-meta-item">
                      <span className="meta-label">Reported</span>
                      <span className="meta-val">{selectedEntity.data.timestamp}</span>
                    </div>
                    <div className="entity-meta-item">
                      <span className="meta-label">Est. Clearance</span>
                      <span className="meta-val">{selectedEntity.data.estimatedClearance}</span>
                    </div>
                  </div>

                  <div className="entity-recommendation">
                    <div className="recommendation-title">Response Dispatch:</div>
                    <p>{selectedEntity.data.responseDispatched}</p>
                  </div>
                </div>
              )}

              {selectedEntity.type === 'hospital' && (
                <div className="entity-content">
                  <h3 className="entity-title" style={{ color: '#ef4444' }}>
                    {selectedEntity.data.name}
                  </h3>
                  <div className="entity-status-badge-row">
                    <StatusBadge label="EMERGENCY READY" variant="success" />
                    <span className="entity-id-tag font-mono">{selectedEntity.data.id}</span>
                  </div>

                  <div className="entity-meta-grid">
                    <div className="entity-meta-item entity-meta-item--full">
                      <span className="meta-label">Zone</span>
                      <span className="meta-val">{selectedEntity.data.area}</span>
                    </div>
                    <div className="entity-meta-item">
                      <span className="meta-label">Fleet</span>
                      <span className="meta-val">{selectedEntity.data.emergencyUnits} Ambulances</span>
                    </div>
                    <div className="entity-meta-item">
                      <span className="meta-label">Trauma Unit</span>
                      <span className="meta-val">{selectedEntity.data.traumaCenter ? 'Yes (Level 1)' : 'Standard'}</span>
                    </div>
                  </div>
                </div>
              )}

              {selectedEntity.type === 'junction' && (
                <div className="entity-content">
                  <h3 className="entity-title" style={{ color: '#00d4ff' }}>
                    {selectedEntity.data.name}
                  </h3>
                  <div className="entity-status-badge-row">
                    <StatusBadge label="ACTIVE SIGNAL" variant="info" />
                    <span className="entity-id-tag font-mono">{selectedEntity.data.id}</span>
                  </div>

                  <div className="entity-meta-grid">
                    <div className="entity-meta-item">
                      <span className="meta-label">Cycle Time</span>
                      <span className="meta-val font-mono">{selectedEntity.data.signalCycleSec}s</span>
                    </div>
                    <div className="entity-meta-item">
                      <span className="meta-label">Queue Delay</span>
                      <span className="meta-val font-mono">{selectedEntity.data.currentWaitSec}s</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="map-empty-selection">
              <Navigation size={32} className="map-empty-icon" />
              <h4>GIS Corridor Inspector</h4>
              <p>
                Click on any road corridor, signal junction, hospital, or incident icon on the map to inspect live parameters and dispatch telemetry.
              </p>
              <div className="quick-stats-box">
                <div className="quick-stat-row">
                  <span>Monitored Corridors:</span>
                  <strong>{roads.length}</strong>
                </div>
                <div className="quick-stat-row">
                  <span>Signal Junctions:</span>
                  <strong>{junctions.length}</strong>
                </div>
                <div className="quick-stat-row">
                  <span>Trauma Hospitals:</span>
                  <strong>{hospitals.length}</strong>
                </div>
                <div className="quick-stat-row">
                  <span>Active Disturbances:</span>
                  <strong style={{ color: '#ef4444' }}>{incidents.length}</strong>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </PageContainer>
  );
}

export default InteractiveMapPage;
