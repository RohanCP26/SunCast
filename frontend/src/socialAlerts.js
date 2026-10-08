import { isNativeApp } from './notifications';

const SEEN_KEY = 'suncast_seen_social';

function readSeen() {
  try {
    const parsed = JSON.parse(localStorage.getItem(SEEN_KEY) || 'null');
    if (!parsed) return null;
    return {
      requests: parsed.requests || [],
      comments: parsed.comments || [],
    };
  } catch {
    return null;
  }
}

function writeSeen(requests, comments) {
  localStorage.setItem(SEEN_KEY, JSON.stringify({
    requests: requests.slice(-80),
    comments: comments.slice(-80),
  }));
}

async function ping(title, body, id) {
  if (isNativeApp()) {
    const { LocalNotifications } = await import('@capacitor/local-notifications');
    const permission = await LocalNotifications.requestPermissions();
    if (permission.display !== 'granted') return;
    await LocalNotifications.schedule({
      notifications: [{
        id,
        title,
        body,
        schedule: { at: new Date(Date.now() + 800) },
      }],
    });
    return;
  }
  if (typeof Notification === 'undefined') return;
  let permission = Notification.permission;
  if (permission === 'default') permission = await Notification.requestPermission();
  if (permission !== 'granted') return;
  // eslint-disable-next-line no-new
  new Notification(title, { body });
}

export async function notifySocialActivity(activity) {
  const incoming = activity?.incoming || [];
  const comments = activity?.comments || [];
  const requestIds = incoming.map((item) => item.friendship_id);
  const commentIds = comments.map((item) => item.id);
  const seen = readSeen();
  if (!seen) {
    writeSeen(requestIds, commentIds);
    return;
  }
  const knownRequests = new Set(seen.requests);
  const knownComments = new Set(seen.comments);
  const freshRequests = incoming.filter((item) => !knownRequests.has(item.friendship_id));
  const freshComments = comments.filter((item) => !knownComments.has(item.id));
  writeSeen(requestIds, commentIds);
  if (!freshRequests.length && !freshComments.length) return;

  const firstRequest = freshRequests[0];
  const firstComment = freshComments[0];
  if (freshRequests.length && !freshComments.length) {
    const name = firstRequest.display_name || firstRequest.username;
    const extra = freshRequests.length > 1 ? ` and ${freshRequests.length - 1} more` : '';
    await ping('SunCast', `${name}${extra} sent you a friend request`, 8100 + (firstRequest.friendship_id % 800));
    return;
  }
  if (freshComments.length && !freshRequests.length) {
    const name = firstComment.display_name || firstComment.username;
    const extra = freshComments.length > 1 ? ` and ${freshComments.length - 1} more` : '';
    await ping('SunCast', `${name}${extra} commented on your sunset`, 8600 + (firstComment.id % 800));
    return;
  }
  await ping(
    'SunCast',
    `${freshRequests.length} friend request${freshRequests.length === 1 ? '' : 's'} and ${freshComments.length} new comment${freshComments.length === 1 ? '' : 's'}`,
    8900,
  );
}
