"""
SQLite-backed social store for SunCast
======================================
Users, friend requests, and sunset photo posts.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, List, Optional

from werkzeug.security import check_password_hash, generate_password_hash


DEFAULT_DB = os.path.join(os.path.dirname(__file__), "data", "suncast_social.db")


class SocialStore:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or os.getenv("SOCIAL_DB_PATH", DEFAULT_DB)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    display_name TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tokens (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS friendships (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    requester_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    addressee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'accepted')),
                    created_at TEXT NOT NULL,
                    UNIQUE(requester_id, addressee_id)
                );

                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    image_path TEXT NOT NULL,
                    caption TEXT,
                    location_name TEXT,
                    sunset_date TEXT,
                    aesthetic_score REAL,
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
            if "avatar_path" not in columns:
                conn.execute("ALTER TABLE users ADD COLUMN avatar_path TEXT")

    def register(self, username: str, password: str, display_name: str = None) -> Dict:
        username = (username or "").strip()
        if len(username) < 3:
            raise ValueError("Username must be at least 3 characters")
        if len(password or "") < 6:
            raise ValueError("Password must be at least 6 characters")
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            try:
                cur = conn.execute(
                    "INSERT INTO users (username, password_hash, display_name, created_at) VALUES (?, ?, ?, ?)",
                    (username, generate_password_hash(password), display_name or username, now),
                )
            except sqlite3.IntegrityError as e:
                raise ValueError("Username already taken") from e
            user_id = cur.lastrowid
        return self.create_session(user_id)

    def login(self, username: str, password: str) -> Dict:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?",
                ((username or "").strip(),),
            ).fetchone()
        if not row or not check_password_hash(row["password_hash"], password or ""):
            raise ValueError("Invalid username or password")
        return self.create_session(row["id"])

    def create_session(self, user_id: int) -> Dict:
        token = secrets.token_urlsafe(32)
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO tokens (token, user_id, created_at) VALUES (?, ?, ?)",
                (token, user_id, now),
            )
            user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return {
            "token": token,
            "user": self._user_public(user),
        }

    def user_from_token(self, token: str) -> Optional[Dict]:
        if not token:
            return None
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT u.* FROM users u
                JOIN tokens t ON t.user_id = u.id
                WHERE t.token = ?
                """,
                (token,),
            ).fetchone()
        return self._user_public(row) if row else None

    def _user_public(self, row) -> Dict:
        avatar_path = row["avatar_path"] if "avatar_path" in row.keys() else None
        return {
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"] or row["username"],
            "avatar_url": f"/uploads/{os.path.basename(avatar_path)}" if avatar_path else None,
            "created_at": row["created_at"],
        }

    def update_profile(self, user_id: int, display_name: str = None, username: str = None) -> Dict:
        with self._conn() as conn:
            user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not user:
                raise ValueError("User not found")
            new_name = user["display_name"] if display_name is None else (display_name or "").strip()
            new_username = user["username"] if username is None else (username or "").strip()
            if len(new_username) < 3:
                raise ValueError("Username must be at least 3 characters")
            if not new_name:
                new_name = new_username
            try:
                conn.execute(
                    "UPDATE users SET display_name = ?, username = ? WHERE id = ?",
                    (new_name, new_username, user_id),
                )
            except sqlite3.IntegrityError as e:
                raise ValueError("Username already taken") from e
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._user_public(row)

    def set_avatar(self, user_id: int, image_path: str) -> Dict:
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET avatar_path = ? WHERE id = ?",
                (image_path, user_id),
            )
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._user_public(row)

    def search_users(self, query: str, exclude_user_id: int = None) -> List[Dict]:
        term = (query or "").strip().lstrip("@")
        q = f"%{term}%"
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM users
                WHERE username LIKE ? OR display_name LIKE ?
                ORDER BY username LIMIT 20
                """,
                (q, q),
            ).fetchall()
            relations = {}
            if exclude_user_id:
                rel_rows = conn.execute(
                    """
                    SELECT * FROM friendships
                    WHERE requester_id = ? OR addressee_id = ?
                    """,
                    (exclude_user_id, exclude_user_id),
                ).fetchall()
                for rel in rel_rows:
                    other_id = rel["addressee_id"] if rel["requester_id"] == exclude_user_id else rel["requester_id"]
                    if rel["status"] == "accepted":
                        kind = "friends"
                    elif rel["requester_id"] == exclude_user_id:
                        kind = "outgoing"
                    else:
                        kind = "incoming"
                    relations[other_id] = {"relation": kind, "friendship_id": rel["id"]}
        users = []
        for row in rows:
            if exclude_user_id and row["id"] == exclude_user_id:
                continue
            user = self._user_public(row)
            user.update(relations.get(row["id"], {"relation": "none", "friendship_id": None}))
            users.append(user)
        return users

    def request_friend(self, requester_id: int, username: str) -> Dict:
        username = (username or "").strip().lstrip("@")
        with self._conn() as conn:
            other = conn.execute(
                "SELECT * FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if not other:
                raise ValueError("User not found")
            if other["id"] == requester_id:
                raise ValueError("Cannot friend yourself")
            existing = conn.execute(
                """
                SELECT * FROM friendships
                WHERE (requester_id = ? AND addressee_id = ?)
                   OR (requester_id = ? AND addressee_id = ?)
                """,
                (requester_id, other["id"], other["id"], requester_id),
            ).fetchone()
            if existing:
                # They already asked us, so Add should complete the friendship.
                if existing["status"] == "pending" and existing["addressee_id"] == requester_id:
                    conn.execute(
                        "UPDATE friendships SET status = 'accepted' WHERE id = ?",
                        (existing["id"],),
                    )
                    return {"id": existing["id"], "status": "accepted", "to": self._user_public(other)}
                return {
                    "id": existing["id"],
                    "status": existing["status"],
                    "message": "Already friends" if existing["status"] == "accepted" else "Request already sent",
                }
            now = datetime.utcnow().isoformat()
            cur = conn.execute(
                """
                INSERT INTO friendships (requester_id, addressee_id, status, created_at)
                VALUES (?, ?, 'pending', ?)
                """,
                (requester_id, other["id"], now),
            )
            return {"id": cur.lastrowid, "status": "pending", "to": self._user_public(other)}

    def respond_friend(self, user_id: int, friendship_id: int, accept: bool) -> Dict:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM friendships WHERE id = ?",
                (friendship_id,),
            ).fetchone()
            if not row or row["addressee_id"] != user_id:
                raise ValueError("Friend request not found")
            if accept:
                conn.execute(
                    "UPDATE friendships SET status = 'accepted' WHERE id = ?",
                    (friendship_id,),
                )
                status = "accepted"
            else:
                conn.execute("DELETE FROM friendships WHERE id = ?", (friendship_id,))
                status = "declined"
        return {"id": friendship_id, "status": status}

    def list_friends(self, user_id: int) -> Dict:
        with self._conn() as conn:
            accepted = conn.execute(
                """
                SELECT u.* FROM users u
                JOIN friendships f ON (
                    (f.requester_id = ? AND f.addressee_id = u.id)
                    OR (f.addressee_id = ? AND f.requester_id = u.id)
                )
                WHERE f.status = 'accepted'
                ORDER BY u.username
                """,
                (user_id, user_id),
            ).fetchall()
            incoming = conn.execute(
                """
                SELECT f.id as friendship_id, u.*
                FROM friendships f
                JOIN users u ON u.id = f.requester_id
                WHERE f.addressee_id = ? AND f.status = 'pending'
                """,
                (user_id,),
            ).fetchall()
            outgoing = conn.execute(
                """
                SELECT f.id as friendship_id, u.*
                FROM friendships f
                JOIN users u ON u.id = f.addressee_id
                WHERE f.requester_id = ? AND f.status = 'pending'
                """,
                (user_id,),
            ).fetchall()
        return {
            "friends": [self._user_public(r) for r in accepted],
            "incoming": [
                {**self._user_public(r), "friendship_id": r["friendship_id"]}
                for r in incoming
            ],
            "outgoing": [
                {**self._user_public(r), "friendship_id": r["friendship_id"]}
                for r in outgoing
            ],
        }

    def create_post(
        self,
        user_id: int,
        image_path: str,
        caption: str = "",
        location_name: str = "",
        sunset_date: str = "",
        aesthetic_score: float = None,
    ) -> Dict:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO posts
                (user_id, image_path, caption, location_name, sunset_date, aesthetic_score, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    image_path,
                    caption or "",
                    location_name or "",
                    sunset_date or "",
                    aesthetic_score,
                    now,
                ),
            )
            post_id = cur.lastrowid
        return self.get_post(post_id)

    def posts_for_user(self, user_id: int) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT p.*, u.username, u.display_name
                FROM posts p JOIN users u ON u.id = p.user_id
                WHERE p.user_id = ?
                ORDER BY p.created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [self._post_public(r) for r in rows]

    def update_post(
        self,
        user_id: int,
        post_id: int,
        caption: str = "",
        location_name: str = "",
        sunset_date: str = "",
    ) -> Dict:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM posts WHERE id = ? AND user_id = ?",
                (post_id, user_id),
            ).fetchone()
            if not row:
                raise ValueError("Post not found")
            conn.execute(
                """
                UPDATE posts
                SET caption = ?, location_name = ?, sunset_date = ?
                WHERE id = ? AND user_id = ?
                """,
                (caption or "", location_name or "", sunset_date or "", post_id, user_id),
            )
        return self.get_post(post_id)

    def get_post(self, post_id: int) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT p.*, u.username, u.display_name
                FROM posts p JOIN users u ON u.id = p.user_id
                WHERE p.id = ?
                """,
                (post_id,),
            ).fetchone()
        return self._post_public(row) if row else None

    def feed_for_user(self, user_id: int, limit: int = 50) -> List[Dict]:
        """Posts from self + accepted friends, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT p.*, u.username, u.display_name
                FROM posts p
                JOIN users u ON u.id = p.user_id
                WHERE p.user_id = ?
                   OR p.user_id IN (
                        SELECT CASE
                            WHEN requester_id = ? THEN addressee_id
                            ELSE requester_id
                        END
                        FROM friendships
                        WHERE status = 'accepted'
                          AND (requester_id = ? OR addressee_id = ?)
                   )
                ORDER BY p.created_at DESC
                LIMIT ?
                """,
                (user_id, user_id, user_id, user_id, limit),
            ).fetchall()
        return [self._post_public(r) for r in rows]

    def _post_public(self, row) -> Dict:
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "username": row["username"],
            "display_name": row["display_name"] or row["username"],
            "image_url": f"/uploads/{os.path.basename(row['image_path'])}",
            "caption": row["caption"] or "",
            "location_name": row["location_name"] or "",
            "sunset_date": row["sunset_date"] or "",
            "aesthetic_score": row["aesthetic_score"],
            "created_at": row["created_at"],
        }
