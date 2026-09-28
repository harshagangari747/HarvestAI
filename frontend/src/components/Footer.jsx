import { Link } from 'react-router-dom'
import './Footer.css'

export default function Footer() {
  const year = new Date().getFullYear()

  return (
    <footer className="site-footer">
      <div className="footer-container">
        <div className="footer-brand">
          <div className="footer-logo">
            <span className="logo-mark">H</span>
            HarvestAI
          </div>
          <p className="footer-tagline">
            Precision crop monitoring powered by satellite imagery, weather
            modeling, and AI analysis.
          </p>
        </div>

        <div className="footer-links">
          <div className="footer-col">
            <span className="footer-col-title">Product</span>
            <Link to="/">Home</Link>
            <a href="/#methodology">Methodology</a>
          </div>
          <div className="footer-col">
            <span className="footer-col-title">Data Sources</span>
            <span className="footer-static-link">Sentinel-2 (ESA Copernicus)</span>
            <span className="footer-static-link">Open-Meteo</span>
            <span className="footer-static-link">Amazon Bedrock</span>
          </div>
        </div>
      </div>

      <div className="footer-bottom">
        <span>&copy; {year} HarvestAI. All rights reserved.</span>
        <span className="footer-disclaimer">
          Forecasts and yield estimates are model-based guidance, not a guarantee.
        </span>
      </div>
    </footer>
  )
}
