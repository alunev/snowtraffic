import { useEffect, useState } from 'react'
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine
} from 'recharts'
import './WeatherChart.css'

const API_BASE_URL = '/api'

function WeatherChart() {
  const [weatherHistory, setWeatherHistory] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [timeRange, setTimeRange] = useState(24) // hours

  useEffect(() => {
    fetchWeatherHistory(timeRange)
    const interval = setInterval(() => fetchWeatherHistory(timeRange), 15 * 60 * 1000) // Refresh every 15 min
    return () => clearInterval(interval)
  }, [timeRange])

  const fetchWeatherHistory = async (hours) => {
    try {
      const response = await fetch(`${API_BASE_URL}/weather/history?hours=${hours}`)
      if (!response.ok) return

      const data = await response.json()

      // Process data for charting
      const chartData = data
        .filter(d => d.station_type === 'base')
        .map(d => {
          const date = new Date(d.recorded_at + 'Z')
          // Format time based on range
          let timeLabel
          if (hours <= 24) {
            // Show time for 24h view
            timeLabel = date.toLocaleTimeString('en-US', {
              hour: 'numeric',
              minute: '2-digit'
            })
          } else {
            // Show date for longer ranges
            timeLabel = date.toLocaleDateString('en-US', {
              month: 'short',
              day: 'numeric',
              hour: 'numeric'
            })
          }

          return {
            time: timeLabel,
            temp: d.temperature_f,
            snow: d.snow_accum_inches || 0,
            depth: d.snow_depth_inches,
            timestamp: date.getTime()
          }
        })
        .sort((a, b) => a.timestamp - b.timestamp)

      setWeatherHistory(chartData)

      // Calculate stats
      if (data.length > 0) {
        const latest = data[data.length - 1]

        // Get data points for different time ranges
        const now = Date.now()
        const last24h = data.filter(d => new Date(d.recorded_at + 'Z').getTime() > now - 24 * 60 * 60 * 1000)
        const last3d = data.filter(d => new Date(d.recorded_at + 'Z').getTime() > now - 3 * 24 * 60 * 60 * 1000)
        const last7d = data.filter(d => new Date(d.recorded_at + 'Z').getTime() > now - 7 * 24 * 60 * 60 * 1000)

        setStats({
          since4pm: latest.snow_accum_inches || 0,
          density: latest.snow_density,
          last24h: Math.max(...last24h.map(d => d.snow_accum_inches || 0)),
          last3d: Math.max(...last3d.map(d => d.snow_accum_inches || 0)),
          last7d: Math.max(...last7d.map(d => d.snow_accum_inches || 0)),
          currentDepth: latest.snow_depth_inches,
          currentTemp: latest.temperature_f
        })
      }

      setLoading(false)
    } catch (err) {
      console.error('Error fetching weather history:', err)
      setLoading(false)
    }
  }

  if (loading) {
    return <div className="weather-chart-loading">Loading weather data...</div>
  }

  if (weatherHistory.length === 0) {
    return null
  }

  const CustomTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
      return (
        <div className="weather-tooltip">
          <p className="time">{payload[0].payload.time}</p>
          <p className="temp">Temp: {payload.find(p => p.dataKey === 'temp')?.value?.toFixed(1)}°F</p>
          <p className="snow">Snow: {payload.find(p => p.dataKey === 'snow')?.value?.toFixed(1)}"</p>
          <p className="depth">Depth: {payload.find(p => p.dataKey === 'depth')?.value?.toFixed(0)}"</p>
        </div>
      )
    }
    return null
  }

  return (
    <div className="weather-chart-container">
      <div className="weather-chart-header">
        <div className="chart-title-row">
          <h2>Snow Report - Stevens Pass Base</h2>
          <div className="time-range-selector">
            <button
              className={timeRange === 24 ? 'active' : ''}
              onClick={() => setTimeRange(24)}
            >
              24 Hours
            </button>
            <button
              className={timeRange === 168 ? 'active' : ''}
              onClick={() => setTimeRange(168)}
            >
              7 Days
            </button>
            <button
              className={timeRange === 720 ? 'active' : ''}
              onClick={() => setTimeRange(720)}
            >
              30 Days
            </button>
          </div>
        </div>
        {stats && (
          <div className="weather-stats">
            <div className="stat">
              <span className="stat-label">Since 4pm:</span>
              <span className="stat-value">
                {stats.since4pm.toFixed(1)}"
                {stats.density && stats.since4pm > 0 && (
                  <span className="stat-ratio"> ({(1/stats.density).toFixed(0)}:1)</span>
                )}
              </span>
            </div>
            <div className="stat">
              <span className="stat-label">24h:</span>
              <span className="stat-value">{stats.last24h.toFixed(1)}"</span>
            </div>
            <div className="stat">
              <span className="stat-label">3d:</span>
              <span className="stat-value">{stats.last3d.toFixed(1)}"</span>
            </div>
            <div className="stat">
              <span className="stat-label">7d:</span>
              <span className="stat-value">{stats.last7d.toFixed(1)}"</span>
            </div>
            <div className="stat">
              <span className="stat-label">Depth:</span>
              <span className="stat-value">{stats.currentDepth?.toFixed(0)}"</span>
            </div>
            <div className="stat">
              <span className="stat-label">Temp:</span>
              <span className="stat-value">{stats.currentTemp?.toFixed(1)}°F</span>
            </div>
          </div>
        )}
      </div>

      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={weatherHistory} margin={{ top: 20, right: 30, left: 0, bottom: 20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis
            dataKey="time"
            tick={{ fontSize: 12 }}
            interval="preserveStartEnd"
          />
          <YAxis
            yAxisId="temp"
            orientation="left"
            label={{ value: 'Temperature (°F)', angle: -90, position: 'insideLeft' }}
            domain={['dataMin - 5', 'dataMax + 5']}
          />
          <YAxis
            yAxisId="snow"
            orientation="right"
            label={{ value: 'Snow Accum (inches)', angle: 90, position: 'insideRight' }}
            domain={[0, 'auto']}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend />

          {/* Freezing line at 32°F */}
          <ReferenceLine
            yAxisId="temp"
            y={32}
            stroke="#3b82f6"
            strokeDasharray="3 3"
            label={{ value: '32°F (Freezing)', position: 'right', fill: '#3b82f6', fontSize: 11 }}
          />

          {/* Temperature line (red, like LP) */}
          <Line
            yAxisId="temp"
            type="monotone"
            dataKey="temp"
            stroke="#dc2626"
            strokeWidth={2}
            dot={false}
            name="Temperature"
          />

          {/* Snow accumulation bars (blue, like LP) */}
          <Bar
            yAxisId="snow"
            dataKey="snow"
            fill="#60a5fa"
            name="Snow Accum"
          />
        </ComposedChart>
      </ResponsiveContainer>

      <div className="weather-chart-note">
        * Data from SNOTEL 791 weather station. Updates every 15 minutes. Snow accumulation resets daily at 4pm (lifts closure).
      </div>
    </div>
  )
}

export default WeatherChart
