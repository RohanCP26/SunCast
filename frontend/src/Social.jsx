import React, { useEffect, useState } from 'react';
import { apiJson, apiUrl, authHeaders } from './api';
import './Social.css';

const initialOf = (name) => (name || '?').trim().charAt(0).toUpperCase();

const Avatar = ({ user, className = 'avatar' }) => {
  if (user?.avatar_url) {
    return <img className={className} src={apiUrl(user.avatar_url)} alt="" />;
  }
  return <span className={`${className} avatar-fallback`} aria-hidden="true">{initialOf(user?.display_name)}</span>;
};

const Social = () => {
  const [user, setUser] = useState(null);
  const [authMode, setAuthMode] = useState('login');
  const [form, setForm] = useState({ username: '', password: '', display_name: '' });
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
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState('feed');
  const [myPosts, setMyPosts] = useState([]);
  const [editingIdentity, setEditingIdentity] = useState(false);
  const [identity, setIdentity] = useState({ display_name: '', username: '' });
  const [editingPostId, setEditingPostId] = useState(null);
  const [postDraft, setPostDraft] = useState({ caption: '', location_name: '', sunset_date: '' });

  const friendCount = (friends.friends || []).length;
  const friendLabel = friendCount === 1 ? '1 friend' : `${friendCount} friends`;

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

  useEffect(() => {
    const token = localStorage.getItem('suncast_token');
    if (!token) return;
    refresh().catch(() => {
      localStorage.removeItem('suncast_token');
      setUser(null);
    });
  }, []);

  const handleAuth = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const path = authMode === 'login' ? '/api/social/login' : '/api/social/register';
      const data = await apiJson(path, {
        method: 'POST',
        body: JSON.stringify(form),
      });
      localStorage.setItem('suncast_token', data.token);
      setUser(data.user);
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const logout = () => {
    localStorage.removeItem('suncast_token');
    setUser(null);
    setFeed([]);
    setView('feed');
    setMyPosts([]);
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
        headers: authHeaders(),
        body,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Upload failed');
      setCaption('');
      setLocationName('');
      setPhoto(null);
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const openProfile = async () => {
    setView('profile');
    setEditingIdentity(false);
    setEditingPostId(null);
    setError(null);
    try {
      await loadMyPosts();
    } catch (err) {
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
        headers: authHeaders(),
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
      setEditingPostId(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  if (!user) {
    return (
      <section className="social-page">
        <header className="social-hero">
          <p className="eyebrow">Community</p>
          <h2>Share tonight&apos;s sky</h2>
          <p>Post your sunset and follow friends&apos; golden hours.</p>
        </header>

        <form className="social-auth" onSubmit={handleAuth}>
          <div className="auth-tabs">
            <button type="button" className={authMode === 'login' ? 'active' : ''} onClick={() => setAuthMode('login')}>
              Sign in
            </button>
            <button type="button" className={authMode === 'register' ? 'active' : ''} onClick={() => setAuthMode('register')}>
              Create account
            </button>
          </div>
          {authMode === 'register' && (
            <label>
              Display name
              <input
                value={form.display_name}
                onChange={(e) => setForm({ ...form, display_name: e.target.value })}
              />
            </label>
          )}
          <label>
            Username
            <input
              required
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
            />
          </label>
          <label>
            Password
            <input
              required
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
            />
          </label>
          {error && <p className="social-error">{error}</p>}
          <button type="submit" disabled={busy}>
            {busy ? 'Please wait…' : authMode === 'login' ? 'Sign in' : 'Join SunCast'}
          </button>
        </form>
      </section>
    );
  }

  return (
    <section className="social-page">
      <header className="social-hero">
        {view === 'feed' && (
          <>
            <p className="eyebrow">Signed in as {user.display_name}</p>
            <h2>Friends&apos; sunsets</h2>
          </>
        )}
        {view === 'profile' && (
          <>
            <button type="button" className="text-btn back-link" onClick={() => setView('feed')}>
              Back to feed
            </button>
            <p className="eyebrow">Your profile</p>
            <h2>{user.display_name}</h2>
          </>
        )}
        {view === 'friends' && (
          <>
            <button type="button" className="text-btn back-link" onClick={() => setView('profile')}>
              Back to profile
            </button>
            <p className="eyebrow">Your circle</p>
            <h2>Friends</h2>
          </>
        )}
        <div className="hero-actions">
          {view !== 'profile' && view !== 'friends' && (
            <button type="button" className="text-btn" onClick={openProfile}>Your profile</button>
          )}
          <button type="button" className="text-btn" onClick={logout}>Sign out</button>
        </div>
      </header>

      {error && <p className="social-error">{error}</p>}

      {view === 'profile' && (
        <>
          <div className="profile-head">
            <div className="avatar-wrap">
              <Avatar user={user} />
              <label className="change-photo">
                Change photo
                <input
                  type="file"
                  accept="image/*"
                  disabled={busy}
                  onChange={(e) => changeAvatar(e.target.files?.[0])}
                />
              </label>
            </div>
            <div className="profile-identity">
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
                  <div className="row-actions">
                    <button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
                    <button type="button" className="ghost" onClick={() => setEditingIdentity(false)}>Cancel</button>
                  </div>
                </form>
              ) : (
                <>
                  <h3>{user.display_name}</h3>
                  <p className="username">@{user.username}</p>
                  <button type="button" className="text-btn" onClick={startIdentityEdit}>
                    Edit name and username
                  </button>
                </>
              )}
              <button type="button" className="friend-count" onClick={() => setView('friends')}>
                {friendLabel}
              </button>
            </div>
          </div>

          <div className="feed">
            <h3>Your posts</h3>
            {myPosts.length === 0 && <p className="muted">You haven&apos;t shared a sunset yet.</p>}
            {myPosts.map((post) => (
              <article key={post.id} className="post-card">
                <img src={apiUrl(post.image_url)} alt={post.caption || 'Sunset'} />
                <div className="post-meta">
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
                        <button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save post'}</button>
                        <button type="button" className="ghost" onClick={() => setEditingPostId(null)}>Cancel</button>
                      </div>
                    </form>
                  ) : (
                    <>
                      <strong>{post.display_name}</strong>
                      <span>
                        {post.location_name || 'Unknown place'}
                        {post.sunset_date ? ` · ${post.sunset_date}` : ''}
                      </span>
                      {post.caption && <p>{post.caption}</p>}
                      <button type="button" className="text-btn" onClick={() => startPostEdit(post)}>
                        Edit post
                      </button>
                    </>
                  )}
                </div>
              </article>
            ))}
          </div>
        </>
      )}

      {view === 'friends' && (
        <div className="friends-panel friend-list">
          {friendCount === 0 && <p className="muted">No friends yet</p>}
          {(friends.friends || []).map((person) => (
            <div key={person.id} className="friend-row">
              <Avatar user={person} className="avatar avatar-sm" />
              <span className="friend-name">
                {person.display_name}
                <span className="muted">@{person.username}</span>
              </span>
            </div>
          ))}
        </div>
      )}

      {view === 'feed' && (
        <>
          <div className="social-grid">
            <form className="compose" onSubmit={submitPost}>
              <h3>Post today&apos;s sunset</h3>
              <label>
                Photo
                <input type="file" accept="image/*" onChange={(e) => setPhoto(e.target.files?.[0] || null)} />
              </label>
              <label>
                Location
                <input value={locationName} onChange={(e) => setLocationName(e.target.value)} placeholder="Boston, MA" />
              </label>
              <label>
                Caption
                <textarea value={caption} onChange={(e) => setCaption(e.target.value)} rows={3} />
              </label>
              <button type="submit" disabled={busy}>{busy ? 'Posting…' : 'Share photo'}</button>
            </form>

            <aside className="friends-panel">
              <h3>Friends</h3>
              <form className="friend-search" onSubmit={searchFriends}>
                <input
                  value={friendQuery}
                  onChange={(e) => setFriendQuery(e.target.value)}
                  placeholder="Find username"
                  aria-label="Find username"
                />
                <button type="submit">Search</button>
              </form>
              {notice && <p className="social-notice">{notice}</p>}
              {searchResults.map((u) => (
                <div key={u.id} className="friend-row">
                  <span>@{u.username}</span>
                  {u.relation === 'friends' && <button type="button" disabled>Friends</button>}
                  {u.relation === 'outgoing' && <button type="button" disabled>Requested</button>}
                  {u.relation === 'incoming' && (
                    <button type="button" onClick={() => respond(u.friendship_id, true)}>Accept</button>
                  )}
                  {(!u.relation || u.relation === 'none') && (
                    <button type="button" onClick={() => sendRequest(u.username)}>Add</button>
                  )}
                </div>
              ))}
              {searched && searchResults.length === 0 && <p className="muted">No one found with that name</p>}
              {friends.incoming?.length > 0 && (
                <div className="friend-block">
                  <p className="eyebrow">Requests</p>
                  {friends.incoming.map((u) => (
                    <div key={u.friendship_id} className="friend-row">
                      <span>@{u.username}</span>
                      <div className="row-actions">
                        <button type="button" onClick={() => respond(u.friendship_id, true)}>Accept</button>
                        <button type="button" className="ghost" onClick={() => respond(u.friendship_id, false)}>Decline</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {friends.outgoing?.length > 0 && (
                <div className="friend-block">
                  <p className="eyebrow">Sent requests</p>
                  {friends.outgoing.map((u) => (
                    <div key={u.friendship_id} className="friend-row">
                      <span>{u.display_name}</span>
                      <span className="muted">Pending</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="friend-block">
                <p className="eyebrow">Your circle</p>
                <button type="button" className="friend-count" onClick={() => setView('friends')}>
                  {friendLabel}
                </button>
                {(friends.friends || []).length === 0 && <p className="muted">No friends yet</p>}
                {(friends.friends || []).map((u) => (
                  <div key={u.id} className="friend-row">
                    <span>{u.display_name}</span>
                    <span className="muted">@{u.username}</span>
                  </div>
                ))}
              </div>
            </aside>
          </div>

          <div className="feed">
            <h3>Feed</h3>
            {feed.length === 0 && <p className="muted">No posts yet — be the first to share tonight.</p>}
            {feed.map((post) => (
              <article key={post.id} className="post-card">
                <img src={apiUrl(post.image_url)} alt={post.caption || 'Sunset'} />
                <div className="post-meta">
                  <strong>{post.display_name}</strong>
                  <span>
                    {post.location_name || 'Unknown place'}
                    {post.sunset_date ? ` · ${post.sunset_date}` : ''}
                  </span>
                  {post.caption && <p>{post.caption}</p>}
                </div>
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  );
};

export default Social;
