import { useState, useEffect, useMemo } from 'react';
import {
  BarChart3,
  Car,
  Activity,
  AlertTriangle,
  TrendingUp,
  Clock,
  Filter,
  CheckCircle,
  ShieldAlert,
  Flame,
  Info,
  Calendar,
  Layers,
} from 'lucide-react';
import {
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts';
import {
  PageContainer,
  StatCard,
  LoadingState,
  ErrorState,
  EmptyState,
  StatusBadge,
} from '../components';
import { analyticsService, trafficService } from '../services';
import { useConnection } from '../context';
import { BENGALURU_ROADS } from '../utils/mockTrafficData';

const VEHICLE_COLORS = {
  Cars: '#00d4ff',
  Motorcycles: '#3b82f6',
  Buses: '#10b981',
  Trucks: '#f59e0b',
};

function AnalyticsDashboardPage() {
  const { isConnected } = useConnection();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Filters State (Section D)
  const [timeRange, setTimeRange] = useState('today'); // 'today' | '7d' | '30d'
  const [selectedClass, setSelectedClass] = useState('all'); // 'all' | 'Cars' | 'Motorcycles' | 'Buses' | 'Trucks'
  const [severityFilter, setSeverityFilter] = useState('all'); // 'all' | 'critical' | 'high' | 'medium' | 'low'
  const [roadFilter, setRoadFilter] = useState('all'); // 'all' | roadId

  // Analytics Data
  const [vehicleData, setVehicleData] = useState(null);
  const [densityData, setDensityData] = useState(null);
  const [incidentData, setIncidentData] = useState(null);
  const [roads, setRoads] = useState(BENGALURU_ROADS);

  const loadAnalytics = async () => {
    setLoading(true);
    setError(null);
    try {
      const [vehRes, denRes, incRes, roadsRes] = await Promise.all([
        analyticsService.getVehicleAnalytics(timeRange, selectedClass),
        analyticsService.getTrafficDensityAnalytics(roadFilter),
        analyticsService.getIncidentAnalytics(severityFilter),
        trafficService.getRoads(),
      ]);

      setVehicleData(vehRes.data);
      setDensityData(denRes.data);
      setIncidentData(incRes.data);
      if (roadsRes.data) setRoads(roadsRes.data);
    } catch (err) {
      setError(err.message || 'Failed to aggregate analytics data.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAnalytics();
  }, [timeRange, selectedClass, severityFilter, roadFilter]);

  // Section E: Data-Grounded Insights Computation
  const insights = useMemo(() => {
    if (!vehicleData || !densityData || !incidentData) return null;

    // Most frequently detected vehicle category
    const topVehicle = [...(vehicleData.classes || [])].sort((a, b) => b.count - a.count)[0];

    // Most congested road segment
    const topCongested = [...(densityData.corridorRankings || [])].sort(
      (a, b) => b.congestion - a.congestion
    )[0];

    // Active incidents
    const activeIncCount =
      incidentData.statusData?.find((s) => s.name.includes('Active'))?.count || 0;

    return {
      topVehicleName: topVehicle?.name || 'Cars',
      topVehiclePercent: topVehicle?.percentage || 56.5,
      topVehicleCount: topVehicle?.count || 8420,
      mostCongestedRoad: topCongested?.name || 'Outer Ring Road (Silk Board to Marathahalli)',
      mostCongestedLevel: topCongested?.congestion || 84,
      mostCongestedSpeed: topCongested?.speed || 14,
      activeIncidents: activeIncCount,
      totalRoadsCount: densityData.corridorRankings?.length || 13,
    };
  }, [vehicleData, densityData, incidentData]);

  if (loading) {
    return (
      <PageContainer>
        <LoadingState message="Aggregating UrbanFlow AI Telemetry &amp; Historical Density Analytics…" />
      </PageContainer>
    );
  }

  if (error) {
    return (
      <PageContainer>
        <ErrorState
          title="Analytics Database Offline"
          message={error}
          onRetry={loadAnalytics}
        />
      </PageContainer>
    );
  }

  return (
    <PageContainer className="analytics-page">
      {/* Module Header */}
      <div className="section-header">
        <div className="section-header__left">
          <div
            className="section-header__icon"
            style={{ backgroundColor: 'rgba(0, 212, 255, 0.15)', color: '#00d4ff' }}
          >
            <BarChart3 size={20} />
          </div>
          <div className="section-header__text">
            <h2>Comprehensive Traffic &amp; Mobility Analytics</h2>
            <p>
              Telemetry aggregation, vehicle distribution curves, road congestion rankings, and incident severity metrics
            </p>
          </div>
        </div>

        <div className="section-header__actions">
          <span className="live-status-pill live-status-pill--demo">
            Calibrated Bengaluru Analytics
          </span>
        </div>
      </div>

      {/* SECTION D: FILTERS BAR */}
      <div className="analytics-filter-bar">
        <div className="filter-group-item">
          <Calendar size={14} className="filter-icon" />
          <select value={timeRange} onChange={(e) => setTimeRange(e.target.value)}>
            <option value="today">Today (Live 24h Window)</option>
            <option value="7d">Past 7 Days</option>
            <option value="30d">Past 30 Days</option>
          </select>
        </div>

        <div className="filter-group-item">
          <Car size={14} className="filter-icon" />
          <select value={selectedClass} onChange={(e) => setSelectedClass(e.target.value)}>
            <option value="all">All Vehicle Classes</option>
            <option value="Cars">Cars Only</option>
            <option value="Motorcycles">Motorcycles Only</option>
            <option value="Buses">Buses Only</option>
            <option value="Trucks">Trucks Only</option>
          </select>
        </div>

        <div className="filter-group-item">
          <AlertTriangle size={14} className="filter-icon" />
          <select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}>
            <option value="all">All Incident Severities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>

        <div className="filter-group-item">
          <Layers size={14} className="filter-icon" />
          <select value={roadFilter} onChange={(e) => setRoadFilter(e.target.value)}>
            <option value="all">All Road Corridors ({roads.length})</option>
            {roads.map((r) => (
              <option key={r.id} value={r.id}>
                {r.id}: {r.name}
              </option>
            ))}
          </select>
        </div>

        <button
          className="dashboard-btn"
          onClick={() => {
            setTimeRange('today');
            setSelectedClass('all');
            setSeverityFilter('all');
            setRoadFilter('all');
          }}
        >
          Reset Filters
        </button>
      </div>

      {/* SECTION E: DATA-GROUNDED INSIGHTS SUMMARY BANNER */}
      {insights && (
        <div className="analytics-insights-card">
          <div className="insights-header">
            <Info size={16} style={{ color: '#00d4ff' }} />
            <span className="insights-title">Data-Driven Mobility Findings (Bengaluru Network)</span>
          </div>
          <div className="insights-grid">
            <div className="insight-stat">
              <span className="insight-label">Dominant Vehicle Class</span>
              <span className="insight-value font-mono">
                {insights.topVehicleName} ({insights.topVehiclePercent}%)
              </span>
              <span className="insight-desc">
                {insights.topVehicleCount.toLocaleString()} detections logged across checkpoints
              </span>
            </div>

            <div className="insight-stat">
              <span className="insight-label">Highest Congestion Bottleneck</span>
              <span className="insight-value font-mono" style={{ color: '#ef4444' }}>
                {insights.mostCongestedLevel}% Delay
              </span>
              <span className="insight-desc">
                {insights.mostCongestedRoad} (Avg speed: {insights.mostCongestedSpeed} km/h)
              </span>
            </div>

            <div className="insight-stat">
              <span className="insight-label">Active Network Disruptions</span>
              <span className="insight-value font-mono" style={{ color: '#f59e0b' }}>
                {insights.activeIncidents} Active Hazards
              </span>
              <span className="insight-desc">
                Monitored across {insights.totalRoadsCount} arterial corridors
              </span>
            </div>
          </div>
        </div>
      )}

      {/* SECTION A: VEHICLE ANALYTICS */}
      <div className="analytics-section-title">
        <Car size={16} />
        <span>Section A: Vehicle Optical Classification &amp; Flow Trends</span>
      </div>

      <div className="analytics-kpi-row">
        <StatCard
          label="Total Vehicles Detected"
          value={vehicleData?.totalVehicles?.toLocaleString() || '14,892'}
          description="Cumulative vehicle detections in selected window"
          icon={Car}
          variant="accent"
        />
        <StatCard
          label="Passenger Cars"
          value={vehicleData?.classes?.find((c) => c.name === 'Cars')?.count?.toLocaleString() || '8,420'}
          description="56.5% of overall vehicle volume"
          icon={Car}
          variant="info"
        />
        <StatCard
          label="Two-Wheelers / Motorcycles"
          value={vehicleData?.classes?.find((c) => c.name === 'Motorcycles')?.count?.toLocaleString() || '4,180'}
          description="28.1% of overall vehicle volume"
          icon={TrendingUp}
          variant="accent"
        />
        <StatCard
          label="Public Buses (BMTC)"
          value={vehicleData?.classes?.find((c) => c.name === 'Buses')?.count?.toLocaleString() || '1,340'}
          description="9.0% dedicated transit volume"
          icon={CheckCircle}
          variant="success"
        />
        <StatCard
          label="Heavy Commercial / Trucks"
          value={vehicleData?.classes?.find((c) => c.name === 'Trucks')?.count?.toLocaleString() || '952'}
          description="6.4% logistics freight volume"
          icon={AlertTriangle}
          variant="warning"
        />
      </div>

      {/* Vehicle Charts Grid */}
      <div className="analytics-charts-dual">
        {/* Chart 1: Donut Distribution */}
        <div className="analytics-card">
          <div className="analytics-card__header">
            <div>
              <h3 className="analytics-card__title">Vehicle Category Share</h3>
              <p className="analytics-card__subtitle">Relative proportion of detected vehicle types</p>
            </div>
          </div>
          <div style={{ height: 260 }}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={vehicleData?.classes || []}
                  cx="50%"
                  cy="50%"
                  innerRadius={55}
                  outerRadius={85}
                  paddingAngle={3}
                  dataKey="count"
                >
                  {(vehicleData?.classes || []).map((entry) => (
                    <Cell key={entry.name} fill={VEHICLE_COLORS[entry.name] || '#3b82f6'} />
                  ))}
                </Pie>
                <Tooltip
                  content={({ active, payload }) => {
                    if (active && payload && payload.length) {
                      const item = payload[0].payload;
                      return (
                        <div className="custom-chart-tooltip">
                          <div className="tooltip-title">{item.name}</div>
                          <div className="tooltip-row">
                            <span>Count:</span>
                            <span className="font-mono">{item.count.toLocaleString()}</span>
                          </div>
                          <div className="tooltip-row">
                            <span>Share:</span>
                            <span className="font-mono">{item.percentage}%</span>
                          </div>
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Legend
                  verticalAlign="bottom"
                  formatter={(v) => <span style={{ color: '#94a3b8', fontSize: 12 }}>{v}</span>}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Chart 2: Hourly Detection Trend Lines */}
        <div className="analytics-card">
          <div className="analytics-card__header">
            <div>
              <h3 className="analytics-card__title">Vehicle Flow Timeline</h3>
              <p className="analytics-card__subtitle">Hourly volume trajectory across 24h operational cycle</p>
            </div>
          </div>
          <div style={{ height: 260 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={vehicleData?.trends || []} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(30, 58, 95, 0.4)" vertical={false} />
                <XAxis dataKey="hour" stroke="#94a3b8" fontSize={11} tickLine={false} />
                <YAxis stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (active && payload && payload.length) {
                      return (
                        <div className="custom-chart-tooltip">
                          <div className="tooltip-title">{label} Hrs Telemetry</div>
                          {payload.map((p) => (
                            <div key={p.dataKey} className="tooltip-row">
                              <span style={{ color: p.color }}>{p.name}:</span>
                              <span className="font-mono">{Number(p.value).toLocaleString()}</span>
                            </div>
                          ))}
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Line type="monotone" dataKey="cars" name="Cars" stroke="#00d4ff" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="motorcycles" name="Motorcycles" stroke="#3b82f6" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="buses" name="Buses" stroke="#10b981" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="trucks" name="Trucks" stroke="#f59e0b" strokeWidth={2} dot={false} />
                <Legend verticalAlign="bottom" formatter={(v) => <span style={{ color: '#94a3b8', fontSize: 12 }}>{v}</span>} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* SECTION B: TRAFFIC DENSITY ANALYTICS */}
      <div className="analytics-section-title" style={{ marginTop: 24 }}>
        <Activity size={16} />
        <span>Section B: Arterial Congestion Density &amp; Corridor Rankings</span>
      </div>

      <div className="analytics-charts-dual">
        {/* Chart 3: Road-wise Congestion Ranking Bar Chart */}
        <div className="analytics-card">
          <div className="analytics-card__header">
            <div>
              <h3 className="analytics-card__title">Top Congested Corridors</h3>
              <p className="analytics-card__subtitle">Congestion density percentage ranking across monitored segments</p>
            </div>
          </div>
          <div style={{ height: 280 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={(densityData?.corridorRankings || []).slice(0, 6)}
                layout="vertical"
                margin={{ top: 10, right: 20, left: 20, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(30, 58, 95, 0.4)" horizontal={false} />
                <XAxis type="number" domain={[0, 100]} tickFormatter={(v) => `${v}%`} stroke="#64748b" fontSize={11} />
                <YAxis dataKey="id" type="category" stroke="#94a3b8" fontSize={11} tickLine={false} width={50} />
                <Tooltip
                  content={({ active, payload }) => {
                    if (active && payload && payload.length) {
                      const item = payload[0].payload;
                      return (
                        <div className="custom-chart-tooltip">
                          <div className="tooltip-title">{item.name}</div>
                          <div className="tooltip-row">
                            <span>Congestion Level:</span>
                            <span className="font-mono" style={{ color: item.congestion > 70 ? '#ef4444' : '#f59e0b' }}>
                              {item.congestion}%
                            </span>
                          </div>
                          <div className="tooltip-row">
                            <span>Speed:</span>
                            <span className="font-mono">{item.speed} km/h (Limit: {item.speedLimit})</span>
                          </div>
                          <div className="tooltip-row">
                            <span>Status:</span>
                            <span>{item.status.toUpperCase()}</span>
                          </div>
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Bar dataKey="congestion" radius={[0, 4, 4, 0]} maxBarSize={22}>
                  {(densityData?.corridorRankings || []).slice(0, 6).map((r) => (
                    <Cell
                      key={r.id}
                      fill={r.status === 'closed' ? '#ef4444' : r.congestion > 70 ? '#ef4444' : r.congestion > 45 ? '#f59e0b' : '#10b981'}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Chart 4: Hourly Congestion Profile Area Chart */}
        <div className="analytics-card">
          <div className="analytics-card__header">
            <div>
              <h3 className="analytics-card__title">Network Congestion vs Speed Trajectory</h3>
              <p className="analytics-card__subtitle">Inverse relationship between volume saturation and velocity</p>
            </div>
          </div>
          <div style={{ height: 280 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={densityData?.congestionProfile || []} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="congGrad2" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#f59e0b" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(30, 58, 95, 0.4)" vertical={false} />
                <XAxis dataKey="time" stroke="#94a3b8" fontSize={11} tickLine={false} />
                <YAxis stroke="#64748b" fontSize={11} tickLine={false} domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (active && payload && payload.length) {
                      const item = payload[0].payload;
                      return (
                        <div className="custom-chart-tooltip">
                          <div className="tooltip-title">{label} Hrs Network Telemetry</div>
                          <div className="tooltip-row">
                            <span>Congestion Rate:</span>
                            <span className="font-mono" style={{ color: '#f59e0b' }}>{item.avgCongestion}%</span>
                          </div>
                          <div className="tooltip-row">
                            <span>Avg Speed:</span>
                            <span className="font-mono" style={{ color: '#00d4ff' }}>{item.avgSpeedKmh} km/h</span>
                          </div>
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Area type="monotone" dataKey="avgCongestion" name="Congestion %" stroke="#f59e0b" strokeWidth={2.5} fill="url(#congGrad2)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* SECTION C: INCIDENT ANALYTICS */}
      <div className="analytics-section-title" style={{ marginTop: 24 }}>
        <AlertTriangle size={16} />
        <span>Section C: Incident Distribution, Severity Breakdown &amp; Resolution Status</span>
      </div>

      <div className="analytics-charts-dual">
        {/* Chart 5: Incidents by Severity Bar Chart */}
        <div className="analytics-card">
          <div className="analytics-card__header">
            <div>
              <h3 className="analytics-card__title">Incidents by Severity Level</h3>
              <p className="analytics-card__subtitle">Distribution of road disruptions categorized by severity threshold</p>
            </div>
          </div>
          <div style={{ height: 240 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={incidentData?.severityData || []} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(30, 58, 95, 0.4)" vertical={false} />
                <XAxis dataKey="severity" stroke="#94a3b8" fontSize={11} tickLine={false} />
                <YAxis stroke="#64748b" fontSize={11} tickLine={false} allowDecimals={false} />
                <Tooltip
                  content={({ active, payload }) => {
                    if (active && payload && payload.length) {
                      const item = payload[0].payload;
                      return (
                        <div className="custom-chart-tooltip">
                          <div className="tooltip-title">{item.severity} Severity</div>
                          <div className="tooltip-row">
                            <span>Count:</span>
                            <span className="font-mono">{item.count} incidents</span>
                          </div>
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Bar dataKey="count" radius={[4, 4, 0, 0]} maxBarSize={45}>
                  {(incidentData?.severityData || []).map((entry) => (
                    <Cell key={entry.severity} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Chart 6: Active vs Resolved Status */}
        <div className="analytics-card">
          <div className="analytics-card__header">
            <div>
              <h3 className="analytics-card__title">Active vs Resolved Hazards</h3>
              <p className="analytics-card__subtitle">Dispatched emergency patrols vs cleared road closures</p>
            </div>
          </div>
          <div style={{ height: 240 }}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={incidentData?.statusData || []}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={80}
                  paddingAngle={4}
                  dataKey="count"
                >
                  {(incidentData?.statusData || []).map((entry) => (
                    <Cell key={entry.name} fill={entry.fill} />
                  ))}
                </Pie>
                <Tooltip
                  content={({ active, payload }) => {
                    if (active && payload && payload.length) {
                      const item = payload[0].payload;
                      return (
                        <div className="custom-chart-tooltip">
                          <div className="tooltip-title">{item.name}</div>
                          <div className="tooltip-row">
                            <span>Total:</span>
                            <span className="font-mono">{item.count}</span>
                          </div>
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Legend
                  verticalAlign="bottom"
                  formatter={(v) => <span style={{ color: '#94a3b8', fontSize: 12 }}>{v}</span>}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </PageContainer>
  );
}

export default AnalyticsDashboardPage;
