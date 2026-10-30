import { useState, useEffect, useCallback } from 'react';
import {
  Car,
  AlertTriangle,
  CheckCircle2,
  AlertOctagon,
  XCircle,
  Activity,
} from 'lucide-react';
import {
  PageContainer,
  StatCard,
  DashboardHeader,
  VehicleDistributionChart,
  CongestionTrendChart,
  RoadStatusChart,
  RecentIncidents,
  TrafficMapPreview,
  LoadingState,
  ErrorState,
} from '../components';
import { dashboardService } from '../services';
import { useConnection } from '../context';
import {
  MOCK_DASHBOARD_DATA,
  BENGALURU_ROADS,
  BENGALURU_INCIDENTS,
} from '../utils/mockTrafficData';

function OverviewPage() {
  const { isConnected, isDemoMode, checkConnection } = useConnection();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(new Date());

  // Dashboard Data State
  const [dashboardData, setDashboardData] = useState({
    kpis: MOCK_DASHBOARD_DATA.kpis,
    vehicleDistribution: MOCK_DASHBOARD_DATA.vehicleDistribution,
    congestionTrends: MOCK_DASHBOARD_DATA.congestionTrends,
    roadStatusDistribution: MOCK_DASHBOARD_DATA.roadStatusDistribution,
    incidents: BENGALURU_INCIDENTS,
    roads: BENGALURU_ROADS,
  });

  const loadData = useCallback(async (isRefresh = false) => {
    if (isRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);

    try {
      const response = await dashboardService.getDashboardData();
      if (response && response.data) {
        // If live API returns structured fields, adapt them
        const data = response.data;
        setDashboardData({
          kpis: data.kpis || {
            totalVehicles: data.traffic_summary?.total_vehicles?.toLocaleString() || MOCK_DASHBOARD_DATA.kpis.totalVehicles,
            activeIncidents: data.active_incidents?.length || MOCK_DASHBOARD_DATA.kpis.activeIncidents,
            openRoads: data.traffic_summary?.open_roads || MOCK_DASHBOARD_DATA.kpis.openRoads,
            congestedRoads: data.traffic_summary?.congested_roads || MOCK_DASHBOARD_DATA.kpis.congestedRoads,
            closedRoads: data.traffic_summary?.closed_roads || MOCK_DASHBOARD_DATA.kpis.closedRoads,
            trafficDensity: data.traffic_summary?.average_density
              ? `${Math.round(data.traffic_summary.average_density * 100)}%`
              : MOCK_DASHBOARD_DATA.kpis.trafficDensity,
          },
          vehicleDistribution: data.vehicleDistribution || MOCK_DASHBOARD_DATA.vehicleDistribution,
          congestionTrends: data.congestionTrends || MOCK_DASHBOARD_DATA.congestionTrends,
          roadStatusDistribution: data.roadStatusDistribution || MOCK_DASHBOARD_DATA.roadStatusDistribution,
          incidents: data.incidents || BENGALURU_INCIDENTS,
          roads: data.roads || BENGALURU_ROADS,
        });
        setLastUpdated(new Date());
      }
    } catch (err) {
      console.warn('Dashboard fetch error:', err);
      // Fallback to demonstration data
      setDashboardData({
        kpis: MOCK_DASHBOARD_DATA.kpis,
        vehicleDistribution: MOCK_DASHBOARD_DATA.vehicleDistribution,
        congestionTrends: MOCK_DASHBOARD_DATA.congestionTrends,
        roadStatusDistribution: MOCK_DASHBOARD_DATA.roadStatusDistribution,
        incidents: BENGALURU_INCIDENTS,
        roads: BENGALURU_ROADS,
      });
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleRefresh = () => {
    loadData(true);
    checkConnection();
  };

  if (loading) {
    return (
      <PageContainer>
        <LoadingState message="Connecting to UrbanFlow AI Traffic Intelligence Core…" />
      </PageContainer>
    );
  }

  if (error) {
    return (
      <PageContainer>
        <ErrorState
          title="Failed to Load Traffic Intelligence Overview"
          message={error}
          onRetry={() => loadData(false)}
        />
      </PageContainer>
    );
  }

  const { kpis, vehicleDistribution, congestionTrends, roadStatusDistribution, incidents, roads } =
    dashboardData;

  return (
    <PageContainer className="overview-page">
      {/* SECTION 1: DASHBOARD HEADER */}
      <DashboardHeader
        title="Traffic Intelligence Overview"
        subtitle="Real-time traffic monitoring and urban mobility insights."
        lastUpdated={lastUpdated}
        isRefreshing={refreshing}
        onRefresh={handleRefresh}
        isConnected={isConnected}
        isDemoMode={isDemoMode}
        onRetryConnection={checkConnection}
      />

      {/* SECTION 2: KPI CARDS (6 CARDS) */}
      <div className="kpi-grid">
        <StatCard
          label="Total Vehicle Detections"
          value={kpis.totalVehicles}
          description="Cumulative detections across all camera checkpoints"
          icon={Car}
          variant="accent"
          trend="+8.4% vs last hour"
          trendDirection="up"
        />

        <StatCard
          label="Active Incidents"
          value={kpis.activeIncidents}
          description="Live road disturbances requiring intervention"
          icon={AlertTriangle}
          variant="danger"
          trend="2 critical severity"
          trendDirection="down"
        />

        <StatCard
          label="Open Roads"
          value={kpis.openRoads}
          description="Corridors operating at optimal traffic capacity"
          icon={CheckCircle2}
          variant="success"
          trend="72% of arterial network"
          trendDirection="up"
        />

        <StatCard
          label="Congested Roads"
          value={kpis.congestedRoads}
          description="Corridors with severe delays (>70% density)"
          icon={AlertOctagon}
          variant="warning"
          trend="Avg speed 16 km/h"
          trendDirection="neutral"
        />

        <StatCard
          label="Closed Roads"
          value={kpis.closedRoads}
          description="Blocked sectors with active traffic diversions"
          icon={XCircle}
          variant="danger"
          trend="KR Puram & Bannerghatta"
          trendDirection="down"
        />

        <StatCard
          label="Traffic Density"
          value={kpis.trafficDensity}
          description="Network-wide average volume utilization"
          icon={Activity}
          variant="info"
          trend="Moderate to High"
          trendDirection="neutral"
        />
      </div>

      {/* SECTION 3: TRAFFIC ANALYTICS CHARTS */}
      <div className="analytics-grid">
        <VehicleDistributionChart data={vehicleDistribution} />
        <CongestionTrendChart data={congestionTrends} />
        <RoadStatusChart data={roadStatusDistribution} />
      </div>

      {/* SECTION 4 & 5: RECENT INCIDENTS + MAP PREVIEW */}
      <div className="dashboard-split-grid">
        <div className="dashboard-split-grid__left">
          <RecentIncidents incidents={incidents} />
        </div>
        <div className="dashboard-split-grid__right">
          <TrafficMapPreview roads={roads} incidents={incidents} />
        </div>
      </div>
    </PageContainer>
  );
}

export default OverviewPage;
