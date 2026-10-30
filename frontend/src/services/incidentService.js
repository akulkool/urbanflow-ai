import apiClient from './apiClient';
import { BENGALURU_INCIDENTS } from '../utils/mockTrafficData';

// Local in-memory store for session persistence when backend is offline
let localIncidents = [...BENGALURU_INCIDENTS];

/**
 * Incident Management service adapter.
 * Handles CRUD operations, status state transitions, and synchronizes
 * with backend endpoints (GET/POST/PATCH/DELETE /api/incidents).
 */
const incidentService = {
  /**
   * Fetch all incidents.
   * Endpoint: GET /incidents or GET /api/incidents
   */
  getIncidents: async () => {
    try {
      const response = await apiClient.get('/incidents');
      const data = Array.isArray(response.data) ? response.data : response.data.incidents || [];
      localIncidents = data;
      return {
        data,
        isLive: true,
        error: null,
      };
    } catch (err) {
      return {
        data: [...localIncidents],
        isLive: false,
        error: err.message || 'Backend incident service unreachable',
        missingEndpoint: 'GET /api/incidents',
      };
    }
  },

  /**
   * Create a new traffic incident.
   * Endpoint: POST /incidents
   * Request Schema: { type, location, roadId, severity, description, coordinates? }
   */
  createIncident: async (incidentData) => {
    try {
      const response = await apiClient.post('/incidents', incidentData);
      return {
        data: response.data,
        isLive: true,
        error: null,
      };
    } catch (err) {
      // Offline fallback: create in local session state
      const newIncident = {
        id: `INC-BLR-${String(localIncidents.length + 1).padStart(2, '0')}`,
        type: incidentData.type,
        roadId: incidentData.roadId,
        location: incidentData.location,
        severity: incidentData.severity || 'medium',
        status: 'pending_confirmation',
        timestamp: 'Just now',
        coordinates: incidentData.coordinates || [12.9716, 77.5946],
        description: incidentData.description || 'Reported incident requiring dispatch review.',
        affectedRoads: [incidentData.roadId],
        estimatedClearance: 'Pending evaluation',
        responseDispatched: 'Awaiting operator confirmation',
      };

      localIncidents.unshift(newIncident);

      return {
        data: newIncident,
        isLive: false,
        error: err.response?.data?.detail || err.message || 'Backend API offline',
        missingEndpoint: 'POST /api/incidents',
        notice: 'Backend API offline. Incident recorded in local operator session.',
      };
    }
  },

  /**
   * Confirm a pending incident.
   * Transitions status: pending_confirmation -> active
   * Endpoint: PATCH /incidents/{id}
   */
  confirmIncident: async (id) => {
    try {
      const response = await apiClient.patch(`/incidents/${id}`, { status: 'active' });
      return { data: response.data, isLive: true };
    } catch (err) {
      localIncidents = localIncidents.map((inc) =>
        inc.id === id ? { ...inc, status: 'active', responseDispatched: 'Emergency Patrol Dispatched' } : inc
      );
      return {
        data: localIncidents.find((i) => i.id === id),
        isLive: false,
        missingEndpoint: `PATCH /api/incidents/${id}`,
        notice: 'Status updated to Active in local session.',
      };
    }
  },

  /**
   * Update incident details.
   * Endpoint: PATCH /incidents/{id}
   */
  updateIncident: async (id, updateData) => {
    try {
      const response = await apiClient.patch(`/incidents/${id}`, updateData);
      return { data: response.data, isLive: true };
    } catch (err) {
      localIncidents = localIncidents.map((inc) =>
        inc.id === id ? { ...inc, ...updateData } : inc
      );
      return {
        data: localIncidents.find((i) => i.id === id),
        isLive: false,
        missingEndpoint: `PATCH /api/incidents/${id}`,
      };
    }
  },

  /**
   * Resolve an incident.
   * Transitions status: active -> resolved
   * Endpoint: PATCH /incidents/{id}
   */
  resolveIncident: async (id) => {
    try {
      const response = await apiClient.patch(`/incidents/${id}`, {
        status: 'resolved',
        estimatedClearance: 'Resolved',
      });
      return { data: response.data, isLive: true };
    } catch (err) {
      localIncidents = localIncidents.map((inc) =>
        inc.id === id ? { ...inc, status: 'resolved', estimatedClearance: 'Resolved' } : inc
      );
      return {
        data: localIncidents.find((i) => i.id === id),
        isLive: false,
        missingEndpoint: `PATCH /api/incidents/${id}`,
        notice: 'Status marked as Resolved in local session.',
      };
    }
  },

  /**
   * Dismiss an incident.
   * Transitions status: -> dismissed
   * Endpoint: DELETE /incidents/{id} or PATCH /incidents/{id}
   */
  dismissIncident: async (id) => {
    try {
      const response = await apiClient.patch(`/incidents/${id}`, { status: 'dismissed' });
      return { data: response.data, isLive: true };
    } catch (err) {
      localIncidents = localIncidents.map((inc) =>
        inc.id === id ? { ...inc, status: 'dismissed', estimatedClearance: 'Dismissed / False Alarm' } : inc
      );
      return {
        data: localIncidents.find((i) => i.id === id),
        isLive: false,
        missingEndpoint: `PATCH /api/incidents/${id} (status: dismissed)`,
        notice: 'Incident marked as Dismissed in local session.',
      };
    }
  },
};

export default incidentService;
