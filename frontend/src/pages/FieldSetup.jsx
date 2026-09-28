import React, { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import L from 'leaflet'
import 'leaflet-draw'
import { fieldAPI } from '../api/client'
import './FieldSetup.css'

// Fix Leaflet's default marker icon paths broken by Vite asset hashing
delete L.Icon.Default.prototype._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl:       'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl:     'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
})

// ── Tooltip component ─────────────────────────────────────────────────────────
function Tooltip({ text }) {
  const [visible, setVisible] = useState(false)
  return (
    <span
      className="tooltip-anchor"
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
      onFocus={() => setVisible(true)}
      onBlur={() => setVisible(false)}
      tabIndex={0}
      aria-label={text}
    >
      <span className="tooltip-icon" aria-hidden="true">?</span>
      {visible && <span className="tooltip-box" role="tooltip">{text}</span>}
    </span>
  )
}

// ── Field label + tooltip row ─────────────────────────────────────────────────
function FieldLabel({ htmlFor, label, tooltip, required }) {
  return (
    <div className="field-label-row">
      <label htmlFor={htmlFor}>
        {label}{required && <span className="required-star"> *</span>}
      </label>
      {tooltip && <Tooltip text={tooltip} />}
    </div>
  )
}

// ── Random farm name generator ────────────────────────────────────────────────
const ADJECTIVES = ['Sunrise', 'Golden', 'Prairie', 'Valley', 'Rolling', 'Green',
  'Harvest', 'Meadow', 'Crystal', 'Silver', 'Blue Ridge', 'Oak', 'Maple', 'Cedar',
  'Willow', 'Elm', 'Broad', 'Deep', 'Clear', 'Misty']
const NOUNS = ['Acres', 'Fields', 'Farm', 'Homestead', 'Ridge', 'Hollow',
  'Creek', 'Run', 'Bend', 'Flats', 'Knoll', 'Plain', 'Grove', 'Crossing', 'Bottom']

function randomFieldName() {
  const adj  = ADJECTIVES[Math.floor(Math.random() * ADJECTIVES.length)]
  const noun = NOUNS[Math.floor(Math.random() * NOUNS.length)]
  return `${adj} ${noun}`
}

// ── Leaflet map wrapper ───────────────────────────────────────────────────────
function MapDrawer({ onPolygonChange, initialGeometry }) {
  const mapRef      = useRef(null)
  const mapObj      = useRef(null)
  const drawnRef    = useRef(null)
  const [search,    setSearch]    = useState('')
  const [results,   setResults]   = useState([])
  const [searching, setSearching] = useState(false)
  const debounceRef = useRef(null)

  // ── Geocode search (Nominatim, no API key) ──────────────────────────
  const doSearch = async (query) => {
    if (!query.trim() || query.length < 3) { setResults([]); return }
    setSearching(true)
    try {
      const resp = await fetch(
        `https://nominatim.openstreetmap.org/search?format=jsonv2&q=${encodeURIComponent(query)}&limit=6`,
        { headers: { 'Accept-Language': 'en', 'User-Agent': 'HarvestAI/1.0' } }
      )
      setResults(await resp.json())
    } catch { setResults([]) }
    finally { setSearching(false) }
  }

  const handleSearchInput = (e) => {
    const val = e.target.value
    setSearch(val)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => doSearch(val), 400)
  }

  const flyTo = (result) => {
    if (!mapObj.current) return
    const bbox = result.boundingbox  // [minlat, maxlat, minlon, maxlon]
    if (bbox) {
      mapObj.current.fitBounds([
        [parseFloat(bbox[0]), parseFloat(bbox[2])],
        [parseFloat(bbox[1]), parseFloat(bbox[3])],
      ], { padding: [30, 30], maxZoom: 17 })
    } else {
      mapObj.current.setView([parseFloat(result.lat), parseFloat(result.lon)], 16)
    }
    setSearch(result.display_name.split(',').slice(0, 2).join(', '))
    setResults([])
  }

  // ── Map initialisation ──────────────────────────────────────────────
  useEffect(() => {
    if (mapObj.current || !mapRef.current) return

    // Start at continental US overview
    const map = L.map(mapRef.current, { center: [38.5, -97.0], zoom: 5, zoomControl: true })
    mapObj.current = map

    // ── Satellite imagery (Esri World Imagery — free, no API key) ─────
    // Shows actual farmland, fields, crops — NOT the road map
    L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      {
        attribution: 'Imagery © Esri, USGS, NOAA',
        maxZoom: 19,
      }
    ).addTo(map)

    // ── Thin labels overlay (roads + place names on top of satellite) ─
    L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
      { attribution: '', maxZoom: 19, opacity: 0.8 }
    ).addTo(map)

    // ── Drawing layer ─────────────────────────────────────────────────
    const drawnItems = new L.FeatureGroup()
    map.addLayer(drawnItems)
    drawnRef.current = drawnItems

    map.addControl(new L.Control.Draw({
      draw: {
        // Yellow outline stands out well against satellite imagery
        // Disable Leaflet Draw's area tooltip. leaflet-draw 1.0.4 has a
        // readableArea bug in the production bundle (undefined `type`).
        // Area is calculated server-side from the submitted GeoJSON.
        polygon:      {
          showArea: false,
          showLength: false,
          metric: false,
          feet: false,
          nautic: false,
          imperial: false,
          shapeOptions: { color: '#ffd700', weight: 2.5, fillOpacity: 0.15 },
        },
        rectangle:    {
          showArea: false,
          showLength: false,
          metric: false,
          feet: false,
          nautic: false,
          imperial: false,
          shapeOptions: { color: '#ffd700', weight: 2.5, fillOpacity: 0.15 },
        },
        polyline:     false,
        circle:       false,
        circlemarker: false,
        marker:       false,
      },
      edit: { featureGroup: drawnItems, remove: true },
    }))

    if (initialGeometry) {
      try {
        const layer = L.geoJSON({ type: 'Feature', geometry: initialGeometry })
        layer.eachLayer(l => drawnItems.addLayer(l))
        map.fitBounds(layer.getBounds(), { padding: [20, 20] })
      } catch (_) {}
    }

    map.on(L.Draw.Event.CREATED, (e) => {
      drawnItems.clearLayers()
      drawnItems.addLayer(e.layer)
      onPolygonChange(e.layer.toGeoJSON().geometry)
    })
    map.on(L.Draw.Event.EDITED, () => {
      const layers = drawnItems.getLayers()
      if (layers.length) onPolygonChange(layers[0].toGeoJSON().geometry)
    })
    map.on(L.Draw.Event.DELETED, () => onPolygonChange(null))

    setTimeout(() => map.invalidateSize(), 150)

    return () => { map.remove(); mapObj.current = null; drawnRef.current = null }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="map-wrapper">
      {/* ── Location search ───────────────────────────────────────── */}
      <div className="map-search-box">
        <div className="map-search-input-row">
          <span className="map-search-icon">🔍</span>
          <input
            type="text"
            className="map-search-input"
            placeholder="Search address, postcode, city, farm name…"
            value={search}
            onChange={handleSearchInput}
            onKeyDown={(e) => { if (e.key === 'Enter' && results.length) flyTo(results[0]) }}
            autoComplete="off"
          />
          {searching && <span className="map-search-spinner">⌛</span>}
          {search && !searching && (
            <button type="button" className="map-search-clear" onClick={() => { setSearch(''); setResults([]) }}>×</button>
          )}
        </div>
        {results.length > 0 && (
          <ul className="map-search-results">
            {results.map((r, i) => (
              <li key={i} className="map-search-result-item" onClick={() => flyTo(r)}>
                <span className="map-result-name">{r.display_name.split(',').slice(0, 3).join(', ')}</span>
                <span className="map-result-type">{r.type}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div ref={mapRef} className="leaflet-map-container" />
    </div>
  )
}


// ── Lat/Lon coordinate entry ──────────────────────────────────────────────────
function CoordinateEntry({ onPolygonChange }) {
  const [rows, setRows] = useState([
    { lat: '', lon: '' },
    { lat: '', lon: '' },
    { lat: '', lon: '' },
  ])
  const [coordError, setCoordError] = useState('')

  const updateRow = (i, field, val) => {
    setRows(prev => {
      const next = [...prev]
      next[i] = { ...next[i], [field]: val }
      return next
    })
  }

  const addRow = () => setRows(prev => [...prev, { lat: '', lon: '' }])

  const removeRow = (i) => {
    if (rows.length <= 3) return
    setRows(prev => prev.filter((_, idx) => idx !== i))
  }

  const buildPolygon = () => {
    setCoordError('')
    const filled = rows.filter(r => r.lat !== '' && r.lon !== '')
    if (filled.length < 3) {
      setCoordError('At least 3 coordinate pairs are required to form a polygon.')
      return
    }
    const coords = filled.map(r => {
      const lat = parseFloat(r.lat)
      const lon = parseFloat(r.lon)
      if (isNaN(lat) || isNaN(lon)) throw new Error('Invalid number')
      if (lat < -90 || lat > 90)  throw new Error(`Latitude ${lat} out of range`)
      if (lon < -180 || lon > 180) throw new Error(`Longitude ${lon} out of range`)
      return [lon, lat]   // GeoJSON uses [lon, lat]
    })
    // Close the ring
    if (
      coords[0][0] !== coords[coords.length - 1][0] ||
      coords[0][1] !== coords[coords.length - 1][1]
    ) {
      coords.push([...coords[0]])
    }
    onPolygonChange({ type: 'Polygon', coordinates: [coords] })
    setCoordError('')
  }

  return (
    <div className="coord-entry">
      <p className="coord-help">
        Enter corner points of your field boundary in WGS84 decimal degrees.
        At least 3 pairs required. Latitude: −90 to 90 · Longitude: −180 to 180.
        <br />
        <span className="coord-hint">
          Tip: find coordinates by right-clicking any location on Google Maps.
        </span>
      </p>

      <div className="coord-table">
        <div className="coord-header">
          <span>#</span>
          <span>Latitude (N/S)</span>
          <span>Longitude (E/W)</span>
          <span></span>
        </div>

        {rows.map((row, i) => (
          <div className="coord-row" key={i}>
            <span className="coord-num">{i + 1}</span>
            <input
              type="number"
              step="0.000001"
              placeholder="e.g. 41.5500"
              value={row.lat}
              onChange={e => updateRow(i, 'lat', e.target.value)}
              aria-label={`Latitude point ${i + 1}`}
            />
            <input
              type="number"
              step="0.000001"
              placeholder="e.g. −93.5500"
              value={row.lon}
              onChange={e => updateRow(i, 'lon', e.target.value)}
              aria-label={`Longitude point ${i + 1}`}
            />
            <button
              type="button"
              className="coord-remove"
              onClick={() => removeRow(i)}
              disabled={rows.length <= 3}
              aria-label="Remove row"
            >
              ×
            </button>
          </div>
        ))}
      </div>

      {coordError && <p className="coord-error">{coordError}</p>}

      <div className="coord-actions">
        <button type="button" className="coord-add-btn" onClick={addRow}>
          + Add Point
        </button>
        <button type="button" className="coord-apply-btn" onClick={buildPolygon}>
          Apply Boundary
        </button>
      </div>
    </div>
  )
}


// ── Main component ────────────────────────────────────────────────────────────
export default function FieldSetup() {
  const navigate = useNavigate()
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)
  const [mapTab,   setMapTab]   = useState('map')   // 'map' | 'coords'
  const [geometry, setGeometry] = useState(null)

  const [formData, setFormData] = useState({
    fieldName:       randomFieldName(),
    plantingDate:    '',
    hybridRM:        '',
    targetGDD:       '',
    irrigationType:  'rainfed',
    soilTest: {
      pH: '', organicMatter: '', phosphorus: '', potassium: '',
    },
  })

  const handleInputChange = (e) => {
    const { name, value } = e.target
    if (name.startsWith('soil_')) {
      const key = name.replace('soil_', '')
      setFormData(prev => ({
        ...prev,
        soilTest: { ...prev.soilTest, [key]: value },
      }))
    } else {
      setFormData(prev => ({ ...prev, [name]: value }))
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError(null)

    if (!geometry) {
      setError('Please define a field boundary — draw on the map or enter coordinates.')
      return
    }

    setLoading(true)
    try {
      const response = await fieldAPI.createField({
        fieldName:      formData.fieldName.trim() || randomFieldName(),
        geometry,
        plantingDate:   new Date(formData.plantingDate).toISOString(),
        hybridRM:       parseInt(formData.hybridRM, 10),
        targetGDD:      formData.targetGDD ? parseInt(formData.targetGDD, 10) : undefined,
        irrigationType: formData.irrigationType,
        soilTest:       Object.fromEntries(
          Object.entries(formData.soilTest).filter(([, v]) => v !== '')
        ),
      })
      navigate(`/field/${response.data.fieldId}`)
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to create field. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="field-setup">
      <h1>Add New Field</h1>
      {error && <div className="error-message" role="alert">{error}</div>}

      <form onSubmit={handleSubmit} className="setup-form">

        {/* ── Section 0: Field Name ────────────────────────────────────────── */}
        <section className="form-section">
          <h2>Field Name</h2>
          <div className="form-group">
            <FieldLabel
              htmlFor="fieldName"
              label="Monitoring Name"
              tooltip="Give this field a memorable name for your dashboard. Leave blank to use a randomly generated name."
            />
            <div className="name-input-row">
              <input
                type="text"
                id="fieldName"
                name="fieldName"
                value={formData.fieldName}
                onChange={handleInputChange}
                placeholder="e.g. North 40 Acres"
                maxLength={60}
              />
              <button
                type="button"
                className="randomise-btn"
                onClick={() => setFormData(p => ({ ...p, fieldName: randomFieldName() }))}
                title="Generate a random name"
              >
                🎲 Randomise
              </button>
            </div>
          </div>
        </section>

        {/* ── Section 1: Boundary ─────────────────────────────────────────── */}
        <section className="form-section">
          <h2>
            Field Boundary
            <Tooltip text="Draw the outline of your field on the map, or enter corner coordinates manually. The boundary is used to pull satellite imagery and calculate field area." />
          </h2>

          {/* Tab switcher */}
          <div className="boundary-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={mapTab === 'map'}
              className={`tab-btn ${mapTab === 'map' ? 'active' : ''}`}
              onClick={() => setMapTab('map')}
            >
              🗺 Draw on Map
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mapTab === 'coords'}
              className={`tab-btn ${mapTab === 'coords' ? 'active' : ''}`}
              onClick={() => setMapTab('coords')}
            >
              📍 Enter Coordinates
            </button>
          </div>

          {/* Map tab */}
          {mapTab === 'map' && (
            <div className="map-panel">
              <p className="map-instructions">
                Use the polygon tool (
                <strong>◻ Draw a polygon</strong> in the toolbar on the left of
                the map) to trace your field boundary. Click each corner, then
                click the first point again to close the shape.
              </p>
              <MapDrawer
                onPolygonChange={setGeometry}
                initialGeometry={geometry}
              />
            </div>
          )}

          {/* Coordinates tab */}
          {mapTab === 'coords' && (
            <CoordinateEntry onPolygonChange={setGeometry} />
          )}

          {/* Confirmation badge */}
          {geometry && (
            <div className="boundary-confirmed">
              ✓ Boundary set —{' '}
              {geometry.coordinates[0].length - 1} corner point
              {geometry.coordinates[0].length - 1 !== 1 ? 's' : ''}
            </div>
          )}
        </section>

        {/* ── Section 2: Crop ─────────────────────────────────────────────── */}
        <section className="form-section">
          <h2>Crop Information</h2>

          <div className="form-group">
            <FieldLabel
              htmlFor="plantingDate"
              label="Planting Date"
              required
              tooltip="The date seeds were planted in the ground. Used to calculate Growing Degree Days (GDD) and estimate current crop stage."
            />
            <input
              type="date"
              id="plantingDate"
              name="plantingDate"
              value={formData.plantingDate}
              onChange={handleInputChange}
              required
            />
          </div>

          <div className="form-group">
            <FieldLabel
              htmlFor="hybridRM"
              label="Hybrid Relative Maturity (RM)"
              required
              tooltip="A number (e.g. 95–115 for corn) indicating how long your hybrid takes to reach maturity relative to other hybrids. Found on the seed bag or your seed supplier's website."
            />
            <input
              type="number"
              id="hybridRM"
              name="hybridRM"
              min="70" max="130"
              value={formData.hybridRM}
              onChange={handleInputChange}
              placeholder="e.g. 105"
              required
            />
          </div>

          <div className="form-group">
            <FieldLabel
              htmlFor="targetGDD"
              label="Target GDD to Maturity"
              tooltip="Growing Degree Days required for this hybrid to reach physiological maturity (R6). If your seed supplier lists this, enter it here for a more accurate harvest forecast. Leave blank to auto-calculate from RM (RM × 24)."
            />
            <input
              type="number"
              id="targetGDD"
              name="targetGDD"
              min="1500" max="3500"
              value={formData.targetGDD}
              onChange={handleInputChange}
              placeholder="e.g. 2500 (auto-calculated if blank)"
            />
          </div>

          <div className="form-group">
            <FieldLabel
              htmlFor="irrigationType"
              label="Irrigation Type"
              required
              tooltip="Whether this field relies on rainfall only (rainfed) or has supplemental irrigation. Affects water stress calculations — if irrigated, you can log irrigation events later."
            />
            <select
              id="irrigationType"
              name="irrigationType"
              value={formData.irrigationType}
              onChange={handleInputChange}
            >
              <option value="rainfed">Rainfed (no irrigation)</option>
              <option value="irrigated">Irrigated</option>
            </select>
          </div>
        </section>

        {/* ── Section 3: Soil ─────────────────────────────────────────────── */}
        <section className="form-section">
          <h2>
            Soil Test Results
            <span className="optional-tag">optional</span>
            <Tooltip text="From your most recent soil test report, typically from a university extension lab or private lab. Values are used to refine AI recommendations. Leave blank if unavailable." />
          </h2>

          <div className="soil-grid">
            <div className="form-group">
              <FieldLabel
                htmlFor="soil_pH"
                label="Soil pH"
                tooltip="Acidity/alkalinity of the soil. Corn grows best at 6.0–7.0. Found on your soil test report. Low pH may indicate need for lime."
              />
              <input
                type="number" id="soil_pH" name="soil_pH"
                step="0.1" min="3" max="10"
                value={formData.soilTest.pH}
                onChange={handleInputChange}
                placeholder="e.g. 6.5"
              />
            </div>

            <div className="form-group">
              <FieldLabel
                htmlFor="soil_organicMatter"
                label="Organic Matter (%)"
                tooltip="Percentage of soil that is organic material. Higher OM improves water holding capacity and nutrient availability. Typical corn ground: 2–5%. From soil test report."
              />
              <input
                type="number" id="soil_organicMatter" name="soil_organicMatter"
                step="0.1" min="0" max="20"
                value={formData.soilTest.organicMatter}
                onChange={handleInputChange}
                placeholder="e.g. 3.2"
              />
            </div>

            <div className="form-group">
              <FieldLabel
                htmlFor="soil_phosphorus"
                label="Phosphorus P (ppm)"
                tooltip="Available phosphorus in parts-per-million. Corn needs adequate P for root development and early growth. Bray-1 or Mehlich-3 extractable P. From soil test report."
              />
              <input
                type="number" id="soil_phosphorus" name="soil_phosphorus"
                step="1" min="0"
                value={formData.soilTest.phosphorus}
                onChange={handleInputChange}
                placeholder="e.g. 45"
              />
            </div>

            <div className="form-group">
              <FieldLabel
                htmlFor="soil_potassium"
                label="Potassium K (ppm)"
                tooltip="Available potassium in parts-per-million. Critical for corn stalk quality and drought tolerance. From soil test report (exchangeable K)."
              />
              <input
                type="number" id="soil_potassium" name="soil_potassium"
                step="1" min="0"
                value={formData.soilTest.potassium}
                onChange={handleInputChange}
                placeholder="e.g. 180"
              />
            </div>
          </div>
        </section>

        {/* ── Submit ──────────────────────────────────────────────────────── */}
        <div className="form-actions">
          <button
            type="submit"
            className="submit-button"
            disabled={loading}
          >
            {loading ? 'Creating Field…' : 'Create Field & Start Monitoring'}
          </button>
        </div>
      </form>
    </div>
  )
}
