import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { fieldAPI } from '../api/client'
import Footer from '../components/Footer'
import './LandingPage.css'

// ── Score badge colour ────────────────────────────────────────────────────────
function scoreStyle(score) {
  if (score == null) return { background: '#f0f0f0', color: '#888' }
  if (score >= 70)   return { background: '#e8f5e1', color: '#2d7a2d' }
  if (score >= 45)   return { background: '#fff3e0', color: '#e65100' }
  return               { background: '#ffebee', color: '#c62828' }
}

// ── Single field card ─────────────────────────────────────────────────────────
function FieldCard({ field }) {
  const s   = field.statusSummary || {}
  const score     = s.healthScore
  const stage     = s.estimatedStage || '—'
  const days      = s.daysSincePlanting
  const lastDate  = s.lastStatusDate || field.createdAt?.slice(0,10)
  const area      = field.areaAcres   ? `${Number(field.areaAcres).toFixed(1)} ac` : ''

  return (
    <Link to={`/field/${field.fieldId}`} className="field-card">
      <div className="field-card-header">
        <div className="field-card-meta">
          <span className="field-card-name">{field.fieldName || `Field ${field.fieldId?.slice(0,8)}`}</span>
        </div>
        {score != null
          ? <div className="field-card-score" style={scoreStyle(score)}>{score}<span>/100</span></div>
          : <div className="field-card-score" style={scoreStyle(null)}>—</div>}
      </div>

      <div className="field-card-sub">
        <span className="field-card-rm">RM {field.hybridRM}</span>
        {area && <span className="field-card-area">{area}</span>}
        {field.location?.displayName && (
          <span className="field-card-loc">{field.location.displayName}</span>
        )}
      </div>

      <div className="field-card-stage">{stage}</div>

      <div className="field-card-footer">
        <div className="field-card-row">
          <span className="fc-label">Planted</span>
          <span>{field.plantingDate?.slice(0,10) || '—'}</span>
        </div>
        <div className="field-card-row">
          <span className="fc-label">Days in field</span>
          <span>{days ?? '—'}</span>
        </div>
        <div className="field-card-row">
          <span className="fc-label">Last update</span>
          <span>{lastDate || '—'}</span>
        </div>
        <div className="field-card-row">
          <span className="fc-label">Irrigation</span>
          <span>{field.irrigationType === 'irrigated' ? 'Irrigated' : 'Rainfed'}</span>
        </div>
      </div>

      <div className="field-card-cta">View Dashboard →</div>
    </Link>
  )
}


// ── Landing page ──────────────────────────────────────────────────────────────
export default function LandingPage() {
  const [fields,  setFields]  = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fieldAPI.listFields()
      .then(r => setFields(r.data.fields || []))
      .catch(() => setFields([]))
      .finally(() => setLoading(false))
  }, [])

  const hasFields = fields.length > 0

  return (
    <div className="landing-page">

      {/* ── Hero ──────────────────────────────────────────────────────────── */}
      <section className="hero">
        <div className="hero-media" aria-hidden="true" />
        <div className="hero-overlay" />
        <div className="hero-content">
          <span className="hero-eyebrow">Precision Crop Monitoring</span>
          <h1>Know what's happening in your corn field before it costs you yield</h1>
          <p>
            HarvestAI tracks every field through the growing season using satellite
            imagery, weather modeling, and AI analysis — surfacing the moments that
            need a decision instead of leaving you to piece it together from a dozen
            different sources.
          </p>
          <div className="hero-actions">
            <a href="#methodology" className="cta-button-secondary">See how it works</a>
          </div>
        </div>
      </section>

      {/* ── Problem ─────────────────────────────────────────────────────────── */}
      <section className="narrative-section problem-section">
        <div className="narrative-inner">
          <span className="section-eyebrow">The Problem</span>
          <h2>Crop stress rarely announces itself in time</h2>
          <div className="problem-grid">
            <div className="problem-item">
              <span className="problem-index">01</span>
              <h3>Ground-level scouting is too slow</h3>
              <p>
                Walking a field only shows you what's visibly wrong, and by the
                time stress is visible from the ground, yield potential may
                already be lost.
              </p>
            </div>
            <div className="problem-item">
              <span className="problem-index">02</span>
              <h3>Data lives in disconnected places</h3>
              <p>
                Weather forecasts, soil reports, and imagery each come from a
                different tool, making it hard to see the full picture before
                acting.
              </p>
            </div>
            <div className="problem-item">
              <span className="problem-index">03</span>
              <h3>Irrigation and inputs get decided on guesswork</h3>
              <p>
                Without a clear read on water balance and canopy health,
                fertilizer and irrigation timing default to habit rather than
                actual field conditions.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── Solution ────────────────────────────────────────────────────────── */}
      <section className="narrative-section solution-section">
        <div className="narrative-inner">
          <span className="section-eyebrow">The Solution</span>
          <h2>One dashboard, updated automatically, for every field you grow</h2>
          <p className="solution-lede">
            HarvestAI runs a daily pipeline behind the scenes so that by the time
            you open the dashboard, the analysis is already done — not raw data
            you have to interpret yourself.
          </p>
          <div className="solution-grid">
            <div className="solution-card">
              <h3>Continuous tracking</h3>
              <p>
                Every active field is re-evaluated daily against the latest
                satellite pass, weather observations, and water balance —
                no manual refresh required.
              </p>
            </div>
            <div className="solution-card">
              <h3>Plain-language guidance</h3>
              <p>
                Instead of raw index values, you get a written brief covering
                crop posture, health diagnosis, and near-term actions worth
                taking.
              </p>
            </div>
            <div className="solution-card">
              <h3>History you can compare</h3>
              <p>
                Recent satellite captures are kept side by side so trends —
                improving, declining, or stable — are visible at a glance
                rather than inferred from memory.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── Methodology ─────────────────────────────────────────────────────── */}
      <section className="narrative-section methodology-section" id="methodology">
        <div className="narrative-inner">
          <span className="section-eyebrow">Methodology</span>
          <h2>How each field is monitored</h2>
          <p className="solution-lede">
            A single pipeline runs for every field, combining four independent
            data sources into one assessment.
          </p>

          <div className="method-steps">
            <div className="method-step">
              <div className="method-marker">1</div>
              <div className="method-body">
                <h3>Satellite imagery</h3>
                <p>
                  Sentinel-2 scenes are pulled for the field boundary and
                  processed into NDVI, NDMI, and NDRE index maps — measuring
                  vegetation vigor, moisture content, and chlorophyll levels
                  respectively. Cloud-affected pixels are filtered out before
                  any index is calculated.
                </p>
              </div>
            </div>
            <div className="method-step">
              <div className="method-marker">2</div>
              <div className="method-body">
                <h3>Weather and growing degree days</h3>
                <p>
                  Observed and forecast weather is combined with the field's
                  planting date and hybrid maturity rating to accumulate
                  growing degree days, estimate current growth stage, and
                  flag upcoming heat stress.
                </p>
              </div>
            </div>
            <div className="method-step">
              <div className="method-marker">3</div>
              <div className="method-body">
                <h3>Water balance</h3>
                <p>
                  Evapotranspiration data is used to track cumulative water
                  deficit against rainfall, producing a water stress score
                  that informs irrigation timing.
                </p>
              </div>
            </div>
            <div className="method-step">
              <div className="method-marker">4</div>
              <div className="method-body">
                <h3>AI-generated analysis</h3>
                <p>
                  A language model reviews the combined metrics to write a
                  daily brief, and a vision model compares the most recent
                  satellite captures directly to describe what's changing
                  in the canopy over time.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Active Fields ─────────────────────────────────────────────────── */}
      <section className="fields-section">
        <div className="fields-header">
          <h2>
            {hasFields
              ? `Active Fields (${fields.length})`
              : 'No Fields Yet'}
          </h2>
        </div>

        {loading ? (
          <div className="fields-loading">Loading fields…</div>
        ) : hasFields ? (
          <div className="fields-grid">
            {fields.map(f => <FieldCard key={f.fieldId} field={f} />)}
          </div>
        ) : (
          <div className="fields-empty">
            <p>You haven't added any fields yet.</p>
          </div>
        )}
      </section>

      <Footer />

    </div>
  )
}
