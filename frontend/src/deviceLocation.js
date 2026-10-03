import { Capacitor } from '@capacitor/core';
import { Geolocation } from '@capacitor/geolocation';
import { apiJson } from './api';

const reverseGeocode = async (latitude, longitude) => {
  try {
    const data = await apiJson('/api/reverse-geocode', {
      method: 'POST',
      body: JSON.stringify({ latitude, longitude }),
    });
    return data.label || data.best?.label || null;
  } catch (err) {
    console.warn('Reverse geocode failed', err);
    return null;
  }
};

const readBrowserPosition = () =>
  new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error('Geolocation is not available in this browser'));
      return;
    }
    navigator.geolocation.getCurrentPosition(resolve, reject, {
      enableHighAccuracy: false,
      timeout: 12000,
      maximumAge: 5 * 60 * 1000,
    });
  });

/**
 * Ask the device/browser for the current GPS position.
 * Returns { latitude, longitude, location_name, fromDevice: true } or null.
 */
export async function getDeviceLocation() {
  try {
    let latitude;
    let longitude;

    if (Capacitor.isNativePlatform()) {
      const permission = await Geolocation.requestPermissions();
      const granted =
        permission.location === 'granted' || permission.coarseLocation === 'granted';
      if (!granted) {
        return null;
      }
      const position = await Geolocation.getCurrentPosition({
        enableHighAccuracy: false,
        timeout: 12000,
        maximumAge: 5 * 60 * 1000,
      });
      latitude = position.coords.latitude;
      longitude = position.coords.longitude;
    } else {
      const position = await readBrowserPosition();
      latitude = position.coords.latitude;
      longitude = position.coords.longitude;
    }

    const location_name =
      (await reverseGeocode(latitude, longitude)) || 'Current location';

    return {
      latitude,
      longitude,
      location_name,
      fromDevice: true,
    };
  } catch (err) {
    console.warn('Device location unavailable', err);
    return null;
  }
}
