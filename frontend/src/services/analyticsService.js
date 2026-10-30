import apiClient from './apiClient';
import {
  MOCK_DASHBOARD_DATA,
  BENGALURU_ROADS,
  BENGALURU_INCIDENTS,
} from '../utils/mockTrafficData';

/**
 * Traffic Analytics Service Adapter.
 * Integrates with backend analytics endpoints (GET /api/analytics/*)
 * and provides calibrated data aggregation for the Analytics Dashboard.
 */
const analyticsService = {
  /**
   * Fetch vehicle distribution and detection trends.
   */
  getVehicleAnalytics: async (timeRange = 'today', selectedClass = 'all') => {
    try {
      const response = await apiClient.get('/analytics/vehicle-distribution', {
        params: { range: timeRange, vehicle_class: selectedClass },
      });
      return { data: response.data, isLive: true, error: null };
    } catch (err) {
      // Calibrated benchmark dataset
      let vehicles = [
        { name: 'Cars', count: 8420, percentage: 56.5, fill: '#00d4ff' },
        { name: 'Motorcycles', count: 4180, percentage: 28.1, fill: '#3b82f6' },
        { name: 'Buses', count: 1340, percentage: 9.0, fill: '#10b981' },
        { name: 'Trucks', count: 952, percentage: 6.4, fill: '#f59e0b' },
      ];

      if (selectedClass !== 'all') {
        vehicles = vehicles.filter((v) => v.name.toLowerCase() === selectedClass.toLowerCase());
      }

      const totalVehicles = vehicles.reduce((sum, v) => sum + v.count, 0);

      // Hourly detection trend curves
      const detectionTrends = [
        { hour: '06:00', cars: 1800, motorcycles: 950, buses: 320, trucks: 220, total: 3290 },
        { hour: '08:00', cars: 5800, motorcycles: 3100, buses: 890, trucks: 410, total: 10200 },
        { hour: '10:00', cars: 8420, motorcycles: 4180, buses: 1340, trucks: 952, total: 14892 },
        { hour: '12:00', cars: 4900, motorcycles: 2400, buses: 780, trucks: 820, total: 8900 },
        { hour: '14:00', cars: 4200, motorcycles: 2100, buses: 710, trucks: 790, total: 7800 },
        { hour: '16:00', cars: 5900, motorcycles: 3200, buses: 920, trucks: 580, total: 10600 },
        { hour: '18:00', cars: 9200, motorcycles: 4900, buses: 1420, trucks: 880, total: 16400 },
        { hour: '20:00', cars: 6800, motorcycles: 3600, buses: 1100, trucks: 800, total: 12300 },
        { hour: '22:00', cars: 3100, motorcycles: 1400, buses: 450, trucks: 650, total: 5600 },
      ];

      return {
        data: {
          totalVehicles,
          classes: vehicles,
          trends: detectionTrends,
        },
        isLive: false,
        error: err.message || 'Analytics backend unreachable',
        missingEndpoint: 'GET /api/analytics/vehicle-distribution',
      };
    }
  },

  /**
   * Fetch corridor congestion levels and density distributions.
   */
  getTrafficDensityAnalytics: async (roadFilter = 'all') => {
    try {
      const response = await apiClient.get('/analytics/congestion-trends', {
        params: { road: roadFilter },
      });
      return { data: response.data, isLive: true, error: null };
    } catch (err) {
      let roads = BENGALURU_ROADS.map((r) => ({
        id: r.id,
        name: r.name,
        congestion: parseInt(r.congestionLevel, 10) || 30,
        speed: r.currentSpeed,
        speedLimit: r.speedLimit,
        density: r.density,
        status: r.status,
        vehicles: r.vehicleCount,
      }));

      if (roadFilter !== 'all') {
        roads = roads.filter((r) => r.id === roadFilter);
      }

      // Sort by highest congestion descending
      const rankedCongested = [...roads].sort((a, b) => b.congestion - a.congestion);

      // Road condition distribution
      const openCount = roads.filter((r) => r.status === 'open').length;
      const congestedCount = roads.filter((r) => r.status === 'congested').length;
      const closedCount = roads.filter((r) => r.status === 'closed').length;

      const roadConditions = [
        { name: 'Open (Free Flow)', count: openCount, fill: '#10b981' },
        { name: 'Congested (Delay)', count: congestedCount, fill: '#f59e0b' },
        { name: 'Closed / Diversion', count: closedCount, fill: '#ef4444' },
      ];

      // Hourly congestion profile
      const congestionProfile = [
        { time: '06:00', avgCongestion: 22, avgSpeedKmh: 48 },
        { time: '08:00', avgCongestion: 68, avgSpeedKmh: 24 },
        { time: '10:00', avgCongestion: 84, avgSpeedKmh: 16 },
        { time: '12:00', avgCongestion: 52, avgSpeedKmh: 35 },
        { time: '14:00', avgCongestion: 48, avgSpeedKmh: 38 },
        { time: '16:00', avgCongestion: 64, avgSpeedKmh: 26 },
        { time: '18:00', avgCongestion: 89, avgSpeedKmh: 14 },
        { time: '20:00', avgCongestion: 71, avgSpeedKmh: 22 },
        { time: '22:00', avgCongestion: 38, avgSpeedKmh: 44 },
      ];

      return {
        data: {
          corridorRankings: rankedCongested,
          roadConditions,
          congestionProfile,
        },
        isLive: false,
        error: err.message || 'Density analytics backend unreachable',
        missingEndpoint: 'GET /api/analytics/congestion-trends',
      };
    }
  },

  /**
   * Fetch incident breakdowns by severity, type, and resolution status.
   */
  getIncidentAnalytics: async (severityFilter = 'all') => {
    try {
      const response = await apiClient.get('/incidents');
      const incList = Array.isArray(response.data) ? response.data : response.data.incidents || [];
      return { data: incList, isLive: true, error: null };
    } catch (err) {
      let incs = [...BENGALURU_INCIDENTS];

      if (severityFilter !== 'all') {
        incs = incs.filter((i) => i.severity.toLowerCase() === severityFilter.toLowerCase());
      }

      // Severity breakdown
      const severityMap = { critical: 0, high: 0, medium: 0, low: 0 };
      const typeMap = {};
      let activeCount = 0;
      let resolvedCount = 0;

      incs.forEach((i) => {
        const sev = i.severity.toLowerCase();
        if (severityMap[sev] !== undefined) severityMap[sev]++;

        typeMap[i.type] = (typeMap[i.type] || 0) + 1;

        if (i.status === 'resolved' || i.status === 'cleared') {
          resolvedCount++;
        } else if (i.status !== 'dismissed') {
          activeCount++;
        }
      });

      const severityData = [
        { severity: 'Critical', count: severityMap.critical, fill: '#ef4444' },
        { severity: 'High', count: severityMap.high, fill: '#f97316' },
        { severity: 'Medium', count: severityMap.medium, fill: '#f59e0b' },
        { severity: 'Low', count: severityMap.low, fill: '#3b82f6' },
      ];

      const typeData = Object.entries(typeMap).map(([type, count]) => ({
        type,
        count,
      }));

      const statusData = [
        { name: 'Active Disruptions', count: activeCount, fill: '#ef4444' },
        { name: 'Resolved Hazards', count: resolvedCount, fill: '#10b981' },
      ];

      return {
        data: {
          total: incs.length,
          severityData,
          typeData,
          statusData,
          recentIncidents: incs,
        },
        isLive: false,
        error: err.message || 'Incident analytics backend unreachable',
        missingEndpoint: 'GET /api/incidents',
      };
    }
  },
};

export default analyticsService;

