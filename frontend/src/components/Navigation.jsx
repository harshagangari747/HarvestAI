import React from 'react'
import { Link } from 'react-router-dom'
import './Navigation.css'

export default function Navigation() {
  return (
    <nav className="navbar">
      <div className="navbar-container">
        <Link to="/" className="navbar-logo">
          <span className="logo-mark">H</span>
          HarvestAI
        </Link>
        <div className="navbar-menu">
          <Link to="/" className="nav-link">Home</Link>
        </div>
      </div>
    </nav>
  )
}
