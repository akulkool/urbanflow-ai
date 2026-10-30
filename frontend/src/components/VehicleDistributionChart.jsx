import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts';
import { Car } from 'lucide-react';

const COLORS = ['#00d4ff', '#3b82f6', '#10b981', '#f59e0b'];

function CustomTooltip({ active, payload }) {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    return (
      <div className="custom-chart-tooltip">
        <div className="tooltip-title">{data.name}</div>
        <div className="tooltip-row">
          <span className="tooltip-label">Count:</span>
          <span className="tooltip-value font-mono">{Number(data.value).toLocaleString()}</span>
        </div>
        <div className="tooltip-row">
          <span className="tooltip-label">Share:</span>
          <span className="tooltip-value font-mono">{data.percentage || ((data.value / 14892) * 100).toFixed(1)}%</span>
        </div>
      </div>
    );
  }
  return null;
}

function VehicleDistributionChart({ data }) {
  const chartData = data && data.length ? data : [
    { name: 'Cars', value: 8420, percentage: 56.5 },
    { name: 'Motorcycles', value: 4180, percentage: 28.1 },
    { name: 'Buses', value: 1340, percentage: 9.0 },
    { name: 'Trucks', value: 952, percentage: 6.4 },
  ];

  const total = chartData.reduce((acc, curr) => acc + curr.value, 0);

  return (
    <div className="analytics-card">
      <div className="analytics-card__header">
        <div>
          <h3 className="analytics-card__title">Vehicle Distribution</h3>
          <p className="analytics-card__subtitle">Active detections classified by vehicle category</p>
        </div>
        <div className="analytics-card__badge">
          <Car size={14} />
          <span>{total.toLocaleString()} total</span>
        </div>
      </div>

      <div className="analytics-card__chart-wrap" style={{ height: 260 }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={chartData}
              cx="50%"
              cy="50%"
              innerRadius={55}
              outerRadius={85}
              paddingAngle={3}
              dataKey="value"
            >
              {chartData.map((entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={entry.color || COLORS[index % COLORS.length]}
                  stroke="#0c1220"
                  strokeWidth={2}
                />
              ))}
            </Pie>
            <Tooltip content={<CustomTooltip />} />
            <Legend
              verticalAlign="bottom"
              height={36}
              formatter={(value, entry) => (
                <span style={{ color: '#94a3b8', fontSize: '0.8rem', marginRight: 10 }}>
                  {value}
                </span>
              )}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>

      <div className="distribution-pills">
        {chartData.map((item, idx) => (
          <div key={item.name} className="distribution-pill">
            <span
              className="distribution-pill__indicator"
              style={{ backgroundColor: item.color || COLORS[idx % COLORS.length] }}
            />
            <span className="distribution-pill__name">{item.name}</span>
            <span className="distribution-pill__val">
              {item.percentage ? `${item.percentage}%` : `${Math.round((item.value / total) * 100)}%`}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default VehicleDistributionChart;

