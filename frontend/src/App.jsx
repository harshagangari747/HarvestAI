import React from 'react'
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import FieldSetup from './pages/FieldSetup'
import FieldDashboard from './pages/FieldDashboard'
import Navigation from './components/Navigation'
import './App.css'

function App() {
  return (
    <Router>
      <div className="app-container">
        <Navigation />
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/field/new" element={<FieldSetup />} />
          <Route path="/field/:fieldId" element={<FieldDashboard />} />
        </Routes>
      </div>
    </Router>
  )
}

export default App
