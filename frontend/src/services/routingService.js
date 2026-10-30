import apiClient from './apiClient';
import { calculateSmartRoute } from '../utils/routeCalculator';
import { BENGALURU_HOSPITALS, BENGALURU_JUNCTIONS } from '../utils/mockTrafficData';

/**
 * Smart Routing service adapter.
 * Integrates with NetworkX routing backend (POST /api/routes/calculate),
 * with client-side Dijkstra fallback when the backend service is offline.
 */
const routingService = {
  /**
   * Calculate shortest/optimal route between junctions or hospital.
   *
   * @param {object} params
   * @param {string} params.originJunctionId
   * @param {string} params.destinationJunctionId
   * @param {string} [params.hospitalId]
   * @param {boolean} [params.avoidIncidents=true]
   * @param {string} [params.transportMode='emergency']
   */
  calculateRoute: async (params) => {
    const payload = {
      start_junction: params.originJunctionId,
      end_junction: params.destinationJunctionId,
      hospital_id: params.hospitalId || null,
      avoid_incidents: params.avoidIncidents !== false,
      transport_mode: params.transportMode || 'emergency',
    };

    try {
      // Primary contract: POST /routes/calculate
      const response = await apiClient.post('/routes/calculate', payload);
      return {
        data: response.data,
        isLive: true,
        error: null,
      };
    } catch (err) {
      // Secondary attempt: POST /routing/find-route
      try {
        const fallback = await apiClient.post('/routing/find-route', payload);
        return {
          data: fallback.data,
          isLive: true,
          error: null,
        };
      } catch (innerErr) {
        // Run verified client-side graph engine
        const calcResult = calculateSmartRoute({
          originJunctionId: params.originJunctionId,
          destinationJunctionId: params.destinationJunctionId,
          hospitalId: params.hospitalId,
          avoidIncidents: params.avoidIncidents,
          transportMode: params.transportMode,
        });

        return {
          data: calcResult,
          isLive: false,
          error: innerErr.message || 'Routing backend offline',
          missingEndpoint: 'POST /api/routes/calculate (NetworkX Routing Service)',
          notice: 'Routing computed via calibrated Bengaluru graph engine (offline simulation).',
        };
      }
    }
  },

  getJunctions: () => BENGALURU_JUNCTIONS,
  getHospitals: () => BENGALURU_HOSPITALS,
};

export default routingService;

