import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';
import { Route } from 'lucide-react';

const STATUS_COLORS = {
  Open: '#10b981',
  Congested: '#f59e0b',
  Closed: '#ef4444',
};

function CustomBarTooltip({ active, payload }) {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    return (
      <div className="custom-chart-tooltip">
        <div className="tooltip-title">{data.status} Corridors</div>
        <div className="tooltip-row">
          <span className="tooltip-label">Roads:</span>
          <span className="tooltip-value font-mono" style={{ color: STATUS_COLORS[data.status] }}>
            {data.count} Segments
          </span>
        </div>
        <div className="tooltip-row">
          <span className="tooltip-label">Percentage:</span>
          <span className="tooltip-value font-mono">{data.percentage || ((data.count / 25) * 100).toFixed(0)}%</span>
        </div>
      </div>
    );
  }
  return null;
}

function RoadStatusChart({ data }) {
  const chartData = data && data.length ? data : [
    { status: 'Open', count: 18, percentage: 72 },
    { status: 'Congested', count: 5, percentage: 20 },
    { status: 'Closed', count: 2, percentage: 8 },
  ];

  const totalRoads = chartData.reduce((acc, curr) => acc + curr.count, 0);

  return (
    <div className="analytics-card">
      <div className="analytics-card__header">
        <div>
          <h3 className="analytics-card__title">Road Status Distribution</h3>
          <p className="analytics-card__subtitle">Operability status across arterial network</p>
        </div>
        <div className="analytics-card__badge analytics-card__badge--green">
          <Route size={14} />
          <span>{totalRoads} Corridors</span>
        </div>
      </div>

      <div className="analytics-card__chart-wrap" style={{ height: 260 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 20, right: 10, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(30, 58, 95, 0.4)" vertical={false} />
            <XAxis
              dataKey="status"
              stroke="#94a3b8"
              fontSize={12}
              tickLine={false}
              axisLine={{ stroke: 'rgba(30, 58, 95, 0.5)' }}
            />
            <YAxis
              stroke="#64748b"
              fontSize={12}
              tickLine={false}
              axisLine={false}
              allowDecimals={false}
            />
            <Tooltip content={<CustomBarTooltip />} />
            <Bar dataKey="count" radius={[6, 6, 0, 0]} maxBarSize={48}>
              {chartData.map((entry) => (
                <Cell key={`bar-${entry.status}`} fill={STATUS_COLORS[entry.status] || '#3b82f6'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="distribution-pills">
        {chartData.map((item) => (
          <div key={item.status} className="distribution-pill">
            <span
              className="distribution-pill__indicator"
              style={{ backgroundColor: STATUS_COLORS[item.status] }}
            />
            <span className="distribution-pill__name">{item.status}</span>
            <span className="distribution-pill__val" style={{ color: STATUS_COLORS[item.status] }}>
              {item.count} ({item.percentage ? `${item.percentage}%` : `${Math.round((item.count / totalRoads) * 100)}%`})
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default RoadStatusChart;

