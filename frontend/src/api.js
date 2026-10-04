import { loadAuthToken } from './authToken';

// The iPhone build talks to the hosted Railway API. Browser dev still uses localhost.
const DEVICE_API_BASE = 'https://suncast-production.up.railway.app';

function resolveApiBase() {
  // An explicit empty value means "same host" (the Railway deploy).
  // Unset keeps localhost in the browser and the Mac's Wi-Fi address on a phone.
  const configured = process.env.REACT_APP_API_URL;
  if (typeof configured === 'string') return configured.replace(/\/$/, '');
  if (typeof window === 'undefined') return 'http://localhost:5001';
  const native =
    window.location.protocol === 'capacitor:' ||
    window.Capacitor?.isNativePlatform?.();
  return native ? DEVICE_API_BASE : 'http://localhost:5001';
}

export function apiUrl(path) {
  if (!path.startsWith('/')) path = `/${path}`;
  return `${resolveApiBase()}${path}`;
}

export async function authHeaders(extra = {}) {
  const token = await loadAuthToken();
  return {
    ...extra,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export async function apiJson(path, options = {}) {
  const base = resolveApiBase();
  let res;
  try {
    res = await fetch(apiUrl(path), {
      ...options,
      headers: {
        ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...(await authHeaders(options.headers || {})),
      },
    });
  } catch (err) {
    const hint = !base || base.includes('localhost')
      ? 'Start the backend with: cd backend && ../venv/bin/python App.py'
      : 'Check that the hosted API is up, then try again.';
    throw new Error(`Cannot reach SunCast API at ${base || 'this site'}. ${hint}`);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(data.error || `API error ${res.status}`);
    error.status = res.status;
    throw error;
  }
  return data;
}
