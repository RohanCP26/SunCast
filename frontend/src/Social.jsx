import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { apiJson, apiUrl, authHeaders } from './api';
import { clearAuthToken, loadAuthToken, setAuthToken } from './authToken';
import './Social.css';

const initialOf = (name) => (name || '?').trim().charAt(0).toUpperCase();

const Avatar = ({ user, className = 'avatar', onClick, label }) => {
  const face = user?.avatar_url ? (
    <img className={className} src={apiUrl(user.avatar_url)} alt="" />
  ) : (
    <span className={`${className} avatar-fallback`} aria-hidden="true">
      {initialOf(user?.display_name || user?.username)}
    </span>
  );
  if (!onClick) return face;
  return (
    <button
      type="button"
      className="avatar-btn"
      onClick={onClick}
      aria-label={label || `${user?.display_name || user?.username || 'User'}'s profile`}
    >
      {face}
    </button>
  );
};

const Heart = ({ filled }) => (
  <svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true">
    <path
      d="M12 20.2S5.2 15.9 5.2 11C5.2 8.2 7 6.4 9.2 6.4c1.3 0 2.4.6 2.8 1.6.4-1 1.5-1.6 2.8-1.6 2.2 0 4 1.8 4 4.6 0 4.9-6.8 9.2-6.8 9.2z"
      fill={filled ? 'currentColor' : 'none'}
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinejoin="round"
    />
  </svg>
);

const ratingLabel = (value) => (value == null ? '—' : Number(value).toFixed(1));

const scoreFromBar = (bar, clientX) => {
  const rect = bar.getBoundingClientRect();
  const ratio = rect.width ? (clientX - rect.left) / rect.width : 0;
  const clamped = Math.min(1, Math.max(0, ratio));
  return Math.round(clamped * 9) + 1;
};

const RateBar = ({ value, onChange }) => {
  const barRef = useRef(null);
  const dragging = useRef(false);
  const [dragScore, setDragScore] = useState(null);
  const shown = dragScore ?? value ?? null;
  const position = shown ? `${((shown - 1) / 9) * 100}%` : '0%';

  const finish = (clientX) => {
    if (!dragging.current || !barRef.current) return;
    dragging.current = false;
    const score = scoreFromBar(barRef.current, clientX);
    setDragScore(null);
    if (score !== value) onChange(score);
  };

  return (
    <div className="rate-row">
      <span className="rate-value">{shown || 'Rate'}</span>
      <div
        ref={barRef}
        className="rate-bar"
        role="slider"
        tabIndex={0}
        aria-label="Rate this sunset"
        aria-valuemin={1}
        aria-valuemax={10}
        aria-valuenow={shown ?? undefined}
        aria-valuetext={shown ? `${shown} out of 10` : 'Not rated'}
        onPointerDown={(event) => {
          try {
            event.currentTarget.setPointerCapture(event.pointerId);
          } catch (err) {
            // Some browsers reject capture until the pointer is active.
          }
          dragging.current = true;
          setDragScore(scoreFromBar(event.currentTarget, event.clientX));
        }}
        onPointerMove={(event) => {
          if (!dragging.current) return;
          setDragScore(scoreFromBar(event.currentTarget, event.clientX));
        }}
        onPointerUp={(event) => finish(event.clientX)}
        onPointerCancel={(event) => finish(event.clientX)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowRight' || event.key === 'ArrowUp') {
            event.preventDefault();
            onChange(Math.min(10, (value || 0) + 1));
          } else if ((event.key === 'ArrowLeft' || event.key === 'ArrowDown') && value) {
            event.preventDefault();
            onChange(Math.max(1, value - 1));
          }
        }}
      >
      <span className="rate-track">
        <span className="rate-fill" style={{ width: position }} />
      </span>
      {shown ? <span className="rate-thumb" style={{ left: position }} /> : null}
      <span className="rate-ticks" aria-hidden="true">
        {Array.from({ length: 10 }, (_, index) => <i key={index} />)}
      </span>
      </div>
    </div>
  );
};

const PostCard = ({ id, post, burstKey, onLike, onRate, onComment, onOpenProfile, showPlace = true, children }) => {
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const lastTap = useRef(0);

  const onPhotoClick = () => {
    const now = Date.now();
    if (now - lastTap.current < 320) {
      onLike(post, { fromPhoto: true });
    }
    lastTap.current = now;
  };

  const sendComment = async (event) => {
    event.preventDefault();
    const body = draft.trim();
    if (!body || sending) return;
    setSending(true);
    try {
      await onComment(post, body);
      setDraft('');
    } finally {
      setSending(false);
    }
  };

  return (
    <article className="post-card" id={id}>
      <header className="post-head">
        <Avatar
          user={{ id: post.user_id, display_name: post.display_name, username: post.username, avatar_url: post.avatar_url }}
          className="avatar avatar-sm"
          onClick={() => onOpenProfile?.({
            id: post.user_id,
            display_name: post.display_name,
            username: post.username,
            avatar_url: post.avatar_url,
          })}
        />
        <div className="post-who">
          <strong>{post.display_name}</strong>
          {showPlace && <span>{post.location_name || 'Somewhere in the light'}</span>}
        </div>
        <time dateTime={post.created_at}>{timeLabel(post)}</time>
      </header>
      <button type="button" className="photo-stage" onClick={onPhotoClick}>
        <img src={apiUrl(post.image_url)} alt={post.caption || `Sunset by ${post.display_name}`} />
        {burstKey ? (
          <span key={burstKey} className="like-burst">
            <Heart filled />
          </span>
        ) : null}
      </button>
      <div className="post-actions">
        <button
          type="button"
          className={`heart-btn${post.liked ? ' liked' : ''}`}
          aria-pressed={!!post.liked}
          aria-label={post.liked ? 'Unlike' : 'Like'}
          onClick={() => onLike(post)}
        >
          <Heart filled={!!post.liked} />
          <span>{post.like_count || 0}</span>
        </button>
        <p className="rating-summary">
          {post.rating_count
            ? `${ratingLabel(post.rating_average)} average · ${post.rating_count}`
            : 'No ratings yet'}
        </p>
      </div>
      <RateBar value={post.my_rating} onChange={(score) => onRate(post, score)} />
      <div className="post-body">
        {children}
        <div className="comments">
          {(post.comments || []).map((comment) => (
            <div key={comment.id} className="comment">
              <Avatar
                user={comment}
                className="avatar avatar-sm"
                onClick={() => onOpenProfile?.(comment)}
              />
              <p>
                <strong>{comment.display_name}</strong> {comment.body}
                <span className="muted">{timeLabel(comment)}</span>
              </p>
            </div>
          ))}
          <form className="comment-form" onSubmit={sendComment}>
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              maxLength={400}
              placeholder="Add a comment"
              aria-label="Add a comment"
            />
            <button type="submit" disabled={sending || !draft.trim()}>
              {sending ? '…' : 'Post'}
            </button>
          </form>
        </div>
      </div>
    </article>
  );
};

const timeLabel = (post) => {
  const raw = post?.created_at;
  if (!raw) return post?.sunset_date || '';
  const then = new Date(raw.endsWith('Z') || raw.includes('+') ? raw : `${raw}Z`);
  if (Number.isNaN(then.getTime())) return post?.sunset_date || '';
  const seconds = Math.max(0, (Date.now() - then.getTime()) / 1000);
  if (seconds < 60) return 'Just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d`;
  return then.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
};

const Social = () => {
  const [user, setUser] = useState(null);
  const [authMode, setAuthMode] = useState('login');
  const [form, setForm] = useState({
    username: '',
    password: '',
    display_name: '',
    email: '',
    phone: '',
    login_id: '',
    confirm: '',
  });
  const [feed, setFeed] = useState([]);
  const [friends, setFriends] = useState({ friends: [], incoming: [], outgoing: [] });
  const [friendQuery, setFriendQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [searched, setSearched] = useState(false);
  const [notice, setNotice] = useState(null);
  const [caption, setCaption] = useState('');
  const [locationName, setLocationName] = useState('');
  const [photo, setPhoto] = useState(null);
  const [error, setError] = useState(null);
  const [resetMessage, setResetMessage] = useState(null);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState('feed');
  const [myPosts, setMyPosts] = useState([]);
  const [editingIdentity, setEditingIdentity] = useState(false);
  const [identity, setIdentity] = useState({ display_name: '', username: '' });
  const [editingPostId, setEditingPostId] = useState(null);
  const [postDraft, setPostDraft] = useState({ caption: '', location_name: '', sunset_date: '' });
  const [activePost, setActivePost] = useState(null);
  const [bursts, setBursts] = useState({});
  const [restoring, setRestoring] = useState(true);
  const [restoreError, setRestoreError] = useState(null);
  const [viewedProfile, setViewedProfile] = useState(null);
  const [profileSource, setProfileSource] = useState('feed');
  const restoreGeneration = useRef(0);

  const friendCount = (friends.friends || []).length;
  const requestCount = (friends.incoming || []).length;
  const friendFeed = feed.filter((post) => post.user_id !== user?.id);
  const photoUrl = useMemo(() => (photo ? URL.createObjectURL(photo) : ''), [photo]);

  useEffect(() => () => {
    if (photoUrl) URL.revokeObjectURL(photoUrl);
  }, [photoUrl]);

  const refresh = async () => {
    const me = await apiJson('/api/social/me');
    setUser(me.user);
    const [feedRes, friendRes] = await Promise.all([
      apiJson('/api/social/feed'),
      apiJson('/api/social/friends'),
    ]);
    setFeed(feedRes.posts || []);
    setFriends(friendRes);
  };

  const loadMyPosts = async () => {
    const data = await apiJson('/api/social/me/posts');
    setMyPosts(data.posts || []);
  };

  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;

  const restoreSession = useCallback(async () => {
    const generation = restoreGeneration.current + 1;
    restoreGeneration.current = generation;
    setRestoring(true);
    setRestoreError(null);
    try {
      const token = await loadAuthToken();
      if (generation !== restoreGeneration.current) return;
      if (!token) return;
      await refreshRef.current();
    } catch (err) {
      if (generation !== restoreGeneration.current) return;
      if (err.status === 401) {
        await clearAuthToken();
        setUser(null);
        setRestoreError(null);
        return;
      }
      setRestoreError(err.message);
    } finally {
      if (generation === restoreGeneration.current) setRestoring(false);
    }
  }, []);

  useEffect(() => {
    restoreSession();
  }, [restoreSession]);

  const openedPostId = view === 'post' ? activePost?.id : null;
  useEffect(() => {
    if (!openedPostId) return undefined;
    const node = document.getElementById(`profile-post-${openedPostId}`);
    if (!node) return undefined;
    const pane = node.closest('.page-pane');
    const align = () => {
      const viewport = pane?.closest('.page-viewport');
      if (viewport && pane.offsetHeight - viewport.clientHeight > 12) return false;
      node.scrollIntoView({ block: 'start' });
      return true;
    };
    if (align()) return undefined;
    const observer = pane ? new ResizeObserver(() => {
      if (align()) observer.disconnect();
    }) : null;
    if (pane && observer) observer.observe(pane);
    const stop = window.setTimeout(() => {
      node.scrollIntoView({ block: 'start' });
      observer?.disconnect();
    }, 520);
    return () => {
      observer?.disconnect();
      window.clearTimeout(stop);
    };
  }, [openedPostId]);

  const handleAuth = async (e) => {
    e.preventDefault();
    if (authMode === 'register' && !form.email.trim() && !form.phone.trim()) {
      setError('Add an email or a phone number so you can reset your password');
      return;
    }
    setBusy(true);
    setError(null);
    setResetMessage(null);
    try {
      const path = authMode === 'login' ? '/api/social/login' : '/api/social/register';
      const body = authMode === 'login'
        ? { username: form.login_id, password: form.password }
        : {
            username: form.username,
            password: form.password,
            display_name: form.display_name,
            email: form.email,
            phone: form.phone,
          };
      const data = await apiJson(path, {
        method: 'POST',
        body: JSON.stringify(body),
      });
      await setAuthToken(data.token);
      setUser(data.user);
      setView('feed');
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const handleReset = async (e) => {
    e.preventDefault();
    if (form.password !== form.confirm) {
      setError('Passwords do not match');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await apiJson('/api/social/password/reset', {
        method: 'POST',
        body: JSON.stringify({ contact: form.login_id, password: form.password }),
      });
      setForm((prev) => ({ ...prev, password: '', confirm: '' }));
      setAuthMode('login');
      setResetMessage('Password updated. Sign in with your email or phone.');
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const logout = async () => {
    await clearAuthToken();
    setUser(null);
    setFeed([]);
    setView('feed');
    setMyPosts([]);
    setActivePost(null);
  };

  const searchFriends = async (event) => {
    event?.preventDefault?.();
    const query = friendQuery.trim().replace(/^@/, '');
    if (!query) return;
    setError(null);
    setNotice(null);
    try {
      const data = await apiJson(`/api/social/users?q=${encodeURIComponent(query)}`);
      setSearchResults(data.results || []);
      setSearched(true);
    } catch (err) {
      setError(err.message);
    }
  };

  const sendRequest = async (username) => {
    setError(null);
    setNotice(null);
    try {
      const data = await apiJson('/api/social/friends/request', {
        method: 'POST',
        body: JSON.stringify({ username }),
      });
      await refresh();
      const relation = data.status === 'accepted' ? 'friends' : 'outgoing';
      setSearchResults((prev) => prev.map((person) => (
        person.username.toLowerCase() === username.toLowerCase()
          ? { ...person, relation, friendship_id: data.id }
          : person
      )));
      setNotice(
        data.status === 'accepted'
          ? `You and @${username} are now friends`
          : `Request sent to @${username}`
      );
    } catch (err) {
      setError(err.message);
    }
  };

  const respond = async (friendshipId, accept) => {
    setError(null);
    setNotice(null);
    try {
      await apiJson('/api/social/friends/respond', {
        method: 'POST',
        body: JSON.stringify({ friendship_id: friendshipId, accept }),
      });
      await refresh();
      setSearchResults((prev) => prev.map((person) => (
        person.friendship_id === friendshipId
          ? { ...person, relation: accept ? 'friends' : 'none' }
          : person
      )));
      if (accept) setNotice('Friend request accepted');
    } catch (err) {
      setError(err.message);
    }
  };

  const openCompose = () => {
    setError(null);
    setNotice(null);
    setView('compose');
  };

  const submitPost = async (e) => {
    e.preventDefault();
    if (!photo) {
      setError('Choose a sunset photo to share');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const body = new FormData();
      body.append('photo', photo);
      body.append('caption', caption);
      body.append('location_name', locationName);
      body.append('sunset_date', new Date().toISOString().slice(0, 10));
      const res = await fetch(apiUrl('/api/social/posts'), {
        method: 'POST',
        headers: await authHeaders(),
        body,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Upload failed');
      setCaption('');
      setLocationName('');
      setPhoto(null);
      setView('feed');
      await Promise.all([refresh(), loadMyPosts()]);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const openProfile = async () => {
    setViewedProfile(null);
    setProfileSource('feed');
    setView('profile');
    setEditingIdentity(false);
    setEditingPostId(null);
    setActivePost(null);
    setError(null);
    try {
      const [me] = await Promise.all([apiJson('/api/social/me'), loadMyPosts()]);
      setUser(me.user);
    } catch (err) {
      setError(err.message);
    }
  };

  const openUserProfile = async (person) => {
    const id = person?.id || person?.user_id;
    if (!id || id === user.id) {
      await openProfile();
      return;
    }
    setProfileSource(view === 'profile' ? profileSource : view);
    setEditingIdentity(false);
    setEditingPostId(null);
    setError(null);
    setView('profile');
    setViewedProfile({
      user: {
        id,
        display_name: person.display_name,
        username: person.username,
        avatar_url: person.avatar_url,
      },
      posts: [],
      loading: true,
    });
    try {
      const data = await apiJson(`/api/social/users/${id}`);
      setViewedProfile({ user: data.user, posts: data.posts || [], loading: false });
    } catch (err) {
      setViewedProfile((current) => (current ? { ...current, loading: false } : current));
      setError(err.message);
    }
  };

  const changeAvatar = async (file) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const body = new FormData();
      body.append('photo', file);
      const res = await fetch(apiUrl('/api/social/me/avatar'), {
        method: 'POST',
        headers: await authHeaders(),
        body,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Could not update photo');
      setUser(data.user);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const startIdentityEdit = () => {
    setIdentity({
      display_name: user.display_name || '',
      username: user.username || '',
      email: user.email || '',
      phone: user.phone || '',
    });
    setEditingIdentity(true);
  };

  const saveIdentity = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const data = await apiJson('/api/social/me', {
        method: 'PATCH',
        body: JSON.stringify(identity),
      });
      setUser(data.user);
      setEditingIdentity(false);
      await Promise.all([refresh(), loadMyPosts()]);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const openPost = (post) => {
    setActivePost(post);
    setEditingPostId(null);
    setError(null);
    setView('post');
  };

  const startPostEdit = (post) => {
    setEditingPostId(post.id);
    setPostDraft({
      caption: post.caption || '',
      location_name: post.location_name || '',
      sunset_date: post.sunset_date || '',
    });
  };

  const savePost = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const data = await apiJson(`/api/social/posts/${editingPostId}`, {
        method: 'PATCH',
        body: JSON.stringify(postDraft),
      });
      setMyPosts((prev) => prev.map((post) => (post.id === data.post.id ? data.post : post)));
      setFeed((prev) => prev.map((post) => (post.id === data.post.id ? data.post : post)));
      setActivePost(data.post);
      setEditingPostId(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const rememberPost = (post, authorRating) => {
    setFeed((prev) => prev.map((item) => (item.id === post.id ? post : item)));
    setMyPosts((prev) => prev.map((item) => (item.id === post.id ? post : item)));
    setViewedProfile((prev) => (
      prev?.posts
        ? { ...prev, posts: prev.posts.map((item) => (item.id === post.id ? post : item)) }
        : prev
    ));
    setActivePost((prev) => (prev && prev.id === post.id ? post : prev));
    if (authorRating && user && post.user_id === user.id) {
      setUser((current) => (current ? { ...current, ...authorRating } : current));
    }
  };

  const toggleLike = async (post, { fromPhoto } = {}) => {
    if (fromPhoto && post.liked) {
      setBursts((prev) => ({ ...prev, [post.id]: Date.now() }));
      return;
    }
    const liking = !post.liked;
    if (liking) setBursts((prev) => ({ ...prev, [post.id]: Date.now() }));
    rememberPost({
      ...post,
      liked: liking,
      like_count: Math.max(0, (post.like_count || 0) + (liking ? 1 : -1)),
    });
    try {
      const data = await apiJson(`/api/social/posts/${post.id}/like`, { method: 'POST' });
      rememberPost(data.post);
    } catch (err) {
      rememberPost(post);
      setError(err.message);
    }
  };

  const ratePost = async (post, score) => {
    setError(null);
    try {
      const data = await apiJson(`/api/social/posts/${post.id}/rate`, {
        method: 'POST',
        body: JSON.stringify({ score }),
      });
      rememberPost(data.post, data.author_rating);
    } catch (err) {
      setError(err.message);
    }
  };

  const commentOn = async (post, body) => {
    setError(null);
    try {
      const data = await apiJson(`/api/social/posts/${post.id}/comments`, {
        method: 'POST',
        body: JSON.stringify({ body }),
      });
      rememberPost(data.post);
    } catch (err) {
      setError(err.message);
      throw err;
    }
  };

  const goBack = () => {
    setError(null);
    setEditingPostId(null);
    if (view === 'post') {
      setActivePost(null);
      setView('profile');
      window.scrollTo(0, 0);
      return;
    }
    if (view === 'friends') {
      setViewedProfile(null);
      setView('profile');
      return;
    }
    if (view === 'profile' && viewedProfile) {
      const backTo = profileSource && profileSource !== 'profile' ? profileSource : 'feed';
      setViewedProfile(null);
      setView(backTo);
      return;
    }
    setViewedProfile(null);
    setView('feed');
  };

  const titles = {
    feed: 'Sunsets',
    compose: 'New post',
    profile: viewedProfile?.user?.display_name || 'Profile',
    friends: 'Friends',
    post: activePost?.display_name || 'Posts',
  };

  if (restoring) {
    return (
      <section className="social-page auth-view">
        <header className="social-hero">
          <p className="eyebrow">Community</p>
          <h2>SunCast</h2>
        </header>
      </section>
    );
  }

  if (!user && restoreError) {
    return (
      <section className="social-page auth-view">
        <header className="social-hero">
          <p className="eyebrow">Community</p>
          <h2>Still signed in</h2>
          <p>Couldn&apos;t reach SunCast just now. Your login is saved on this phone.</p>
        </header>
        <div className="social-auth">
          <p className="social-error">{restoreError}</p>
          <button type="button" className="share-btn" onClick={restoreSession}>Try again</button>
        </div>
      </section>
    );
  }

  if (!user) {
    return (
      <section className="social-page auth-view">
        <header className="social-hero">
          <p className="eyebrow">Community</p>
          <h2>Share tonight&apos;s sky</h2>
          <p>Post your sunset and follow friends&apos; golden hours.</p>
        </header>

        <form className="social-auth" onSubmit={authMode === 'forgot' ? handleReset : handleAuth}>
          {authMode !== 'forgot' && (
            <div className="auth-tabs">
              <button type="button" className={authMode === 'login' ? 'active' : ''} onClick={() => { setAuthMode('login'); setError(null); }}>
                Sign in
              </button>
              <button type="button" className={authMode === 'register' ? 'active' : ''} onClick={() => { setAuthMode('register'); setError(null); setResetMessage(null); }}>
                Create account
              </button>
            </div>
          )}
          {authMode === 'forgot' && (
            <p className="muted">Enter the email or phone on your account, then choose a new password.</p>
          )}
          {authMode === 'register' && (
            <label>
              Display name
              <input
                value={form.display_name}
                onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                autoComplete="name"
              />
            </label>
          )}
          {authMode === 'register' ? (
            <label>
              Username
              <input
                required
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                autoComplete="username"
              />
            </label>
          ) : (
            <label>
              Email or phone
              <input
                required
                value={form.login_id}
                onChange={(e) => setForm({ ...form, login_id: e.target.value })}
                autoComplete="username"
                placeholder="Email or phone"
              />
            </label>
          )}
          {authMode === 'register' && (
            <>
              <label>
                Email
                <input
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  autoComplete="email"
                  placeholder="you@email.com"
                />
              </label>
              <label>
                Phone
                <input
                  type="tel"
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                  autoComplete="tel"
                  placeholder="Phone number"
                />
              </label>
            </>
          )}
          <label>
            {authMode === 'forgot' ? 'New password' : 'Password'}
            <input
              required
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              autoComplete={authMode === 'login' ? 'current-password' : 'new-password'}
            />
          </label>
          {authMode === 'forgot' && (
            <label>
              Confirm password
              <input
                required
                type="password"
                value={form.confirm}
                onChange={(e) => setForm({ ...form, confirm: e.target.value })}
                autoComplete="new-password"
              />
            </label>
          )}
          {resetMessage && authMode === 'login' && <p className="social-notice">{resetMessage}</p>}
          {error && <p className="social-error">{error}</p>}
          <button type="submit" disabled={busy}>
            {busy ? 'Please wait…' : authMode === 'login' ? 'Sign in' : authMode === 'forgot' ? 'Reset password' : 'Join SunCast'}
          </button>
          {authMode === 'login' && (
            <button type="button" className="auth-switch" onClick={() => { setAuthMode('forgot'); setError(null); setResetMessage(null); }}>
              Forgot password?
            </button>
          )}
          {authMode === 'forgot' && (
            <button type="button" className="auth-switch" onClick={() => { setAuthMode('login'); setError(null); }}>
              Back to sign in
            </button>
          )}
        </form>
      </section>
    );
  }

  return (
    <section className={`social-page view-${view}`}>
      <header className="social-bar">
        {view === 'feed' ? (
          <button type="button" className="icon-btn" onClick={openProfile} aria-label="Your profile">
            <Avatar user={user} className="avatar avatar-sm" />
            {requestCount > 0 && <span className="request-dot" aria-label={`${requestCount} friend requests`} />}
          </button>
        ) : (
          <button type="button" className="icon-btn back-btn" onClick={goBack} aria-label="Back">
            <span aria-hidden="true">‹</span>
          </button>
        )}
        <h2>{titles[view] || 'Sunsets'}</h2>
        {view === 'compose' ? (
          <span className="bar-spacer" />
        ) : (
          <button type="button" className="icon-btn add-btn" onClick={openCompose} aria-label="New post">
            +
          </button>
        )}
      </header>

      {error && <p className="social-error">{error}</p>}

      {view === 'feed' && (
        <div className="feed">
          {friendFeed.length === 0 && (
            <div className="empty-feed">
              <p>When friends share a sunset, it shows up here.</p>
              <button type="button" onClick={() => setView('friends')}>Find friends</button>
            </div>
          )}
          {friendFeed.map((post) => (
            <PostCard
              key={post.id}
              post={post}
              showPlace={false}
              burstKey={bursts[post.id]}
              onLike={toggleLike}
              onRate={ratePost}
              onComment={commentOn}
              onOpenProfile={openUserProfile}
            >
              {post.caption ? (
                <p><strong>{post.display_name}</strong> {post.caption}</p>
              ) : (
                <p className="muted">Shared a sunset</p>
              )}
            </PostCard>
          ))}
        </div>
      )}

      {view === 'compose' && (
        <form className="compose" onSubmit={submitPost}>
          <label className="photo-picker">
            {photoUrl ? (
              <img src={photoUrl} alt="Selected sunset" />
            ) : (
              <span>
                <strong>Choose a photo</strong>
                Tap to upload tonight&apos;s sky
              </span>
            )}
            <input
              type="file"
              accept="image/*"
              onChange={(e) => setPhoto(e.target.files?.[0] || null)}
            />
          </label>
          <label>
            Location
            <input
              value={locationName}
              onChange={(e) => setLocationName(e.target.value)}
              placeholder="Boston, MA"
            />
          </label>
          <label>
            Caption
            <textarea
              value={caption}
              onChange={(e) => setCaption(e.target.value)}
              rows={4}
              placeholder="How did it look?"
            />
          </label>
          <button type="submit" className="share-btn" disabled={busy}>
            {busy ? 'Posting…' : 'Share'}
          </button>
        </form>
      )}

      {view === 'profile' && viewedProfile && (
        <div className="profile">
          <div className="profile-top">
            <Avatar user={viewedProfile.user} />
            <div className="profile-stats" aria-label="Profile stats">
              <div>
                <strong>{viewedProfile.posts.length}</strong>
                <span>posts</span>
              </div>
              <div>
                <strong>{viewedProfile.user.friend_count || 0}</strong>
                <span>friends</span>
              </div>
              <div title={viewedProfile.user.rating_count ? `From ${viewedProfile.user.rating_count} ratings` : 'No ratings yet'}>
                <strong>{ratingLabel(viewedProfile.user.average_rating)}</strong>
                <span>rating</span>
              </div>
            </div>
          </div>
          <div className="profile-bio">
            <h3>{viewedProfile.user.display_name}</h3>
            <p className="username">@{viewedProfile.user.username}</p>
          </div>
          {viewedProfile.loading ? (
            <p className="muted empty-grid">Loading sunsets…</p>
          ) : viewedProfile.posts.length === 0 ? (
            <p className="muted empty-grid">No sunsets yet.</p>
          ) : (
            <div className="photo-grid">
              {viewedProfile.posts.map((post) => (
                <button
                  key={post.id}
                  type="button"
                  className="grid-cell"
                  onClick={() => openPost(post)}
                  aria-label={post.caption || `Sunset by ${viewedProfile.user.display_name}`}
                >
                  <img src={apiUrl(post.image_url)} alt="" />
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {view === 'profile' && !viewedProfile && (
        <div className="profile">
          <div className="profile-top">
            <label className="avatar-wrap">
              <Avatar user={user} />
              <span>{busy ? 'Saving…' : 'Edit photo'}</span>
              <input
                type="file"
                accept="image/*"
                disabled={busy}
                onChange={(e) => changeAvatar(e.target.files?.[0])}
              />
            </label>
            <div className="profile-stats" aria-label="Profile stats">
              <div>
                <strong>{myPosts.length}</strong>
                <span>posts</span>
              </div>
              <button type="button" onClick={() => setView('friends')}>
                <strong>{friendCount}</strong>
                <span>friends</span>
                {requestCount > 0 && <em>{requestCount} new</em>}
              </button>
              <div title={user.rating_count ? `From ${user.rating_count} ratings on your posts` : 'No ratings yet'}>
                <strong>{ratingLabel(user.average_rating)}</strong>
                <span>rating</span>
              </div>
            </div>
          </div>

          {editingIdentity ? (
            <form className="profile-form" onSubmit={saveIdentity}>
              <label>
                Name
                <input
                  required
                  value={identity.display_name}
                  onChange={(e) => setIdentity({ ...identity, display_name: e.target.value })}
                />
              </label>
              <label>
                Username
                <input
                  required
                  value={identity.username}
                  onChange={(e) => setIdentity({ ...identity, username: e.target.value })}
                />
              </label>
              <label>
                Email
                <input
                  type="email"
                  value={identity.email}
                  onChange={(e) => setIdentity({ ...identity, email: e.target.value })}
                  autoComplete="email"
                />
              </label>
              <label>
                Phone
                <input
                  type="tel"
                  value={identity.phone}
                  onChange={(e) => setIdentity({ ...identity, phone: e.target.value })}
                  autoComplete="tel"
                />
              </label>
              <div className="row-actions">
                <button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
                <button type="button" className="ghost" onClick={() => setEditingIdentity(false)}>Cancel</button>
              </div>
            </form>
          ) : (
            <div className="profile-bio">
              <h3>{user.display_name}</h3>
              <p className="username">@{user.username}</p>
              {user.email && <p className="muted">{user.email}</p>}
              {user.phone && <p className="muted">{user.phone}</p>}
              <button type="button" className="edit-profile" onClick={startIdentityEdit}>
                Edit profile
              </button>
            </div>
          )}

          {myPosts.length === 0 ? (
            <p className="muted empty-grid">You haven&apos;t shared a sunset yet.</p>
          ) : (
            <div className="photo-grid">
              {myPosts.map((post) => (
                <button
                  key={post.id}
                  type="button"
                  className="grid-cell"
                  onClick={() => openPost(post)}
                  aria-label={post.caption || 'Your sunset'}
                >
                  <img src={apiUrl(post.image_url)} alt="" />
                </button>
              ))}
            </div>
          )}

          <button type="button" className="text-btn sign-out" onClick={logout}>Sign out</button>
        </div>
      )}

      {view === 'post' && activePost && (
        <div className="feed profile-feed">
          {(viewedProfile?.posts?.length ? viewedProfile.posts : myPosts).map((post) => (
            <PostCard
              key={post.id}
              id={`profile-post-${post.id}`}
              post={post}
              showPlace={false}
              burstKey={bursts[post.id]}
              onLike={toggleLike}
              onRate={ratePost}
              onComment={commentOn}
              onOpenProfile={openUserProfile}
            >
              {editingPostId === post.id ? (
                <form className="profile-form" onSubmit={savePost}>
                  <label>
                    Caption
                    <textarea
                      rows={3}
                      value={postDraft.caption}
                      onChange={(e) => setPostDraft({ ...postDraft, caption: e.target.value })}
                    />
                  </label>
                  <label>
                    Location
                    <input
                      value={postDraft.location_name}
                      onChange={(e) => setPostDraft({ ...postDraft, location_name: e.target.value })}
                    />
                  </label>
                  <label>
                    Date
                    <input
                      type="date"
                      value={postDraft.sunset_date}
                      onChange={(e) => setPostDraft({ ...postDraft, sunset_date: e.target.value })}
                    />
                  </label>
                  <div className="row-actions">
                    <button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
                    <button type="button" className="ghost" onClick={() => setEditingPostId(null)}>Cancel</button>
                  </div>
                </form>
              ) : (
                <>
                  <p>
                    <strong>{post.display_name}</strong>
                    {' '}
                    {post.caption || 'Shared a sunset'}
                  </p>
                  <span className="muted">
                    {post.location_name || 'Unknown place'}
                    {post.sunset_date ? ` · ${post.sunset_date}` : ''}
                  </span>
                  {post.user_id === user.id && (
                    <button type="button" className="text-btn" onClick={() => startPostEdit(post)}>
                      Edit post
                    </button>
                  )}
                </>
              )}
            </PostCard>
          ))}
        </div>
      )}

      {view === 'friends' && (
        <div className="friends-panel">
          <form className="friend-search" onSubmit={searchFriends}>
            <input
              value={friendQuery}
              onChange={(e) => setFriendQuery(e.target.value)}
              placeholder="Search username"
              aria-label="Search username"
            />
            <button type="submit">Search</button>
          </form>
          {notice && <p className="social-notice">{notice}</p>}
          {searchResults.map((person) => (
            <div key={person.id} className="friend-row">
              <Avatar user={person} className="avatar avatar-sm" onClick={() => openUserProfile(person)} />
              <span className="friend-name">
                {person.display_name}
                <span className="muted">@{person.username}</span>
              </span>
              {person.relation === 'friends' && <button type="button" disabled>Friends</button>}
              {person.relation === 'outgoing' && <button type="button" disabled>Requested</button>}
              {person.relation === 'incoming' && (
                <button type="button" onClick={() => respond(person.friendship_id, true)}>Accept</button>
              )}
              {(!person.relation || person.relation === 'none') && (
                <button type="button" onClick={() => sendRequest(person.username)}>Add</button>
              )}
            </div>
          ))}
          {searched && searchResults.length === 0 && <p className="muted">No one found with that name</p>}

          {requestCount > 0 && (
            <div className="friend-block">
              <p className="eyebrow">Requests</p>
              {friends.incoming.map((person) => (
                <div key={person.friendship_id} className="friend-row">
                  <Avatar user={person} className="avatar avatar-sm" onClick={() => openUserProfile(person)} />
                  <span className="friend-name">
                    {person.display_name}
                    <span className="muted">@{person.username}</span>
                  </span>
                  <div className="row-actions">
                    <button type="button" onClick={() => respond(person.friendship_id, true)}>Accept</button>
                    <button type="button" className="ghost" onClick={() => respond(person.friendship_id, false)}>Decline</button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {(friends.outgoing || []).length > 0 && (
            <div className="friend-block">
              <p className="eyebrow">Sent</p>
              {friends.outgoing.map((person) => (
                <div key={person.friendship_id} className="friend-row">
                  <Avatar user={person} className="avatar avatar-sm" onClick={() => openUserProfile(person)} />
                  <span className="friend-name">
                    {person.display_name}
                    <span className="muted">@{person.username}</span>
                  </span>
                  <span className="muted">Pending</span>
                </div>
              ))}
            </div>
          )}

          <div className="friend-block">
            <p className="eyebrow">Friends</p>
            {friendCount === 0 && <p className="muted">No friends yet</p>}
            {(friends.friends || []).map((person) => (
              <div key={person.id} className="friend-row">
                <Avatar user={person} className="avatar avatar-sm" onClick={() => openUserProfile(person)} />
                <span className="friend-name">
                  {person.display_name}
                  <span className="muted">@{person.username}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
};

export default Social;
