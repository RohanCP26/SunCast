// A phone's localhost is the phone itself. The native app must use this Mac's Wi-Fi address.
// If the computer's IP changes, update DEVICE_API_BASE and frontend/.env.production, then rebuild.
const DEVICE_API_BASE = 'http://10.0.0.73:5001';

function resolveApiBase() {
  if (process.env.REACT_APP_API_URL) return process.env.REACT_APP_API_URL;
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

export function authHeaders(extra = {}) {
  const token = localStorage.getItem('suncast_token');
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
        ...authHeaders(options.headers || {}),
      },
    });
  } catch (err) {
    const hint = base.includes('localhost')
      ? 'Start the backend with: cd backend && ../venv/bin/python App.py'
      : 'Keep the backend running on your computer, and keep this phone on the same Wi-Fi.';
    throw new Error(`Cannot reach SunCast API at ${base}. ${hint}`);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `API error ${res.status}`);
  }
  return data;
}
