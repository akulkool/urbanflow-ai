import apiClient from './apiClient';

/**
 * Application health-check service.
 * Verifies backend connectivity via GET /health or GET /api/health.
 */
const healthService = {
  check: async () => {
    try {
      const response = await apiClient.get('/health', { timeout: 4000 });
      return { isConnected: true, data: response.data, error: null };
    } catch (err) {
      return {
        isConnected: false,
        data: null,
        error: err.message || 'Backend unreachable',
      };
    }
  },
};

export default healthService;
