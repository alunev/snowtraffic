import './StatusCard.css'

function StatusCard({ status, isSelected, onClick, weatherData }) {
  const {
    route_id,
    route_name,
    current_min,
    average_min,
    delta_min,
    delta_percent,
    last_updated,
    status: routeStatus
  } = status

  const isClosed = routeStatus === 'closed' || current_min === null

  // Determine status level for color coding
  const getStatusLevel = () => {
    if (isClosed) return 'closed'
    if (!delta_percent) return 'normal'
    if (delta_percent >= 50) return 'severe'
    if (delta_percent >= 25) return 'warning'
    if (delta_percent >= 10) return 'moderate'
    return 'normal'
  }

  const statusLevel = getStatusLevel()

  const formatTime = (dateString) => {
    // Parse as UTC (database stores in UTC without Z suffix)
    const date = new Date(dateString + 'Z')
    return date.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit'
    })
  }

  // Get weather data for routes TO Stevens Pass only (not return routes)
  const isStevensToRoute = route_id?.includes('-stevens-')
  const baseStation = weatherData?.find(w => w.station_type === 'base')
  const summitStation = weatherData?.find(w => w.station_type === 'summit')

  return (
    <div
      className={`status-card ${statusLevel} ${isSelected ? 'selected' : ''}`}
      onClick={onClick}
    >
      <div className="card-header">
        <h3 className="route-name">{route_name}</h3>
        <div className="badges">
          {isClosed && <span className="closed-badge">CLOSED</span>}
          {isSelected && <span className="selected-badge">Selected</span>}
        </div>
      </div>

      {isClosed ? (
        <div className="closed-message">
          <p className="closed-text">Route Currently Unavailable</p>
          <p className="closed-subtext">Will auto-update when reopened</p>
        </div>
      ) : (
        <div className="compact-info">
          <span className="time-value">{current_min || '--'}</span>
          <span className="time-unit">min</span>
          {delta_min !== null && delta_min !== undefined && (
            <span className={`delta-inline ${delta_min > 0 ? 'above' : 'below'}`}>
              ({delta_min > 0 ? '+' : ''}{delta_min})
            </span>
          )}
          <span className="dot">•</span>
          <span className="avg-label">avg {average_min}</span>
          <span className="dot">•</span>
          <span className="updated-label">{formatTime(last_updated)}</span>

          {/* Weather info inline - routes TO Stevens Pass only */}
          {isStevensToRoute && baseStation && (
            <>
              <span className="dot">•</span>
              <span className="weather-inline">
                Base: {baseStation.temperature_f}°F • {baseStation.snow_accum_inches?.toFixed(1) || '0.0'}" snow
                {baseStation.snow_density && baseStation.snow_accum_inches > 0 && (
                  <> ({(1 / baseStation.snow_density).toFixed(0)}:1)</>
                )} / {baseStation.rain_accum_inches?.toFixed(2) || '0.00'}" rain (since 4pm)
              </span>
            </>
          )}
        </div>
      )}

      {isClosed && (
        <div className="closed-footer">
          Checked: {formatTime(last_updated)}
        </div>
      )}
    </div>
  )
}

export default StatusCard
