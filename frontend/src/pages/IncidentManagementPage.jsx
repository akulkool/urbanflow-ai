import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  Polyline,
} from 'react-leaflet';
import {
  AlertTriangle,
  PlusCircle,
  Search,
  Filter,
  CheckCircle,
  XCircle,
  AlertOctagon,
  Clock,
  ShieldAlert,
  Flame,
  Radio,
  RefreshCw,
  Edit,
  Eye,
  Check,
  X,
  FileText,
} from 'lucide-react';
import {
  PageContainer,
  StatCard,
  StatusBadge,
  LoadingState,
  ErrorState,
  EmptyState,
} from '../components';
import { incidentService, trafficService } from '../services';
import { useConnection } from '../context';
import {
  BENGALURU_CENTER,
  DEFAULT_ZOOM,
  BENGALURU_ROADS,
} from '../utils/mockTrafficData';
import { createIncidentIcon } from '../utils/leafletIcons';

const INCIDENT_TYPES = [
  'Road accident',
  'Road closure',
  'Construction',
  'Waterlogging',
  'Traffic obstruction',
  'Other',
];

const SEVERITIES = ['low', 'medium', 'high', 'critical'];

function IncidentManagementPage() {
  const { isConnected } = useConnection();
  const [incidents, setIncidents] = useState([]);
  const [roads, setRoads] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Filters
  const [searchTerm, setSearchTerm] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [severityFilter, setSeverityFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');

  // Modals & Forms
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isDismissModalOpen, setIsDismissModalOpen] = useState(false);
  const [selectedIncident, setSelectedIncident] = useState(null);
  const [actionNotification, setActionNotification] = useState(null);

  // Form State for Create
  const [newIncident, setNewIncident] = useState({
    type: 'Road accident',
    roadId: 'RD-01',
    location: '',
    severity: 'high',
    description: '',
  });

  // Load Incidents
  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [incRes, roadRes] = await Promise.all([
        incidentService.getIncidents(),
        trafficService.getRoads(),
      ]);
      setIncidents(incRes.data || []);
      setRoads(roadRes.data || BENGALURU_ROADS);
    } catch (err) {
      setError(err.message || 'Failed to fetch incident dataset.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Handle Create Incident
  const handleCreateSubmit = async (e) => {
    e.preventDefault();
    if (!newIncident.location.trim()) {
      alert('Please specify the incident location name.');
      return;
    }

    const matchedRoad = roads.find((r) => r.id === newIncident.roadId);
    const centerCoord = matchedRoad?.coordinates[1] || [12.9716, 77.5946];

    const payload = {
      ...newIncident,
      coordinates: centerCoord,
    };

    const res = await incidentService.createIncident(payload);
    if (res.data) {
      setIncidents((prev) => [res.data, ...prev]);
      setIsCreateModalOpen(false);
      setNewIncident({
        type: 'Road accident',
        roadId: roads[0]?.id || 'RD-01',
        location: '',
        severity: 'high',
        description: '',
      });
      showNotification(res.notice || 'Incident successfully logged.');
    }
  };

  // Handle Confirm Incident (pending -> active)
  const handleConfirm = async (incident) => {
    const res = await incidentService.confirmIncident(incident.id);
    if (res.data) {
      setIncidents((prev) =>
        prev.map((i) => (i.id === incident.id ? { ...i, status: 'active', responseDispatched: 'Emergency Patrol Dispatched' } : i))
      );
      showNotification(`Incident ${incident.id} confirmed and marked as ACTIVE.`);
    }
  };

  // Handle Resolve Incident
  const handleResolve = async (incident) => {
    const res = await incidentService.resolveIncident(incident.id);
    if (res.data) {
      setIncidents((prev) =>
        prev.map((i) => (i.id === incident.id ? { ...i, status: 'resolved', estimatedClearance: 'Resolved' } : i))
      );
      showNotification(`Incident ${incident.id} marked as RESOLVED.`);
    }
  };

  // Handle Dismiss Incident
  const handleDismissConfirm = async () => {
    if (!selectedIncident) return;
    const res = await incidentService.dismissIncident(selectedIncident.id);
    if (res.data) {
      setIncidents((prev) =>
        prev.map((i) => (i.id === selectedIncident.id ? { ...i, status: 'dismissed' } : i))
      );
      setIsDismissModalOpen(false);
      setSelectedIncident(null);
      showNotification(`Incident ${selectedIncident.id} DISMISSED.`);
    }
  };

  const showNotification = (msg) => {
    setActionNotification(msg);
    setTimeout(() => setActionNotification(null), 4000);
  };

  // KPI Calculations
  const stats = useMemo(() => {
    const total = incidents.length;
    const active = incidents.filter((i) => i.status === 'active').length;
    const critical = incidents.filter((i) => i.severity === 'critical' && i.status !== 'resolved' && i.status !== 'dismissed').length;
    const resolved = incidents.filter((i) => i.status === 'resolved').length;
    const pending = incidents.filter((i) => i.status === 'pending_confirmation').length;
    return { total, active, critical, resolved, pending };
  }, [incidents]);

  // Filtered Table Records
  const filteredIncidents = useMemo(() => {
    return incidents.filter((inc) => {
      const matchSearch =
        inc.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
        inc.location.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (inc.roadId && inc.roadId.toLowerCase().includes(searchTerm.toLowerCase())) ||
        (inc.description && inc.description.toLowerCase().includes(searchTerm.toLowerCase()));

      const matchType = typeFilter === 'all' || inc.type.toLowerCase() === typeFilter.toLowerCase();
      const matchSeverity = severityFilter === 'all' || inc.severity.toLowerCase() === severityFilter.toLowerCase();
      const matchStatus = statusFilter === 'all' || inc.status.toLowerCase() === statusFilter.toLowerCase();

      return matchSearch && matchType && matchSeverity && matchStatus;
    });
  }, [incidents, searchTerm, typeFilter, severityFilter, statusFilter]);

  if (loading) {
    return (
      <PageContainer>
        <LoadingState message="Synchronizing Incident Operations Control Table…" />
      </PageContainer>
    );
  }

  if (error) {
    return (
      <PageContainer>
        <ErrorState title="Incident Database Unavailable" message={error} onRetry={loadData} />
      </PageContainer>
    );
  }

  return (
    <PageContainer className="incident-page">
      {/* Module Header */}
      <div className="section-header">
        <div className="section-header__left">
          <div className="section-header__icon" style={{ backgroundColor: 'rgba(239, 68, 68, 0.15)', color: '#ef4444' }}>
            <AlertTriangle size={20} />
          </div>
          <div className="section-header__text">
            <h2>Incident Management &amp; Dispatch Control</h2>
            <p>
              Log, confirm, track, and clear road closures, traffic bottlenecks, and emergency collisions
            </p>
          </div>
        </div>

        <div className="section-header__actions">
          <button className="dashboard-btn dashboard-btn--primary" onClick={() => setIsCreateModalOpen(true)}>
            <PlusCircle size={15} />
            <span>Log New Incident</span>
          </button>
        </div>
      </div>

      {/* Action Notification Banner */}
      {actionNotification && (
        <div className="action-notification-toast">
          <CheckCircle size={16} />
          <span>{actionNotification}</span>
        </div>
      )}

      {/* SECTION A: INCIDENT OVERVIEW (5 KPI CARDS) */}
      <div className="incident-kpi-grid">
        <StatCard
          label="Total Incidents"
          value={stats.total}
          description="Cumulative reported road events in current log"
          icon={AlertTriangle}
          variant="accent"
        />
        <StatCard
          label="Active Incidents"
          value={stats.active}
          description="Live corridor disruptions requiring patrol response"
          icon={Flame}
          variant="danger"
        />
        <StatCard
          label="Critical Incidents"
          value={stats.critical}
          description="High impact blockages requiring diversions"
          icon={AlertOctagon}
          variant="danger"
        />
        <StatCard
          label="Resolved Incidents"
          value={stats.resolved}
          description="Successfully cleared hazards with normal flow restored"
          icon={CheckCircle}
          variant="success"
        />
        <StatCard
          label="Pending Confirmation"
          value={stats.pending}
          description="Citizen reports awaiting operator validation"
          icon={Clock}
          variant="warning"
        />
      </div>

      {/* Split Grid: Interactive Incident Map + Filters & Table */}
      <div className="incident-workspace-grid">
        {/* Interactive Map with Incident Markers */}
        <div className="incident-map-card">
          <div className="incident-map-card__header">
            <div className="incident-map-card__title">
              <Radio size={14} className="pulse-icon" />
              <span>Spatial Incident Tracker (Bengaluru Grid)</span>
            </div>
            <span className="incident-map-badge font-mono">
              {incidents.filter((i) => i.status === 'active' || i.status === 'pending_confirmation').length} Active Pins
            </span>
          </div>

          <div style={{ height: 320, borderRadius: '0 0 8px 8px', overflow: 'hidden' }}>
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

              {/* Road lines */}
              {roads.map((road) => (
                <Polyline
                  key={road.id}
                  positions={road.coordinates}
                  pathOptions={{
                    color: road.status === 'closed' ? '#ef4444' : road.status === 'congested' ? '#f59e0b' : '#3b82f6',
                    weight: 3,
                    opacity: 0.6,
                    dashArray: road.status === 'closed' ? '6, 6' : null,
                  }}
                />
              ))}

              {/* Incidents */}
              {incidents
                .filter((inc) => inc.status !== 'dismissed')
                .map((incident) => (
                  <Marker
                    key={incident.id}
                    position={incident.coordinates || [12.9716, 77.5946]}
                    icon={createIncidentIcon(incident.severity)}
                  >
                    <Popup className="custom-leaflet-popup">
                      <div className="map-popup-card">
                        <div className="map-popup-title" style={{ color: '#ef4444' }}>
                          ⚠️ {incident.type}
                        </div>
                        <div className="map-popup-row">
                          <span>ID:</span>
                          <span className="font-mono">{incident.id}</span>
                        </div>
                        <div className="map-popup-row">
                          <span>Road:</span>
                          <span className="font-mono">{incident.roadId}</span>
                        </div>
                        <div className="map-popup-row">
                          <span>Severity:</span>
                          <strong style={{ color: incident.severity === 'critical' ? '#ef4444' : '#f59e0b' }}>
                            {incident.severity.toUpperCase()}
                          </strong>
                        </div>
                        <div className="map-popup-row">
                          <span>Status:</span>
                          <span>{incident.status}</span>
                        </div>
                        <div className="map-popup-row">
                          <span>Clearance:</span>
                          <span>{incident.estimatedClearance}</span>
                        </div>
                      </div>
                    </Popup>
                  </Marker>
                ))}
            </MapContainer>
          </div>
        </div>

        {/* SECTION B, C, D, G: INCIDENT MANAGEMENT TABLE & FILTERS */}
        <div className="incident-table-pane">
          {/* Filter Bar */}
          <div className="incident-filter-bar">
            {/* Search Input */}
            <div className="incident-search-box">
              <Search size={14} className="incident-search-icon" />
              <input
                type="text"
                placeholder="Filter by ID, road, location, description…"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="incident-search-input"
              />
            </div>

            {/* Type Filter */}
            <div className="incident-select-box">
              <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                <option value="all">All Incident Types</option>
                {INCIDENT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>

            {/* Severity Filter */}
            <div className="incident-select-box">
              <select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}>
                <option value="all">All Severities</option>
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </div>

            {/* Status Filter */}
            <div className="incident-select-box">
              <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                <option value="all">All Statuses</option>
                <option value="active">Active</option>
                <option value="pending_confirmation">Pending</option>
                <option value="investigating">Investigating</option>
                <option value="resolved">Resolved</option>
                <option value="dismissed">Dismissed</option>
              </select>
            </div>

            <button
              className="dashboard-btn"
              onClick={() => {
                setSearchTerm('');
                setTypeFilter('all');
                setSeverityFilter('all');
                setStatusFilter('all');
              }}
              title="Reset all filters"
            >
              Reset
            </button>
          </div>

          {/* Table */}
          <div className="incident-main-table-wrap">
            {filteredIncidents.length === 0 ? (
              <EmptyState
                title="No Incidents Found"
                message="No incident records match the active search criteria or filters."
                icon={ShieldAlert}
              />
            ) : (
              <table className="incident-main-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Type</th>
                    <th>Location</th>
                    <th>Road ID</th>
                    <th>Severity</th>
                    <th>Status</th>
                    <th>Logged</th>
                    <th style={{ textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredIncidents.map((incident) => {
                    const isPending = incident.status === 'pending_confirmation';
                    const isActive = incident.status === 'active' || incident.status === 'investigating';
                    const isResolved = incident.status === 'resolved';

                    return (
                      <tr key={incident.id}>
                        <td>
                          <span className="font-mono font-semibold" style={{ color: '#00d4ff' }}>
                            {incident.id}
                          </span>
                        </td>
                        <td>
                          <span className="incident-type-tag">{incident.type}</span>
                        </td>
                        <td>
                          <div className="incident-loc-cell" title={incident.location}>
                            {incident.location}
                          </div>
                        </td>
                        <td>
                          <span className="font-mono text-muted">{incident.roadId || 'N/A'}</span>
                        </td>
                        <td>
                          <StatusBadge
                            label={incident.severity.toUpperCase()}
                            variant={
                              incident.severity === 'critical'
                                ? 'danger'
                                : incident.severity === 'high'
                                ? 'warning'
                                : 'info'
                            }
                          />
                        </td>
                        <td>
                          <StatusBadge
                            label={incident.status.replace('_', ' ').toUpperCase()}
                            variant={
                              isPending
                                ? 'warning'
                                : isActive
                                ? 'danger'
                                : isResolved
                                ? 'success'
                                : 'neutral'
                            }
                          />
                        </td>
                        <td>
                          <span className="text-muted font-mono" style={{ fontSize: 11 }}>
                            {incident.timestamp}
                          </span>
                        </td>
                        <td style={{ textAlign: 'right' }}>
                          <div className="incident-row-actions">
                            {isPending && (
                              <button
                                className="action-btn action-btn--confirm"
                                onClick={() => handleConfirm(incident)}
                                title="Confirm incident"
                              >
                                <Check size={13} />
                                <span>Confirm</span>
                              </button>
                            )}

                            {isActive && (
                              <button
                                className="action-btn action-btn--resolve"
                                onClick={() => handleResolve(incident)}
                                title="Mark resolved"
                              >
                                <CheckCircle size={13} />
                                <span>Resolve</span>
                              </button>
                            )}

                            {incident.status !== 'dismissed' && (
                              <button
                                className="action-btn action-btn--dismiss"
                                onClick={() => {
                                  setSelectedIncident(incident);
                                  setIsDismissModalOpen(true);
                                }}
                                title="Dismiss as false report"
                              >
                                <X size={13} />
                                <span>Dismiss</span>
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      {/* CREATE INCIDENT MODAL (SECTION E) */}
      {isCreateModalOpen && (
        <div className="modal-backdrop">
          <div className="modal-dialog">
            <div className="modal-header">
              <h3>Log New Traffic Incident</h3>
              <button className="modal-close-btn" onClick={() => setIsCreateModalOpen(false)}>
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateSubmit} className="modal-form">
              <div className="form-group">
                <label>Incident Classification</label>
                <select
                  value={newIncident.type}
                  onChange={(e) => setNewIncident({ ...newIncident, type: e.target.value })}
                >
                  {INCIDENT_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label>Corridor Segment</label>
                <select
                  value={newIncident.roadId}
                  onChange={(e) => setNewIncident({ ...newIncident, roadId: e.target.value })}
                >
                  {roads.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.id}: {r.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label>Location Landmark / Description</label>
                <input
                  type="text"
                  placeholder="e.g. Silk Board Ramp near Petrol Pump"
                  value={newIncident.location}
                  onChange={(e) => setNewIncident({ ...newIncident, location: e.target.value })}
                  required
                />
              </div>

              <div className="form-group">
                <label>Severity Level</label>
                <select
                  value={newIncident.severity}
                  onChange={(e) => setNewIncident({ ...newIncident, severity: e.target.value })}
                >
                  {SEVERITIES.map((s) => (
                    <option key={s} value={s}>
                      {s.toUpperCase()}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label>Incident Details / Obstruction Nature</label>
                <textarea
                  rows={3}
                  placeholder="Details of lanes blocked, emergency response required, etc."
                  value={newIncident.description}
                  onChange={(e) => setNewIncident({ ...newIncident, description: e.target.value })}
                />
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="dashboard-btn"
                  onClick={() => setIsCreateModalOpen(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="dashboard-btn dashboard-btn--primary">
                  Publish Incident Record
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* DISMISS CONFIRMATION MODAL */}
      {isDismissModalOpen && selectedIncident && (
        <div className="modal-backdrop">
          <div className="modal-dialog modal-dialog--small">
            <div className="modal-header">
              <h3 style={{ color: '#ef4444' }}>Dismiss Incident {selectedIncident.id}?</h3>
              <button className="modal-close-btn" onClick={() => setIsDismissModalOpen(false)}>
                ✕
              </button>
            </div>
            <div className="modal-body">
              <p>
                Are you sure you want to dismiss <strong>{selectedIncident.type}</strong> at{' '}
                <em>{selectedIncident.location}</em>?
              </p>
              <p className="text-muted" style={{ fontSize: 12, marginTop: 8 }}>
                This marks the incident record as dismissed/false alarm and restores normal corridor routing priority.
              </p>
            </div>
            <div className="modal-footer">
              <button
                className="dashboard-btn"
                onClick={() => setIsDismissModalOpen(false)}
              >
                Cancel
              </button>
              <button
                className="dashboard-btn dashboard-btn--clear"
                onClick={handleDismissConfirm}
              >
                Dismiss Incident
              </button>
            </div>
          </div>
        </div>
      )}
    </PageContainer>
  );
}

export default IncidentManagementPage;
