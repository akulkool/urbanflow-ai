import apiClient from './apiClient';
import { BENGALURU_ROADS, BENGALURU_JUNCTIONS, BENGALURU_HOSPITALS } from '../utils/mockTrafficData';

/**
 * Traffic service for road conditions, junctions, and road geography.
 * Integrates with actual backend endpoints when available, and provides
 * clearly labeled demonstration data when the backend is offline.
 */
const trafficService = {
  /**
   * Fetch road network segments and conditions.
   * Endpoint: GET /roads or GET /traffic/roads
   */
  getRoads: async () => {
    try {
      const response = await apiClient.get('/traffic/roads');
      return {
        data: response.data,
        isLive: true,
        error: null,
      };
    } catch (err) {
      // Secondary attempt at /roads
      try {
        const fallback = await apiClient.get('/roads');
        return {
          data: fallback.data,
          isLive: true,
          error: null,
        };
      } catch (innerErr) {
        return {
          data: BENGALURU_ROADS,
          isLive: false,
          error: innerErr.message || 'Backend roads API unreachable',
          missingEndpoint: 'GET /api/traffic/roads or GET /api/roads',
        };
      }
    }
  },

  /**
   * Fetch junction coordinates and signal status.
   * Endpoint: GET /traffic/junctions or GET /junctions
   */
  getJunctions: async () => {
    try {
      const response = await apiClient.get('/traffic/junctions');
      return {
        data: response.data,
        isLive: true,
        error: null,
      };
    } catch (err) {
      return {
        data: BENGALURU_JUNCTIONS,
        isLive: false,
        error: err.message || 'Backend junctions API unreachable',
        missingEndpoint: 'GET /api/traffic/junctions',
      };
    }
  },

  /**
   * Fetch emergency medical centers / hospitals.
   * Endpoint: GET /routing/hospitals or GET /hospitals
   */
  getHospitals: async () => {
    try {
      const response = await apiClient.get('/routing/hospitals');
      return {
        data: response.data,
        isLive: true,
        error: null,
      };
    } catch (err) {
      return {
        data: BENGALURU_HOSPITALS,
        isLive: false,
        error: err.message || 'Backend hospitals API unreachable',
        missingEndpoint: 'GET /api/routing/hospitals',
      };
    }
  },
};

export default trafficService;

