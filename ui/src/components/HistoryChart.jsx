import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer
} from 'recharts'
import './HistoryChart.css'

function HistoryChart({ data }) {
  if (!data || data.length === 0) {
    return (
      <div className="chart-empty">
        <p>No historical data available yet.</p>
        <p>Data will appear here once the poller has collected some samples.</p>
      </div>
    )
  }

  // Transform data for Recharts
  const chartData = data.map((record) => {
    const date = new Date(record.recorded_at)
    return {
      time: date.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit'
      }),
      timestamp: date.getTime(),
      current: record.current_min,
      average: record.average_min
    }
  })

  // Custom tooltip
  const CustomTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
      return (
        <div className="custom-tooltip">
          <p className="label">{payload[0].payload.time}</p>
          <p className="current">
            Current: <strong>{payload[0].value} min</strong>
          </p>
          {payload[1] && (
            <p className="average">
              Average: <strong>{payload[1].value} min</strong>
            </p>
          )}
        </div>
      )
    }
    return null
  }

  return (
    <div className="history-chart">
      <ResponsiveContainer width="100%" height={400}>
        <LineChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis
            dataKey="time"
            stroke="#64748b"
            tick={{ fontSize: 12 }}
            interval="preserveStartEnd"
            angle={-45}
            textAnchor="end"
            height={80}
          />
          <YAxis
            stroke="#64748b"
            tick={{ fontSize: 12 }}
            label={{ value: 'Travel Time (minutes)', angle: -90, position: 'insideLeft' }}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend />
          <Line
            type="monotone"
            dataKey="current"
            stroke="#3b82f6"
            strokeWidth={2}
            dot={{ r: 2 }}
            activeDot={{ r: 6 }}
            name="Current Time"
          />
          <Line
            type="monotone"
            dataKey="average"
            stroke="#94a3b8"
            strokeWidth={2}
            strokeDasharray="5 5"
            dot={false}
            name="Average Time"
          />
        </LineChart>
      </ResponsiveContainer>

      <div className="chart-stats">
        <div className="stat">
          <span className="stat-label">Data Points:</span>
          <span className="stat-value">{data.length}</span>
        </div>
        <div className="stat">
          <span className="stat-label">Min:</span>
          <span className="stat-value">
            {Math.min(...data.map(d => d.current_min || Infinity))} min
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">Max:</span>
          <span className="stat-value">
            {Math.max(...data.map(d => d.current_min || -Infinity))} min
          </span>
        </div>
      </div>
    </div>
  )
}

export default HistoryChart
