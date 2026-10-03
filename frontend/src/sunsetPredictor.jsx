import React, { useState, useEffect } from 'react';
import { apiJson, apiUrl } from './api';
import { getDeviceLocation } from './deviceLocation';
import { scheduleHighScoreNotifications, isNativeApp } from './notifications';
import './sunsetPredictor.css';

const DEFAULT_LOCATION = {
  latitude: 30.2672,
  longitude: -97.7431,
  location_name: 'Austin, TX',
};

const scoreTone = (score) => {
  if (score >= 8.5) return 'exceptional';
  if (score >= 7) return 'excellent';
  if (score >= 5.5) return 'good';
  if (score >= 4) return 'fair';
  return 'muted';
};

const formatShortDate = (iso) => {
  try {
    return new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return iso;
  }
};

const generateSunsetGradient = (hue, saturation, brightness) => {
  if (hue == null) {
    return 'linear-gradient(180deg, #1b1230 0%, #6b2d4a 42%, #e8703a 78%, #f6c48a 100%)';
  }

  const h = (((hue % 360) + 360) % 360) / 360;
  const s = Math.min(Math.max(saturation ?? 0.65, 0.35), 1);
  const b = Math.min(Math.max(brightness ?? 0.75, 0.45), 1);

  const c = b * s;
  const x = c * (1 - Math.abs(((h * 6) % 2) - 1));
  const m = b - c;

  let r;
  let g;
  let bl;
  if (h < 1 / 6) [r, g, bl] = [c, x, 0];
  else if (h < 2 / 6) [r, g, bl] = [x, c, 0];
  else if (h < 3 / 6) [r, g, bl] = [0, c, x];
  else if (h < 4 / 6) [r, g, bl] = [0, x, c];
  else if (h < 5 / 6) [r, g, bl] = [x, 0, c];
  else [r, g, bl] = [c, 0, x];

  const toHex = (n) => {
    const hex = Math.round((n + m) * 255).toString(16);
    return hex.length === 1 ? `0${hex}` : hex;
  };

  const mid = `#${toHex(r)}${toHex(g)}${toHex(bl)}`;
  return `linear-gradient(180deg, #120c22 0%, #4a2140 38%, ${mid} 72%, #f8d7a8 100%)`;
};

const SunsetPredictor = () => {
  const [location, setLocation] = useState(DEFAULT_LOCATION);
  const [week, setWeek] = useState(null);
  const [selectedDate, setSelectedDate] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [imageUrl, setImageUrl] = useState(null);
  const [imageProvider, setImageProvider] = useState(null);
  const [imageLoading, setImageLoading] = useState(false);
  const [imageError, setImageError] = useState(null);
  const [viewpoints, setViewpoints] = useState([]);
  const [viewpointsLoading, setViewpointsLoading] = useState(false);
  const [locating, setLocating] = useState(false);

  const selected = week?.days?.find((d) => d.date === selectedDate) || week?.days?.[0];

  const loadViewpoints = async (loc) => {
    setViewpointsLoading(true);
    try {
      const data = await apiJson('/api/viewpoints', {
        method: 'POST',
        body: JSON.stringify({
          latitude: Number(loc.latitude),
          longitude: Number(loc.longitude),
          location_name: loc.name || loc.location_name || '',
        }),
      });
      setViewpoints(data.viewpoints || []);
      return data.viewpoints?.[0] || null;
    } catch (err) {
      console.error(err);
      setViewpoints([]);
      return null;
    } finally {
      setViewpointsLoading(false);
    }
  };

  const loadWeek = async (loc = location, options = {}) => {
    const resolveLocation = options.resolveLocation ?? !loc.fromDevice;
    setLoading(true);
    setError(null);
    setImageUrl(null);
    setImageProvider(null);
    setImageError(null);
    try {
      const data = await apiJson('/api/week', {
        method: 'POST',
        body: JSON.stringify({
          latitude: Number(loc.latitude),
          longitude: Number(loc.longitude),
          location_name: loc.location_name || 'Custom location',
          // GPS coords must not be overwritten by geocoding the place label.
          resolve_location: resolveLocation,
          days: 7,
        }),
      });
      const topViewpoint = await loadViewpoints(data.location || loc);
      const enriched = { ...data, topViewpoint };
      setWeek(enriched);
      if (data.location) {
        setLocation({
          location_name: data.location.name || loc.location_name,
          latitude: data.location.latitude,
          longitude: data.location.longitude,
          fromDevice: Boolean(loc.fromDevice),
        });
      }
      setSelectedDate(data.best_day?.date || data.days?.[0]?.date);
      if (isNativeApp()) {
        scheduleHighScoreNotifications(enriched).catch(console.error);
      }
    } catch (err) {
      setError(err.message);
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const useMyLocation = async () => {
    setLocating(true);
    setError(null);
    try {
      const deviceLoc = await getDeviceLocation();
      if (!deviceLoc) {
        setError('Could not access location. Check permissions and try again.');
        return;
      }
      setLocation(deviceLoc);
      await loadWeek(deviceLoc, { resolveLocation: false });
    } finally {
      setLocating(false);
    }
  };

  const generateRendition = async () => {
    if (!selected) return;
    setImageLoading(true);
    setImageError(null);
    try {
      const response = await fetch(apiUrl('/api/predict'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: selected.image_generation_prompt,
          location_name: week?.location?.name || location.location_name,
          latitude: Number(week?.location?.latitude ?? location.latitude),
          longitude: Number(week?.location?.longitude ?? location.longitude),
          hue_shift: selected.prediction.hue_shift,
          saturation: selected.prediction.saturation,
          brightness: selected.prediction.brightness,
          cloud_density: selected.prediction.cloud_density,
          visual_description: selected.visual_description,
          seed: Math.abs(Math.round(selected.prediction.hue_shift * 10 + selected.aesthetic_score * 100)),
        }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || `Image API error: ${response.status}`);
      }
      setImageUrl(data.image_url);
      setImageProvider(data.provider);
    } catch (err) {
      setImageError(err.message);
      console.error(err);
    } finally {
      setImageLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLocating(true);
      const deviceLoc = await getDeviceLocation();
      if (cancelled) return;
      setLocating(false);
      if (deviceLoc) {
        setLocation(deviceLoc);
        await loadWeek(deviceLoc, { resolveLocation: false });
      } else {
        await loadWeek(DEFAULT_LOCATION, { resolveLocation: true });
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setImageUrl(null);
    setImageProvider(null);
    setImageError(null);
  }, [selectedDate]);

  const handleLocationSubmit = (e) => {
    e.preventDefault();
    const typed = String(location.location_name || '').trim();
    // Prefer geocoding when the user typed a place name; otherwise keep lat/lon as-is.
    loadWeek(
      { ...location, fromDevice: false },
      { resolveLocation: Boolean(typed) && typed !== 'Current location' }
    );
  };

  return (
    <div className="sunset-predictor">
      <header
        className="sky-hero"
        style={{
          background: selected
            ? generateSunsetGradient(
                selected.prediction.hue_shift,
                selected.prediction.saturation,
                selected.prediction.brightness
              )
            : undefined,
        }}
      >
        <div className="sky-wash" aria-hidden="true" />
        <div className="sky-hero-inner">
          <div className="brand">
            <img src="/suncast-logo.jpg" alt="" className="brand-logo" />
            <span>SunCast</span>
          </div>
          <h1>Know tonight&apos;s sky.</h1>
          <p className="lede">
            Seven-day sunset scores from live weather and your ML model.
          </p>

          <form className="location-bar" onSubmit={handleLocationSubmit}>
            <label className="field place">
              <span>Location</span>
              <input
                type="text"
                value={location.location_name}
                onChange={(e) =>
                  setLocation((p) => ({
                    ...p,
                    location_name: e.target.value,
                    fromDevice: false,
                  }))
                }
                placeholder="Austin, TX"
              />
            </label>
            <label className="field">
              <span>Lat</span>
              <input
                type="number"
                step="0.0001"
                value={location.latitude}
                onChange={(e) =>
                  setLocation((p) => ({
                    ...p,
                    latitude: e.target.value,
                    fromDevice: false,
                  }))
                }
              />
            </label>
            <label className="field">
              <span>Lon</span>
              <input
                type="number"
                step="0.0001"
                value={location.longitude}
                onChange={(e) =>
                  setLocation((p) => ({
                    ...p,
                    longitude: e.target.value,
                    fromDevice: false,
                  }))
                }
              />
            </label>
            <button
              type="button"
              className="location-gps"
              onClick={useMyLocation}
              disabled={loading || locating}
            >
              {locating ? 'Locating…' : 'Use my location'}
            </button>
            <button type="submit" disabled={loading || locating}>
              {loading ? 'Updating…' : 'Update'}
            </button>
          </form>
        </div>
      </header>

      <main className="week-main">
        {error && <div className="error-banner" role="alert">{error}</div>}

        <section className="week-panel">
          <div className="week-heading">
            <div>
              <h2>This week</h2>
              <p>
                {week?.location?.name || location.location_name}
                {week?.location?.latitude != null && (
                  <span className="coords">
                    {' '}
                    · {Number(week.location.latitude).toFixed(2)}, {Number(week.location.longitude).toFixed(2)}
                    {week.location.timezone ? ` · ${week.location.timezone}` : ''}
                  </span>
                )}
                {week?.best_day
                  ? ` · Best: ${week.best_day.weekday} (${week.best_day.aesthetic_score}/10)`
                  : ''}
              </p>
              {week?.weather_basis_note && (
                <p className="basis-note">{week.weather_basis_note}</p>
              )}
            </div>
            {loading && <span className="status-dot" aria-live="polite">Refreshing forecast</span>}
          </div>

          <div className="week-strip" role="listbox" aria-label="Seven day sunset scores">
            {(week?.days || Array.from({ length: 7 })).map((day, i) =>
              day?.date ? (
                <button
                  key={day.date}
                  type="button"
                  role="option"
                  aria-selected={selectedDate === day.date}
                  className={`day-chip ${selectedDate === day.date ? 'active' : ''} tone-${scoreTone(day.aesthetic_score)}`}
                  onClick={() => setSelectedDate(day.date)}
                >
                  <span className="day-name">{day.weekday.slice(0, 3)}</span>
                  <span className="day-date">{formatShortDate(day.date)}</span>
                  <span className="day-score">{day.aesthetic_score.toFixed(1)}</span>
                </button>
              ) : (
                <div key={`skeleton-${i}`} className="day-chip skeleton" aria-hidden="true" />
              )
            )}
          </div>
        </section>

        {selected && (
          <section className="day-detail" key={selected.date}>
            <div className="detail-primary">
              <p className="eyebrow">Selected evening</p>
              <h3>
                {selected.weekday}
                <span>{formatShortDate(selected.date)}</span>
              </h3>

              <div className="score-row">
                <div className={`score-display tone-${scoreTone(selected.aesthetic_score)}`}>
                  <span className="score-number">{selected.aesthetic_score.toFixed(1)}</span>
                  <span className="score-scale">/ 10</span>
                </div>
                <div className="score-copy">
                  <strong>{selected.aesthetic_label}</strong>
                  <span>Sunset {selected.sunset_time || '—'}</span>
                </div>
              </div>

              <p className="description">{selected.visual_description}</p>
              {selected.sample_time && (
                <p className="sample-note">
                  Weather sampled near sunset ({selected.sample_time}
                  {selected.weather.temp_max != null
                    ? ` · day high/low ${Math.round(selected.weather.temp_max)}°/${Math.round(selected.weather.temp_min)}°F`
                    : ''}
                  )
                </p>
              )}

              <dl className="weather-facts">
                <div>
                  <dt>Clouds @ sunset</dt>
                  <dd>{Math.round(selected.weather.cloud_cover)}%</dd>
                </div>
                <div>
                  <dt>Humidity @ sunset</dt>
                  <dd>{Math.round(selected.weather.humidity)}%</dd>
                </div>
                <div>
                  <dt>Wind @ sunset</dt>
                  <dd>{selected.weather.wind_speed} mph</dd>
                </div>
                <div>
                  <dt>Visibility</dt>
                  <dd>{selected.weather.visibility} km</dd>
                </div>
                <div>
                  <dt>Temp @ sunset</dt>
                  <dd>{Math.round(selected.weather.temperature)}°F</dd>
                </div>
                <div>
                  <dt>Precip chance</dt>
                  <dd>{Math.round(selected.weather.precip_probability || 0)}%</dd>
                </div>
                <div>
                  <dt>Pressure</dt>
                  <dd>{Math.round(selected.weather.pressure)} mb</dd>
                </div>
                <div>
                  <dt>Sunset</dt>
                  <dd>{selected.sunset_time || '—'}</dd>
                </div>
              </dl>
            </div>

            <aside className="detail-aside">
              <p className="eyebrow">Model readout</p>
              <ul className="metric-list">
                <li>
                  <span>Hue</span>
                  <strong>{Math.round(selected.prediction.hue_shift)}°</strong>
                </li>
                <li>
                  <span>Saturation</span>
                  <strong>{(selected.prediction.saturation * 100).toFixed(0)}%</strong>
                </li>
                <li>
                  <span>Brightness</span>
                  <strong>{(selected.prediction.brightness * 100).toFixed(0)}%</strong>
                </li>
                <li>
                  <span>Cloud density</span>
                  <strong>{(selected.prediction.cloud_density * 100).toFixed(0)}%</strong>
                </li>
                <li>
                  <span>Confidence</span>
                  <strong>{(selected.confidence * 100).toFixed(0)}%</strong>
                </li>
              </ul>
            </aside>
          </section>
        )}

        {selected && selected.aesthetic_score >= 7.5 && (
          <section className="viewpoint-panel">
            <div className="rendition-header">
              <div>
                <p className="eyebrow">Go chase it</p>
                <h3>Best viewpoints near you</h3>
              </div>
            </div>
            <p className="sample-note">
              This evening scores {selected.aesthetic_score}/10
              {isNativeApp() ? ' · a mobile notification was scheduled' : ''}.
              Head to higher or open west-facing ground before sunset
              {selected.sunset_time ? ` (${selected.sunset_time})` : ''}.
            </p>
            {viewpointsLoading && <p className="muted">Finding scenic overlooks…</p>}
            <div className="viewpoint-list">
              {viewpoints.slice(0, 4).map((spot) => (
                <a
                  key={`${spot.name}-${spot.latitude}`}
                  className="viewpoint-card"
                  href={spot.maps_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  <strong>{spot.name}</strong>
                  <span>
                    {spot.type?.replace('_', ' ')}
                    {spot.elevation_m != null ? ` · ${Math.round(spot.elevation_m)} m` : ''}
                    {spot.distance_km != null ? ` · ${spot.distance_km} km ${spot.direction || ''}` : ''}
                  </span>
                  <p>{spot.why}</p>
                </a>
              ))}
            </div>
          </section>
        )}

        {selected && (
          <section className="rendition-panel">
            <div className="rendition-header">
              <div>
                <p className="eyebrow">AI rendition</p>
                <h3>What this sunset may look like</h3>
              </div>
              <button
                type="button"
                className="rendition-button"
                onClick={generateRendition}
                disabled={imageLoading}
              >
                {imageLoading ? 'Generating…' : imageUrl ? 'Regenerate' : 'Generate image'}
              </button>
            </div>

            {imageError && <p className="rendition-error">{imageError}</p>}

            <div className={`rendition-frame ${imageLoading ? 'is-loading' : ''}`}>
              {imageUrl ? (
                <img
                  src={imageUrl}
                  alt={`AI sunset rendition for ${selected.weekday}`}
                  onError={() => {
                    setImageError('Image failed to display. Try Generate again.');
                    setImageUrl(null);
                  }}
                />
              ) : (
                <div className="rendition-placeholder">
                  <p>Generate a photorealistic preview from this evening&apos;s ML forecast.</p>
                </div>
              )}
            </div>
            {imageProvider && (
              <p className="rendition-meta">
                Generated via {imageProvider}
                {imageProvider === 'procedural'
                  ? ' · local ML-conditioned sky (add REPLICATE_API_TOKEN for hosted AI)'
                  : ''}
              </p>
            )}
          </section>
        )}
      </main>
    </div>
  );
};

export default SunsetPredictor;
