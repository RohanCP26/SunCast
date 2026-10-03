import React, { useState } from 'react';
import SunsetPredictor from './sunsetPredictor';
import Social from './Social';
import './App.css';

function App() {
  const [tab, setTab] = useState('forecast');

  return (
    <div className="app">
      <nav className="app-nav" aria-label="Primary">
        <div className="nav-brand">
          <img src="/suncast-logo.png" alt="" />
          <span>SunCast</span>
        </div>
        <div className="nav-tabs">
          <button
            type="button"
            className={tab === 'forecast' ? 'active' : ''}
            onClick={() => setTab('forecast')}
          >
            Forecast
          </button>
          <button
            type="button"
            className={tab === 'social' ? 'active' : ''}
            onClick={() => setTab('social')}
          >
            Social
          </button>
        </div>
      </nav>

      {tab === 'forecast' ? <SunsetPredictor /> : <Social />}

      <footer className="app-footer">
        <img src="/suncast-logo.png" alt="SunCast" className="footer-logo" />
        <p className="footer-brand">SunCast</p>
        <p className="footer-note">Weather via Open-Meteo · Scored with gradient boosting</p>
        <p className="footer-author">Author: Rohan Paranjape</p>
      </footer>
    </div>
  );
}

export default App;
