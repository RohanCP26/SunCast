import { Capacitor } from '@capacitor/core';

const THRESHOLD = 7.5;

export function isNativeApp() {
  try {
    return Capacitor.isNativePlatform();
  } catch {
    return false;
  }
}

/**
 * Mobile-only: schedule local notifications for evenings scored above 7.5.
 * No-ops on web.
 */
export async function scheduleHighScoreNotifications(week) {
  if (!isNativeApp() || !week?.days?.length) return { scheduled: 0 };

  const { LocalNotifications } = await import('@capacitor/local-notifications');
  await LocalNotifications.requestPermissions();

  const pending = await LocalNotifications.getPending();
  const sunsetIds = (pending?.notifications || [])
    .map((item) => item.id)
    .filter((id) => id >= 7000 && id < 7100);
  if (sunsetIds.length) {
    await LocalNotifications.cancel({
      notifications: sunsetIds.map((id) => ({ id })),
    });
  }

  const location = week.location?.name || 'your area';
  const toSchedule = [];

  week.days.forEach((day, idx) => {
    if (day.aesthetic_score < THRESHOLD) return;

    // Fire mid-afternoon local time on that day (approx)
    const when = new Date(`${day.date}T15:00:00`);
    if (Number.isNaN(when.getTime()) || when.getTime() < Date.now()) return;

    const viewpointHint = week.topViewpoint
      ? ` Try ${week.topViewpoint.name}.`
      : ' Check SunCast for the best viewpoint.';

    toSchedule.push({
      id: 7000 + idx,
      title: `SunCast: ${day.aesthetic_score}/10 sunset`,
      body: `${day.weekday} looks ${day.aesthetic_label.toLowerCase()} in ${location}.${viewpointHint}`,
      schedule: { at: when },
      extra: { date: day.date, score: day.aesthetic_score },
    });
  });

  if (toSchedule.length) {
    await LocalNotifications.schedule({ notifications: toSchedule });
  }

  return { scheduled: toSchedule.length };
}
