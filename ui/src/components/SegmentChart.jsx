import { useState } from 'react'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer
} from 'recharts'
import './SegmentChart.css'

// Color palette for segments
const SEGMENT_COLORS = [
  '#3b82f6', // blue
  '#10b981', // green
  '#f59e0b', // amber
  '#ef4444', // red
  '#8b5cf6', // purple
  '#ec4899', // pink
]

function SegmentChart({ data }) {
  const [isolatedSegment, setIsolatedSegment] = useState(null)

  if (!data || data.length === 0) {
    return (
      <div className="chart-empty">
        <p>No segment data available yet.</p>
        <p>Data will appear here once the poller has collected some samples.</p>
      </div>
    )
  }

  // Get unique segment names from most recent record (last in array after reverse)
  // This ensures we use the current segment structure, not historical
  const mostRecentRecord = data[data.length - 1]
  const segmentNames = mostRecentRecord?.segments?.map((seg, idx) => ({
    key: `seg${idx}`,
    name: `${seg.from} → ${seg.to}`,
    color: SEGMENT_COLORS[idx % SEGMENT_COLORS.length]
  })) || []

  // Transform data for Recharts
  const chartData = data.map((record) => {
    // Parse as UTC (database stores in UTC without Z suffix)
    const date = new Date(record.recorded_at + 'Z')
    const timeStr = date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit'
    })

    const dataPoint = {
      time: timeStr,
      timestamp: date.getTime(),
    }

    // Add each segment as a data key
    if (isolatedSegment !== null) {
      // Isolate mode: show only selected segment, re-baselined to zero
      dataPoint[segmentNames[isolatedSegment].key] = record.segments[isolatedSegment]?.duration_min || 0
    } else {
      // Stacked mode: show all segments
      record.segments.forEach((seg, idx) => {
        dataPoint[segmentNames[idx].key] = seg.duration_min || 0
      })
    }

    return dataPoint
  })

  // Custom tooltip
  const CustomTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
      const totalTime = payload.reduce((sum, item) => sum + (item.value || 0), 0)

      return (
        <div className="custom-tooltip">
          <p className="label">{payload[0].payload.time}</p>
          {isolatedSegment === null && (
            <p className="total-time">
              <strong>Total: {totalTime} min</strong>
            </p>
          )}
          {payload.map((item, idx) => {
            const segmentInfo = segmentNames.find(s => s.key === item.dataKey)
            return (
              <p key={idx} style={{ color: item.color }}>
                {segmentInfo?.name}: <strong>{item.value} min</strong>
              </p>
            )
          })}
        </div>
      )
    }
    return null
  }

  // Custom legend click handler
  const handleLegendClick = (segmentIndex) => {
    if (isolatedSegment === segmentIndex) {
      // Already isolated, return to stacked view
      setIsolatedSegment(null)
    } else {
      // Isolate this segment
      setIsolatedSegment(segmentIndex)
    }
  }

  // Custom legend renderer
  const renderLegend = () => {
    return (
      <div className="segment-legend">
        <div className="legend-title">
          {isolatedSegment !== null ? (
            <span className="legend-mode">Isolated Mode (click to return)</span>
          ) : (
            <span className="legend-mode">Stacked Mode (click segment to isolate)</span>
          )}
        </div>
        <div className="legend-items">
          {segmentNames.map((segment, idx) => (
            <div
              key={segment.key}
              className={`legend-item ${isolatedSegment === idx ? 'active' : ''} ${isolatedSegment !== null && isolatedSegment !== idx ? 'dimmed' : ''}`}
              onClick={() => handleLegendClick(idx)}
            >
              <div
                className="legend-color"
                style={{ backgroundColor: segment.color }}
              />
              <span className="legend-label">{segment.name}</span>
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="segment-chart">
      {renderLegend()}

      <ResponsiveContainer width="100%" height={400}>
        <AreaChart data={chartData} margin={{ top: 10, right: 30, left: 20, bottom: 5 }}>
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
            label={{
              value: isolatedSegment !== null ? 'Segment Time (minutes)' : 'Total Time (minutes)',
              angle: -90,
              position: 'insideLeft'
            }}
          />
          <Tooltip content={<CustomTooltip />} />

          {/* Render areas based on mode */}
          {isolatedSegment !== null ? (
            // Isolated mode: single area
            <Area
              type="monotone"
              dataKey={segmentNames[isolatedSegment].key}
              stackId="1"
              stroke={segmentNames[isolatedSegment].color}
              fill={segmentNames[isolatedSegment].color}
              fillOpacity={0.6}
            />
          ) : (
            // Stacked mode: all areas
            segmentNames.map((segment) => (
              <Area
                key={segment.key}
                type="monotone"
                dataKey={segment.key}
                stackId="1"
                stroke={segment.color}
                fill={segment.color}
                fillOpacity={0.6}
              />
            ))
          )}
        </AreaChart>
      </ResponsiveContainer>

      <div className="chart-stats">
        <div className="stat">
          <span className="stat-label">Data Points:</span>
          <span className="stat-value">{data.length}</span>
        </div>
        {isolatedSegment !== null && (
          <div className="stat">
            <span className="stat-label">Viewing:</span>
            <span className="stat-value">{segmentNames[isolatedSegment].name}</span>
          </div>
        )}
      </div>
    </div>
  )
}

export default SegmentChart
