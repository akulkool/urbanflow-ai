import apiClient from './apiClient';
import { MOCK_DASHBOARD_DATA, BENGALURU_INCIDENTS, BENGALURU_ROADS } from '../utils/mockTrafficData';

/**
 * Dashboard data service.
 * Fetches data for the Overview page from the backend API.
 * Gracefully provides Bengaluru-inspired demonstration data when backend is offline.
 */
const dashboardService = {
  /**
   * Fetch combined dashboard summary.
   * Endpoints probed: GET /analytics/dashboard or GET /dashboard
   */
  getDashboardData: async () => {
    try {
      const response = await apiClient.get('/analytics/dashboard');
      return {
        data: response.data,
        isLive: true,
        error: null,
      };
    } catch (err) {
      try {
        const fallback = await apiClient.get('/dashboard');
        return {
          data: fallback.data,
          isLive: true,
          error: null,
        };
      } catch (innerErr) {
        return {
          data: {
            ...MOCK_DASHBOARD_DATA,
            incidents: BENGALURU_INCIDENTS,
            roads: BENGALURU_ROADS,
          },
          isLive: false,
          error: innerErr.message || 'Backend dashboard API unreachable',
          missingEndpoint: 'GET /api/analytics/dashboard or GET /api/dashboard',
        };
      }
    }
  },

  /**
   * Fetch vehicle distribution breakdown.
   */
  getVehicleDistribution: async () => {
    try {
      const response = await apiClient.get('/analytics/vehicle-distribution');
      return { data: response.data, isLive: true };
    } catch (err) {
      return { data: MOCK_DASHBOARD_DATA.vehicleDistribution, isLive: false };
    }
  },

  /**
   * Fetch congestion trends over time.
   */
  getCongestionTrends: async () => {
    try {
      const response = await apiClient.get('/analytics/congestion-trends');
      return { data: response.data, isLive: true };
    } catch (err) {
      return { data: MOCK_DASHBOARD_DATA.congestionTrends, isLive: false };
    }
  },
};

export default dashboardService;
