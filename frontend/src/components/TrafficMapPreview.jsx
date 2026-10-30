import { Link } from 'react-router-dom';
import { MapContainer, TileLayer, Polyline, Marker, Popup } from 'react-leaflet';
import { Map as MapIcon, ExternalLink, ShieldAlert } from 'lucide-react';
import { BENGALURU_CENTER, DEFAULT_ZOOM } from '../utils/mockTrafficData';
import { createIncidentIcon } from '../utils/leafletIcons';

const ROAD_COLORS = {
  open: '#10b981',
  congested: '#f59e0b',
  closed: '#ef4444',
};

function TrafficMapPreview({ roads = [], incidents = [] }) {
  return (
    <div className="map-preview-card">
      <div className="map-preview-card__header">
        <div className="map-preview-card__title-group">
          <div className="map-preview-card__icon-wrap">
            <MapIcon size={18} />
          </div>
          <div>
            <h3 className="map-preview-card__title">Live Traffic Corridor Preview</h3>
            <p className="map-preview-card__subtitle">
              Bengaluru arterial road network condition preview
            </p>
          </div>
        </div>

        <Link to="/map" className="map-preview-card__link">
          <span>Open Interactive Map</span>
          <ExternalLink size={14} />
        </Link>
      </div>

      <div className="map-preview-card__body">
        <div className="map-preview-container" style={{ height: 340, borderRadius: 8, overflow: 'hidden' }}>
          <MapContainer
            center={BENGALURU_CENTER}
            zoom={DEFAULT_ZOOM}
            scrollWheelZoom={false}
            style={{ width: '100%', height: '100%' }}
          >
            <TileLayer
              attribution='&copy; <a href="https://carto.com/">CARTO</a>'
              url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
            />

            {/* Road Polylines */}
            {roads.map((road) => (
              <Polyline
                key={road.id}
                positions={road.coordinates}
                pathOptions={{
                  color: ROAD_COLORS[road.status] || '#3b82f6',
                  weight: road.status === 'closed' ? 5 : 4,
                  opacity: 0.85,
                  dashArray: road.status === 'closed' ? '6, 6' : null,
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
                      <span>Speed:</span>
                      <span>{road.currentSpeed} km/h</span>
                    </div>
                    <div className="map-popup-row">
                      <span>Congestion:</span>
                      <span>{road.congestionLevel}</span>
                    </div>
                  </div>
                </Popup>
              </Polyline>
            ))}

            {/* Active Incident Pins */}
            {incidents.slice(0, 5).map((incident) => (
              <Marker
                key={incident.id}
                position={incident.coordinates}
                icon={createIncidentIcon(incident.severity)}
              >
                <Popup className="custom-leaflet-popup">
                  <div className="map-popup-card">
                    <div className="map-popup-title" style={{ color: '#ef4444' }}>
                      ⚠️ {incident.type}
                    </div>
                    <div className="map-popup-row">
                      <span>Location:</span>
                      <span>{incident.location}</span>
                    </div>
                    <div className="map-popup-row">
                      <span>Severity:</span>
                      <strong>{incident.severity.toUpperCase()}</strong>
                    </div>
                  </div>
                </Popup>
              </Marker>
            ))}
          </MapContainer>
        </div>

        <div className="map-preview-legend">
          <div className="legend-item">
            <span className="legend-color-line legend-color-line--green" />
            <span>Open (Free Flow)</span>
          </div>
          <div className="legend-item">
            <span className="legend-color-line legend-color-line--orange" />
            <span>Congested</span>
          </div>
          <div className="legend-item">
            <span className="legend-color-line legend-color-line--red" />
            <span>Closed / Blocked</span>
          </div>
          <div className="legend-item">
            <span className="legend-marker-dot">⚠️</span>
            <span>Active Incident</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default TrafficMapPreview;

