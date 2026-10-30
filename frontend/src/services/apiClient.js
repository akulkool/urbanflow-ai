import axios from 'axios';

/**
 * Centralized Axios instance for all API calls.
 *
 * The base URL is read from the VITE_API_BASE_URL environment variable.
 * See .env.example for configuration details.
 */
const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api',
  timeout: 15000,
  headers: {
    'Content-Type': 'application/json',
  },
});

/* ---------- Request Interceptor ---------- */
apiClient.interceptors.request.use(
  (config) => {
    // Attach auth tokens or other headers here when needed
    return config;
  },
  (error) => Promise.reject(error),
);

/* ---------- Response Interceptor ---------- */
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    // Centralised error handling (logging, toast notifications, etc.)
    console.error('[API Error]', error?.response?.status, error?.message);
    return Promise.reject(error);
  },
);

export default apiClient;

