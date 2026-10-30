import { useState, useMemo } from 'react';
import { AlertTriangle, Search, Filter, ShieldAlert } from 'lucide-react';
import StatusBadge from './StatusBadge';
import EmptyState from './EmptyState';

function RecentIncidents({ incidents = [] }) {
  const [searchTerm, setSearchTerm] = useState('');
  const [severityFilter, setSeverityFilter] = useState('all');

  const filteredIncidents = useMemo(() => {
    return incidents.filter((item) => {
      const matchesSearch =
        item.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
        item.type.toLowerCase().includes(searchTerm.toLowerCase()) ||
        item.location.toLowerCase().includes(searchTerm.toLowerCase());
      const matchesSeverity =
        severityFilter === 'all' || item.severity.toLowerCase() === severityFilter.toLowerCase();
      return matchesSearch && matchesSeverity;
    });
  }, [incidents, searchTerm, severityFilter]);

  const getSeverityBadgeVariant = (severity) => {
    switch (severity.toLowerCase()) {
      case 'critical':
        return 'danger';
      case 'high':
        return 'warning';
      case 'medium':
        return 'warning';
      case 'low':
        return 'info';
      default:
        return 'neutral';
    }
  };

  const getStatusBadgeVariant = (status) => {
    switch (status.toLowerCase()) {
      case 'active':
        return 'danger';
      case 'investigating':
      case 'monitoring':
        return 'warning';
      case 'cleared':
      case 'resolved':
        return 'success';
      default:
        return 'neutral';
    }
  };

  return (
    <div className="incident-table-card">
      <div className="incident-table-card__header">
        <div className="incident-table-card__title-group">
          <div className="incident-table-card__icon-wrap">
            <AlertTriangle size={18} />
          </div>
          <div>
            <h3 className="incident-table-card__title">Recent Incident Activity</h3>
            <p className="incident-table-card__subtitle">
              Live traffic disturbances, collision reports, and emergency road work
            </p>
          </div>
        </div>

        <div className="incident-table-card__controls">
          <div className="incident-search">
            <Search size={14} className="incident-search__icon" />
            <input
              type="text"
              placeholder="Search ID, type, location…"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="incident-search__input"
            />
          </div>

          <div className="incident-filter">
            <Filter size={14} className="incident-filter__icon" />
            <select
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value)}
              className="incident-filter__select"
            >
              <option value="all">All Severities</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>
        </div>
      </div>

      <div className="incident-table-wrapper">
        {filteredIncidents.length === 0 ? (
          <EmptyState
            title="No Incidents Match Filters"
            message="Try clearing your search query or choosing another severity level."
            icon={ShieldAlert}
          />
        ) : (
          <table className="incident-table">
            <thead>
              <tr>
                <th>Incident ID</th>
                <th>Incident Type</th>
                <th>Location</th>
                <th>Severity</th>
                <th>Status</th>
                <th>Reported</th>
              </tr>
            </thead>
            <tbody>
              {filteredIncidents.map((incident) => (
                <tr key={incident.id}>
                  <td>
                    <span className="incident-id font-mono">{incident.id}</span>
                  </td>
                  <td>
                    <span className="incident-type">{incident.type}</span>
                  </td>
                  <td>
                    <span className="incident-location">{incident.location}</span>
                  </td>
                  <td>
                    <StatusBadge
                      label={incident.severity.toUpperCase()}
                      variant={getSeverityBadgeVariant(incident.severity)}
                    />
                  </td>
                  <td>
                    <StatusBadge
                      label={incident.status.charAt(0).toUpperCase() + incident.status.slice(1)}
                      variant={getStatusBadgeVariant(incident.status)}
                    />
                  </td>
                  <td>
                    <span className="incident-time">{incident.timestamp}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export default RecentIncidents;

