import { useState, useEffect } from 'react'
import StatusCard from './components/StatusCard'
import SegmentChart from './components/SegmentChart'
import WeatherChart from './components/WeatherChart'
import './App.css'

const API_BASE_URL = '/api'

function App() {
  const [routes, setRoutes] = useState([])
  const [currentStatus, setCurrentStatus] = useState([])
  const [selectedRoute, setSelectedRoute] = useState(null)
  const [segmentData, setSegmentData] = useState([])
  const [weatherData, setWeatherData] = useState([])
  const [timeRange, setTimeRange] = useState(24) // hours
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Fetch routes on mount
  useEffect(() => {
    fetchRoutes()
    fetchCurrentStatus()
    fetchWeather()

    // Refresh current status and weather every 5 minutes
    const interval = setInterval(() => {
      fetchCurrentStatus()
      fetchWeather()
    }, 5 * 60 * 1000)
    return () => clearInterval(interval)
  }, [])

  // Fetch segments when route or time range changes
  useEffect(() => {
    if (selectedRoute) {
      fetchSegments(selectedRoute, timeRange)
    }
  }, [selectedRoute, timeRange])

  const fetchRoutes = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/routes`)
      if (!response.ok) throw new Error('Failed to fetch routes')
      const data = await response.json()
      setRoutes(data)

      // Auto-select Stevens Pass eastbound route by default
      if (data.length > 0 && !selectedRoute) {
        const stevensRoute = data.find(r => r.route_id === 'redmond-stevens-eb')
        setSelectedRoute(stevensRoute ? stevensRoute.route_id : data[0].route_id)
      }
    } catch (err) {
      console.error('Error fetching routes:', err)
      setError(err.message)
    }
  }

  const fetchCurrentStatus = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/current`)
      if (!response.ok) throw new Error('Failed to fetch current status')
      const data = await response.json()
      setCurrentStatus(data)
      setLoading(false)
    } catch (err) {
      console.error('Error fetching current status:', err)
      setError(err.message)
      setLoading(false)
    }
  }

  const fetchSegments = async (routeId, hours) => {
    try {
      const response = await fetch(`${API_BASE_URL}/segments/${routeId}?hours=${hours}`)
      if (!response.ok) throw new Error('Failed to fetch segments')
      const data = await response.json()

      // Reverse to show oldest first for chart
      setSegmentData(data.reverse())
    } catch (err) {
      console.error('Error fetching segments:', err)
      setError(err.message)
    }
  }

  const fetchWeather = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/weather/current`)
      if (!response.ok) {
        console.warn('Weather data not available')
        return
      }
      const data = await response.json()
      setWeatherData(data)
    } catch (err) {
      console.error('Error fetching weather:', err)
      // Don't set error state - weather is optional
    }
  }

  if (loading) {
    return (
      <div className="app">
        <div className="loading">Loading traffic data...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="app">
        <div className="error">
          <h2>Error</h2>
          <p>{error}</p>
          <p>Make sure the API is running and the database is initialized.</p>
        </div>
      </div>
    )
  }

  // Group routes by ski area (dynamically extracted from route names)
  const groupRoutes = () => {
    const groups = {}

    currentStatus.forEach(status => {
      // Parse route name: "Origin to Destination" format
      const parts = status.route_name.split(' to ')
      if (parts.length !== 2) return

      const [origin, destination] = parts

      // Ski area is the one that ends with "Pass", "Baker", or contains "Ski"
      const skiArea = destination.includes('Pass') || destination.includes('Baker') || destination.includes('Ski')
        ? destination
        : origin

      if (!groups[skiArea]) {
        groups[skiArea] = []
      }
      groups[skiArea].push(status)
    })

    // Sort within each group: outbound first (to ski area), then return (from ski area)
    Object.keys(groups).forEach(skiArea => {
      groups[skiArea].sort((a, b) => {
        const aIsReturn = a.route_name.startsWith(skiArea)
        const bIsReturn = b.route_name.startsWith(skiArea)
        if (aIsReturn === bIsReturn) return a.route_name.localeCompare(b.route_name)
        return aIsReturn ? 1 : -1
      })
    })

    return groups
  }

  const routeGroups = groupRoutes()

  // Sort groups to put Stevens Pass first, then Snoqualmie, then others
  const sortedGroupEntries = Object.entries(routeGroups).sort(([a], [b]) => {
    if (a.includes('Stevens')) return -1
    if (b.includes('Stevens')) return 1
    if (a.includes('Snoqualmie')) return -1
    if (b.includes('Snoqualmie')) return 1
    return a.localeCompare(b)
  })

  return (
    <div className="app">
      <header className="header">
        <h1>🎿 Snow Traffic</h1>
        <p className="subtitle">Real-time travel times to Stevens Pass via US-2</p>
      </header>

      <main className="main">
        {/* Route Selector */}
        {routes.length > 1 && (
          <div className="route-selector">
            <label htmlFor="route-select">Route: </label>
            <select
              id="route-select"
              value={selectedRoute || ''}
              onChange={(e) => setSelectedRoute(e.target.value)}
            >
              {routes.map((route) => (
                <option key={route.route_id} value={route.route_id}>
                  {route.route_name}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Current Status Cards - Grouped by Destination */}
        <div className="status-cards">
          {sortedGroupEntries.map(([destination, routes]) => (
            <div key={destination} className="route-group">
              <h3 className="route-group-title">{destination}</h3>
              <div className="route-pair">
                {routes.map((status) => (
                  <StatusCard
                    key={status.route_id}
                    status={status}
                    isSelected={status.route_id === selectedRoute}
                    onClick={() => setSelectedRoute(status.route_id)}
                    weatherData={weatherData}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Travel Time Chart */}
        {selectedRoute && (
          <div className="chart-container">
            <div className="chart-header">
              <h2>Travel Time History</h2>
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
            <SegmentChart data={segmentData} />
          </div>
        )}

        {/* Weather Chart */}
        <WeatherChart />

        {/* Info Section */}
        <div className="info-section">
          <p>
            Data is collected every 15 minutes from Google Maps Routes API.
            {routes.length > 0 && (
              <> Started tracking on {new Date(routes[0].first_recorded).toLocaleDateString()}.</>
            )}
          </p>
        </div>
      </main>
    </div>
  )
}

export default App
