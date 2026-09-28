import React, { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { fieldAPI } from '../api/client'
import './FieldDashboard.css'

// ── Helpers ───────────────────────────────────────────────────────────────────
const fmt1    = (v) => (v != null ? Number(v).toFixed(1) : '—')
const fmt0    = (v) => (v != null ? Number(v).toFixed(0) : '—')
const fmt3    = (v) => (v != null ? Number(v).toFixed(3) : '—')
const fmtDate = (s) => s ? new Date(s).toLocaleDateString('en-US',
  { month: 'short', day: 'numeric', year: 'numeric' }) : '—'
const fmtPct  = (v) => (v != null ? `${(Number(v) * 100).toFixed(0)}%` : '—')

function scoreColor(score) {
  if (score == null) return '#999'
  if (score >= 70)   return '#2d7a2d'
  if (score >= 45)   return '#e68900'
  return '#c62828'
}

// ── Tooltip ────────────────────────────────────────────────────────────────────
function Tooltip({ text, dark }) {
  const [visible, setVisible] = useState(false)
  return (
    <span
      className={`tooltip-anchor ${dark ? 'tooltip-anchor-dark' : ''}`}
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

// ── Sub-components ────────────────────────────────────────────────────────────
function Card({ title, children, wide, className }) {
  return (
    <section className={`dash-card ${wide ? 'wide' : ''} ${className || ''}`}>
      <h2>{title}</h2>
      {children}
    </section>
  )
}

// ── Accordion (toggle) section ─────────────────────────────────────────────────
function Accordion({ title, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="accordion-section">
      <button
        type="button"
        className="accordion-header"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
      >
        <span>{title}</span>
        <span className={`accordion-chevron ${open ? 'open' : ''}`} aria-hidden="true">▾</span>
      </button>
      {open && <div className="accordion-body">{children}</div>}
    </section>
  )
}

function Row({ label, value, unit, accent }) {
  return (
    <div className="dash-row">
      <span className="dash-label">{label}</span>
      <span className={`dash-value ${accent ? 'accent' : ''}`}>
        {value}{unit ? <span className="dash-unit"> {unit}</span> : null}
      </span>
    </div>
  )
}

function PendingNote() {
  return <p className="pending-note">⏳ Available after first batch run</p>
}

// ── Boundary map image ────────────────────────────────────────────────────────
function BoundaryMapImage({ url, fieldName }) {
  const [err, setErr] = useState(false)
  if (!url || err) {
    return (
      <div className="boundary-placeholder">
        <span>🗺</span>
        <p>Boundary map generates on next field creation</p>
      </div>
    )
  }
  return (
    <img
      src={url}
      alt={`Boundary map for ${fieldName || 'field'}`}
      className="boundary-map-img"
      onError={() => setErr(true)}
    />
  )
}

// ── Satellite gallery ─────────────────────────────────────────────────────────
function SatelliteGallery({ fieldId }) {
  const [observations, setObs]     = useState([])
  const [loading,      setLoading] = useState(true)
  const [selected,     setSelected] = useState(0)
  const [activeIndex,  setActiveIndex] = useState('ndvi')
  const [lightboxOpen, setLightboxOpen] = useState(false)

  useEffect(() => {
    fieldAPI.getObservations(fieldId)
      .then(r => {
        setObs(r.data.observations || [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [fieldId])

  // Close lightbox on Escape key
  useEffect(() => {
    const handleEscape = (e) => {
      if (e.key === 'Escape') setLightboxOpen(false)
    }
    if (lightboxOpen) window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  }, [lightboxOpen])

  if (loading) return <p className="pending-note">Loading satellite images…</p>
  if (!observations.length) return <PendingNote />

  const obs     = observations[selected]
  const imgUrl  = obs?.previewUrls?.[activeIndex]
  const indices = ['ndvi', 'ndmi', 'ndre']
  const indexLabels = { ndvi: 'NDVI (Vegetation)', ndmi: 'NDMI (Moisture)', ndre: 'NDRE (Chlorophyll)' }

  return (
    <>
      <div className="sat-gallery">
        {/* Main image viewer */}
        <div className="sat-main">
          <div className="sat-index-tabs">
            {indices.map(idx => (
              <button
                key={idx}
                className={`sat-tab ${activeIndex === idx ? 'active' : ''}`}
                onClick={() => setActiveIndex(idx)}
              >
                {idx.toUpperCase()}
              </button>
            ))}
          </div>
          {imgUrl ? (
            <img
              src={imgUrl}
              alt={`${indexLabels[activeIndex]} — ${obs.observationDate}`}
              className="sat-preview-img"
              onClick={() => setLightboxOpen(true)}
              title="Click to expand"
              style={{ cursor: 'pointer' }}
            />
          ) : (
            <div className="sat-no-preview">
              <p>No preview available for this scene</p>
            </div>
          )}
          <div className="sat-caption">
            <span className="sat-index-name">{indexLabels[activeIndex]}</span>
            <span className="sat-scene-meta">
              {fmtDate(obs?.observationDate)} &nbsp;·&nbsp;
              ☁ {fmt1(obs?.sceneCloudPct)}% cloud &nbsp;·&nbsp;
              {obs?.quality} quality
            </span>
          </div>
          {/* Index values for selected scene */}
          <div className="sat-index-row">
            {obs?.ndvi_mean != null && <span className="sat-idx">NDVI {fmt3(obs.ndvi_mean)}</span>}
            {obs?.ndmi_mean != null && <span className="sat-idx">NDMI {fmt3(obs.ndmi_mean)}</span>}
            {obs?.ndre_mean != null && <span className="sat-idx">NDRE {fmt3(obs.ndre_mean)}</span>}
          </div>
        </div>

        {/* Thumbnail strip — up to 7 scenes */}
        <div className="sat-strip">
          {observations.map((o, i) => (
            <button
              key={i}
              className={`sat-thumb-btn ${selected === i ? 'selected' : ''}`}
              onClick={() => setSelected(i)}
              title={`${o.observationDate} — ${fmt1(o.sceneCloudPct)}% cloud`}
            >
              {o.previewUrls?.ndvi ? (
                <img
                  src={o.previewUrls.ndvi}
                  alt={o.observationDate}
                  className="sat-thumb-img"
                />
              ) : (
                <div className="sat-thumb-empty">
                  <span>{new Date(o.observationDate).toLocaleDateString('en-US',
                    { month: 'short', day: 'numeric' })}</span>
                </div>
              )}
              <div className="sat-thumb-date">
                {new Date(o.observationDate).toLocaleDateString('en-US',
                  { month: 'short', day: 'numeric' })}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Lightbox modal */}
      {lightboxOpen && imgUrl && (
        <div className="lightbox-overlay" onClick={() => setLightboxOpen(false)}>
          <div className="lightbox-content" onClick={(e) => e.stopPropagation()}>
            <button className="lightbox-close" onClick={() => setLightboxOpen(false)}>
              ✕
            </button>
            <div className="lightbox-title">
              {indexLabels[activeIndex]}
              <span className="lightbox-date">{fmtDate(obs.observationDate)}</span>
            </div>
            <img src={imgUrl} alt={indexLabels[activeIndex]} className="lightbox-img" />
            <div className="lightbox-controls">
              <div className="lightbox-tabs">
                {indices.map(idx => (
                  <button
                    key={idx}
                    className={`lightbox-tab ${activeIndex === idx ? 'active' : ''}`}
                    onClick={() => setActiveIndex(idx)}
                  >
                    {idx.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ── Main dashboard ────────────────────────────────────────────────────────────
export default function FieldDashboard() {
  const { fieldId } = useParams()
  const [field,      setField]      = useState(null)
  const [status,     setStatus]     = useState(null)
  const [loading,    setLoading]    = useState(true)

  useEffect(() => {
    load()
    const iv = setInterval(load, 60_000)
    return () => clearInterval(iv)
  }, [fieldId]) // eslint-disable-line

  const load = async () => {
    // Fetch field and status independently — don't let one failure kill the other
    const [fieldRes, statusRes] = await Promise.allSettled([
      fieldAPI.getField(fieldId),
      fieldAPI.getLatestStatus(fieldId),
    ])
    if (fieldRes.status  === 'fulfilled') setField(fieldRes.value.data)
    if (statusRes.status === 'fulfilled') {
      const d = statusRes.value.data
      // Guard: ignore batch-log payloads that accidentally land here
      if (d.statusDate || d.weather || d.metrics) setStatus(d)
    }
    setLoading(false)
  }

  // ── Loading ────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="dash-page">
        <div className="dash-loading">Loading field data…</div>
      </div>
    )
  }

  // ── No field found at all ──────────────────────────────────────────────────
  if (!field) {
    return (
      <div className="dash-page">
        <div className="dash-empty">
          <p>Field not found.</p>
        </div>
      </div>
    )
  }

  // ── Derived values ─────────────────────────────────────────────────────────
  const planting  = field.plantingDate ? fmtDate(field.plantingDate) : '—'
  const areaAcres = field.areaAcres    ? `${Number(field.areaAcres).toFixed(1)} ac` : '—'
  const soilTest  = field.soilTest || {}
  const hasSoil   = Object.keys(soilTest).length > 0
  const location  = field.location || {}
  const fieldName = field.fieldName || `Field ${fieldId?.slice(0,8)}`

  const wx        = status?.weather  || {}
  const metrics   = status?.metrics  || {}
  const sat       = status?.satellite
  const ai        = status?.aiBrief
  const vision    = status?.visionAnalysis
  const fc        = status?.forecast || []
  const isPending = status?.source === 'initial_seed'

  function C2F(c) { return Math.round((c * 9/5 + 32) * 10) / 10 }
  const tminF = wx.tmin_f ?? (wx.tmin_c != null ? C2F(wx.tmin_c) : null)
  const tmaxF = wx.tmax_f ?? (wx.tmax_c != null ? C2F(wx.tmax_c) : null)

  return (
    <div className="dash-page">

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="dash-header">
        <div className="dash-title">
          <h1>{fieldName}</h1>
          <p className="dash-subtitle">
            {location.displayName && <><span className="dash-location">📍 {location.displayName}</span><span className="dash-sep"> · </span></>}
            <span>{Number(field.centroidLat || 0).toFixed(4)}°, {Number(field.centroidLon || 0).toFixed(4)}°</span>
            <span className="dash-sep"> · </span><span>{areaAcres}</span>
            <span className="dash-sep"> · </span><span>Created {fmtDate(field.createdAt)}</span>
          </p>
        </div>
      </div>

      {isPending && (
        <div className="init-banner">
          ✓ Field created — weather data loaded. Run the batch pipeline for satellite imagery, full analysis, and AI recommendations.
        </div>
      )}

      {/* ── Harvest estimate summary ─────────────────────────────────── */}
      {metrics.harvestWindow?.estimatedDate && (
        <div className="harvest-summary">
          <div className="harvest-summary-item">
            <span className="hs-label">Estimated Harvest Date</span>
            <span className="hs-value">{fmtDate(metrics.harvestWindow?.estimatedDate)}</span>
            {metrics.harvestWindow?.earliestDate && metrics.harvestWindow?.latestDate && (
              <span className="hs-range">
                Range: {fmtDate(metrics.harvestWindow.earliestDate)} – {fmtDate(metrics.harvestWindow.latestDate)}
              </span>
            )}
          </div>
        </div>
      )}

      {/* ══ Section 1: Overview — Field Map row + 7-Day Forecast ═══════ */}
      <Accordion title="Overview" defaultOpen={true}>
        <div className="dash-top-row">

          {/* ── Field Map ──────────────────────────────────────────────── */}
          <Card title="Field Map">
            <BoundaryMapImage url={field.boundaryMapUrl} fieldName={fieldName} />
            <div className="coords-line">
              <span className="coord-tag">Lat</span>{Number(field.centroidLat || 0).toFixed(5)}
              <span className="coord-tag ml">Lon</span>{Number(field.centroidLon || 0).toFixed(5)}
            </div>
          </Card>

          {/* ── Field Overview ─────────────────────────────────────────── */}
          <Card title="Field Overview">
            {location.displayName && (
              <div className="location-line">
                <span className="loc-icon">📍</span>
                <span>{location.displayName}</span>
              </div>
            )}
            <Row label="Area"          value={areaAcres} />
            <Row label="Planting date" value={planting} />
            <Row label="Hybrid RM"     value={field.hybridRM} unit="RM" accent />
            <Row label="Irrigation"    value={field.irrigationType === 'irrigated' ? 'Irrigated' : 'Rainfed'} />
            {hasSoil && <>
              {soilTest.pH             && <Row label="Soil pH"     value={soilTest.pH} />}
              {soilTest.organicMatter  && <Row label="Org. matter" value={soilTest.organicMatter} unit="%" />}
              {soilTest.phosphorus     && <Row label="Phosphorus"  value={soilTest.phosphorus}    unit="ppm" />}
              {soilTest.potassium      && <Row label="Potassium"   value={soilTest.potassium}     unit="ppm" />}
            </>}
          </Card>

          {/* ── Today's Weather ─────────────────────────────────────────── */}
          <Card title="Today's Weather">
            {tminF != null || tmaxF != null ? <>
              <Row label="Temperature"   value={`${fmt1(tminF)} – ${fmt1(tmaxF)}`} unit="°F" />
              <Row label="Precipitation" value={fmt1(wx.precipitation_mm)} unit="mm" />
              <Row label="Solar rad."    value={fmt1(wx.radiation_mj)}     unit="MJ/m²" />
              <Row label="Reference ET₀" value={fmt1(wx.et0_mm)}           unit="mm" />
              <Row label="Daily GDD"     value={fmt1(wx.gddDaily)}         unit="GDD" accent />
              {wx.weatherDate && <p className="wx-date">Observed: {fmtDate(wx.weatherDate)}</p>}
            </> : <p className="no-data">No weather data yet</p>}
          </Card>

        </div>

        {/* ── 7-Day Forecast ──────────────────────────────────────────── */}
        {fc.length > 0 && (
          <div className="dash-grid">
            <Card title="7-Day Forecast" wide>
              <div className="forecast-row">
                {fc.map((day, i) => (
                  <div key={i} className="forecast-day">
                    <div className="fc-date">{new Date(day.weatherDate).toLocaleDateString('en-US',
                      { weekday: 'short', month: 'short', day: 'numeric' })}</div>
                    <div className="fc-temp">{fmt0(day.tmax_f)}° / {fmt0(day.tmin_f)}°</div>
                    {Number(day.precipitation_mm) > 0 &&
                      <div className="fc-rain">🌧 {fmt1(day.precipitation_mm)} mm</div>}
                  </div>
                ))}
              </div>
            </Card>
          </div>
        )}
      </Accordion>

      {/* ══ Section 2: Observation — Growth Stage row ══════════════════ */}
      <Accordion title="Observation" defaultOpen={true}>
        <div className="dash-grid">

          {/* ── Growth Stage ────────────────────────────────────────────── */}
          <Card title="Growth Stage">
            {metrics.estimatedStage ? <>
              <div className="stage-badge">{metrics.estimatedStage}</div>
              <Row label="GDD accumulated"  value={fmt0(metrics.gddAccumulated)} unit="GDD" accent />
              <Row label="Days since plant" value={metrics.daysSincePlanting} />
              <Row label="Daily GDD"        value={fmt1(metrics.gddDaily)} unit="GDD" />
              {metrics.maturityForecast?.predictedDate &&
                <Row label="Predicted R6" value={fmtDate(metrics.maturityForecast.predictedDate)} />}
              {metrics.harvestWindow?.estimatedDate &&
                <Row label="Est. harvest" value={fmtDate(metrics.harvestWindow.estimatedDate)} accent />}
            </> : <PendingNote />}
          </Card>

          {/* ── Crop Health ─────────────────────────────────────────────── */}
          <Card title="Crop Health">
            {metrics.healthScore != null ? <>
              <div className="health-ring" style={{ '--score-color': scoreColor(metrics.healthScore) }}>
                <div className="health-score">{metrics.healthScore}<span>/100</span></div>
                <div className="health-conf">{metrics.healthScoreConfidence || ''}</div>
              </div>
              <Row label="Water stress" value={fmtPct(metrics.waterStressScore)} />
              <Row label="Heat stress"  value={metrics.heatStress?.heatStressSeverity || '—'} />
            </> : <PendingNote />}
          </Card>

          {/* ── Satellite Latest Indices ─────────────────────────────────── */}
          <Card title="Latest Satellite Indices">
            {sat?.status === 'success' ? <>
              <Row label="NDVI (vegetation)"  value={fmt3((sat.indices?.ndvi?.mean))} accent />
              <Row label="NDMI (moisture)"    value={fmt3((sat.indices?.ndmi?.mean))} />
              <Row label="NDRE (chlorophyll)" value={fmt3((sat.indices?.ndre?.mean))} />
              <Row label="Valid pixels"       value={fmtPct(sat.validPixelFraction)} />
              <Row label="Cloud cover"        value={fmt1(sat.sceneCloudPct)} unit="%" />
              {sat.observationDate &&
                <p className="wx-date">Scene: {fmtDate(sat.observationDate)}</p>}
            </> : <PendingNote />}
          </Card>

          {/* ── Water Balance ────────────────────────────────────────────── */}
          <Card title="Water Balance">
            {status?.et?.cumulativeDeficit_mm != null ? <>
              <Row label="Cumulative deficit" value={fmt0(status.et.cumulativeDeficit_mm)} unit="mm" accent />
              <Row label="Water stress"       value={fmtPct(status.et.waterStressScore)} />
              <Row label="ET source"          value={status.et.source === 'openet' ? 'OpenET' : 'ET₀ estimate'} />
            </> : <PendingNote />}
          </Card>

        </div>
      </Accordion>

      {/* ══ Section 3: Analysis — AI Brief → Satellite Images → Trend ══ */}
      <Accordion title="Analysis" defaultOpen={true}>
        <div className="dash-grid">

        {/* ── AI Brief (Detailed Crop Posture & Health Analysis) ───────────── */}
        <Card title="AI Brief & Crop Analysis" wide>
          {ai?.summary && ai.summary !== 'AI brief generation unavailable. Review metrics manually.' ? <>
            {/* Executive summary */}
            <p className="ai-summary">{ai.summary}</p>

            {/* New detailed sections (if available) */}
            {ai.cropPostureAnalysis && (
              <div className="ai-section">
                <h3>Crop Posture</h3>
                <div className="ai-posture">
                  {ai.cropPostureAnalysis.currentStage && (
                    <div className="posture-row">
                      <strong>Stage:</strong> {ai.cropPostureAnalysis.currentStage}
                      {ai.cropPostureAnalysis.maturityProgress && (
                        <span className="posture-status"> ({ai.cropPostureAnalysis.maturityProgress})</span>
                      )}
                    </div>
                  )}
                  {ai.cropPostureAnalysis.canopyCondition && (
                    <div className="posture-row">
                      <strong>Canopy:</strong> {ai.cropPostureAnalysis.canopyCondition}
                    </div>
                  )}
                  {ai.cropPostureAnalysis.stressIndicators?.length > 0 && (
                    <div className="posture-row">
                      <strong>Stress:</strong> {ai.cropPostureAnalysis.stressIndicators.join(', ')}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Health diagnosis */}
            {ai.healthDiagnosis && (
              <div className="ai-section">
                <h3>Health Diagnosis</h3>
                <div className="ai-health">
                  {ai.healthDiagnosis.overallHealthRating && (
                    <div className="health-row">
                      <strong>Rating:</strong> <span className={`health-badge ${ai.healthDiagnosis.overallHealthRating.toLowerCase()}`}>
                        {ai.healthDiagnosis.overallHealthRating}
                      </span>
                    </div>
                  )}
                  {ai.healthDiagnosis.primaryConcerns?.length > 0 && (
                    <div className="health-row">
                      <strong>Concerns:</strong>
                      <ul className="compact-list">
                        {ai.healthDiagnosis.primaryConcerns.map((c, i) => <li key={i}>{c}</li>)}
                      </ul>
                    </div>
                  )}
                  {ai.healthDiagnosis.rootCauses?.length > 0 && (
                    <div className="health-row">
                      <strong>Root Causes:</strong>
                      <ul className="compact-list">
                        {ai.healthDiagnosis.rootCauses.map((c, i) => <li key={i}>{c}</li>)}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Next 48h outlook */}
            {ai.next48hForecast && (
              <div className="ai-section">
                <h3>Next 48 Hours</h3>
                <div className="ai-forecast">
                  {ai.next48hForecast.rainfall_mm != null && (
                    <div className="forecast-row">
                      <strong>Expected rainfall:</strong> {ai.next48hForecast.rainfall_mm} mm
                    </div>
                  )}
                  {ai.next48hForecast.sunlightExpectation && (
                    <div className="forecast-row">
                      <strong>Sunlight:</strong> {ai.next48hForecast.sunlightExpectation}
                    </div>
                  )}
                  {ai.next48hForecast.waterSupplyOutlook && (
                    <div className="forecast-row">
                      <strong>Water supply:</strong> {ai.next48hForecast.waterSupplyOutlook}
                    </div>
                  )}
                  {ai.next48hForecast.actionsDuringNextTwoDays?.length > 0 && (
                    <div className="forecast-row">
                      <strong>Actions:</strong>
                      <ul className="compact-list">
                        {ai.next48hForecast.actionsDuringNextTwoDays.map((a, i) => <li key={i}>{a}</li>)}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Interventions (fertilizer, irrigation, pest) */}
            {ai.interventions && (
              <div className="ai-section">
                <h3>Recommended Interventions</h3>
                <div className="ai-interventions">
                  {ai.interventions.fertiliserRecommendations && (
                    <div className="intervention-block">
                      <strong>Fertilizer:</strong>
                      <div className="indent">
                        {ai.interventions.fertiliserRecommendations.timing && (
                          <p><span className="label">Timing:</span> {ai.interventions.fertiliserRecommendations.timing}</p>
                        )}
                        {ai.interventions.fertiliserRecommendations.npkGuidance && (
                          <p><span className="label">NPK:</span> {ai.interventions.fertiliserRecommendations.npkGuidance}</p>
                        )}
                        {ai.interventions.fertiliserRecommendations.micronutrients && (
                          <p><span className="label">Micronutrients:</span> {ai.interventions.fertiliserRecommendations.micronutrients}</p>
                        )}
                        {ai.interventions.fertiliserRecommendations.rationale && (
                          <p className="rationale"><em>{ai.interventions.fertiliserRecommendations.rationale}</em></p>
                        )}
                      </div>
                    </div>
                  )}
                  {ai.interventions.irrigationAdvisory && (
                    <div className="intervention-block">
                      <strong>Irrigation:</strong>
                      <p className="indent">{ai.interventions.irrigationAdvisory}</p>
                    </div>
                  )}
                  {ai.interventions.pestDiseasePrevention?.length > 0 && (
                    <div className="intervention-block">
                      <strong>Pest/Disease Prevention:</strong>
                      <ul className="compact-list indent">
                        {ai.interventions.pestDiseasePrevention.map((p, i) => <li key={i}>{p}</li>)}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Legacy format fallback */}
            {!ai.cropPostureAnalysis && ai.top_risks?.length > 0 && (
              <div className="ai-cols">
                {ai.top_risks?.length > 0 && (
                  <div><h3>Top Risks</h3>
                    <ul>{ai.top_risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
                  </div>
                )}
                {ai.recommended_actions?.length > 0 && (
                  <div><h3>Recommended Actions</h3>
                    <ul>{ai.recommended_actions.map((a, i) => <li key={i}>{a}</li>)}</ul>
                  </div>
                )}
              </div>
            )}

            {/* Confidence */}
            {ai.confidence && (
              <div className="ai-confidence">
                Confidence: <strong>{ai.confidence}</strong> — {ai.confidence_reason}
              </div>
            )}
          </> : (
            <div className="ai-pending">
              <p>🤖 AI crop analysis will appear here after the next batch run.</p>
            </div>
          )}
        </Card>

        {/* ── Satellite Image Gallery ─────────────────────────────────── */}
        <Card title="Satellite Image History (Last 7 Scenes)" wide>
          <SatelliteGallery fieldId={fieldId} />
        </Card>

        {/* ── Image Trend Analysis (AI vision over last 7 captures) ────── */}
        <Card title="Satellite Image Trend Analysis" wide>
          {vision?.summary ? <>
            <div className="vision-trend-header">
              <span className={`trend-badge trend-${(vision.overallTrend || 'unknown').toLowerCase()}`}>
                {vision.overallTrend || 'unknown'}
              </span>
              <span className="vision-meta">
                {vision.capturesAnalyzed} capture{vision.capturesAnalyzed === 1 ? '' : 's'} analyzed
                {vision.latestObservationDate && <> · latest {fmtDate(vision.latestObservationDate)}</>}
              </span>
            </div>

            <p className="ai-summary">{vision.summary}</p>

            {vision.perCaptureNotes?.length > 0 && (
              <div className="ai-section">
                <h3>Capture-by-Capture Notes</h3>
                <ul className="compact-list">
                  {vision.perCaptureNotes.map((n, i) => (
                    <li key={i}><strong>{fmtDate(n.date)}:</strong> {n.observation}</li>
                  ))}
                </ul>
              </div>
            )}

            {vision.keyChanges?.length > 0 && (
              <div className="ai-section">
                <h3>Key Changes</h3>
                <ul className="compact-list">
                  {vision.keyChanges.map((c, i) => <li key={i}>{c}</li>)}
                </ul>
              </div>
            )}

            {vision.suggestions?.length > 0 && (
              <div className="ai-section">
                <h3>Suggestions</h3>
                <ul className="compact-list">
                  {vision.suggestions.map((s, i) => <li key={i}>{s}</li>)}
                </ul>
              </div>
            )}

            {vision.confidence && (
              <div className="ai-confidence">
                Confidence: <strong>{vision.confidence}</strong>
                {vision.confidenceReason && <> — {vision.confidenceReason}</>}
              </div>
            )}
          </> : (
            <div className="ai-pending">
              <p>🛰 Image trend analysis will appear here once satellite captures are available.</p>
            </div>
          )}
        </Card>

        </div>
      </Accordion>

      {/* ══ Section 4: Checklist ════════════════════════════════════════ */}
      <Accordion title="Checklist" defaultOpen={true}>
        <div className="dash-grid">
          {(ai?.scouting_checklist?.length > 0 || ai?.scoutingChecklist?.length > 0) ? (
            <Card title="Scouting Checklist" wide>
              <ul className="checklist">
                {(ai.scouting_checklist || ai.scoutingChecklist)?.map((item, i) => (
                  <li key={i}>
                    <input type="checkbox" id={`chk-${i}`} />
                    <label htmlFor={`chk-${i}`}>{item}</label>
                  </li>
                ))}
              </ul>
            </Card>
          ) : (
            <Card title="Scouting Checklist" wide>
              <PendingNote />
            </Card>
          )}
        </div>
      </Accordion>
    </div>
  )
}
