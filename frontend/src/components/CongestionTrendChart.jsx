import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { Activity } from 'lucide-react';

function CustomTrendTooltip({ active, payload, label }) {
  if (active && payload && payload.length) {
    const rate = payload[0].value;
    const vol = payload[0].payload.vehicleVolume;
    return (
      <div className="custom-chart-tooltip">
        <div className="tooltip-title">{label} Hrs</div>
        <div className="tooltip-row">
          <span className="tooltip-label">Congestion:</span>
          <span className="tooltip-value font-mono" style={{ color: rate > 70 ? '#ef4444' : rate > 45 ? '#f59e0b' : '#10b981' }}>
            {rate}%
          </span>
        </div>
        {vol && (
          <div className="tooltip-row">
            <span className="tooltip-label">Vehicles:</span>
            <span className="tooltip-value font-mono">{vol.toLocaleString()}</span>
          </div>
        )}
      </div>
    );
  }
  return null;
}

function CongestionTrendChart({ data }) {
  const chartData = data && data.length ? data : [
    { time: '06:00', congestionRate: 22, vehicleVolume: 3200 },
    { time: '08:00', congestionRate: 68, vehicleVolume: 11400 },
    { time: '10:00', congestionRate: 84, vehicleVolume: 14892 },
    { time: '12:00', congestionRate: 52, vehicleVolume: 8900 },
    { time: '14:00', congestionRate: 48, vehicleVolume: 7800 },
    { time: '16:00', congestionRate: 64, vehicleVolume: 10600 },
    { time: '18:00', congestionRate: 89, vehicleVolume: 16400 },
    { time: '20:00', congestionRate: 71, vehicleVolume: 12300 },
    { time: '22:00', congestionRate: 38, vehicleVolume: 5600 },
  ];

  return (
    <div className="analytics-card">
      <div className="analytics-card__header">
        <div>
          <h3 className="analytics-card__title">Congestion Trends</h3>
          <p className="analytics-card__subtitle">Hourly congestion percentage across monitored corridors</p>
        </div>
        <div className="analytics-card__badge analytics-card__badge--cyan">
          <Activity size={14} />
          <span>Peak: 89% at 18:00</span>
        </div>
      </div>

      <div className="analytics-card__chart-wrap" style={{ height: 260 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="congestionGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#00d4ff" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#00d4ff" stopOpacity={0.0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(30, 58, 95, 0.4)" vertical={false} />
            <XAxis
              dataKey="time"
              stroke="#64748b"
              fontSize={12}
              tickLine={false}
              axisLine={{ stroke: 'rgba(30, 58, 95, 0.5)' }}
            />
            <YAxis
              stroke="#64748b"
              fontSize={12}
              tickLine={false}
              axisLine={false}
              domain={[0, 100]}
              tickFormatter={(v) => `${v}%`}
            />
            <Tooltip content={<CustomTrendTooltip />} />
            <Area
              type="monotone"
              dataKey="congestionRate"
              stroke="#00d4ff"
              strokeWidth={2.5}
              fillOpacity={1}
              fill="url(#congestionGrad)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="chart-legend-row">
        <span className="legend-chip legend-chip--green">0-40% Free Flow</span>
        <span className="legend-chip legend-chip--orange">41-75% Moderate Delay</span>
        <span className="legend-chip legend-chip--red">76-100% Critical Bottleneck</span>
      </div>
    </div>
  );
}

export default CongestionTrendChart;

