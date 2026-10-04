import { Preferences } from '@capacitor/preferences';

const KEY = 'suncast_token';

// undefined means we have not read storage yet. null means signed out.
let memoryToken;

async function readStoredToken() {
  let value = null;
  try {
    const stored = await Preferences.get({ key: KEY });
    value = stored.value || null;
  } catch (err) {
    value = null;
  }
  if (!value) {
    value = localStorage.getItem(KEY);
    if (value) {
      try {
        await Preferences.set({ key: KEY, value });
      } catch (err) {
        // The web view copy is still available for this launch.
      }
    }
  }
  if (memoryToken === undefined) memoryToken = value;
  return memoryToken;
}

export function getCachedToken() {
  return memoryToken || null;
}

export async function loadAuthToken() {
  if (memoryToken !== undefined) return memoryToken;
  return readStoredToken();
}

export async function setAuthToken(token) {
  memoryToken = token;
  localStorage.setItem(KEY, token);
  try {
    await Preferences.set({ key: KEY, value: token });
  } catch (err) {
    // This launch still has the token if native storage is unavailable.
  }
}

export async function clearAuthToken() {
  memoryToken = null;
  localStorage.removeItem(KEY);
  try {
    await Preferences.remove({ key: KEY });
  } catch (err) {
    // The in-memory session is already cleared.
  }
}
