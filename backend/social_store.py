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
from datetime import datetime, timedelta
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

                CREATE TABLE IF NOT EXISTS likes (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, post_id)
                );

                CREATE TABLE IF NOT EXISTS ratings (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                    score INTEGER NOT NULL CHECK(score BETWEEN 1 AND 10),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, post_id)
                );

                CREATE TABLE IF NOT EXISTS comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
            if "avatar_path" not in columns:
                conn.execute("ALTER TABLE users ADD COLUMN avatar_path TEXT")
            if "email" not in columns:
                conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
            if "phone" not in columns:
                conn.execute("ALTER TABLE users ADD COLUMN phone TEXT")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique ON users(email) WHERE email IS NOT NULL"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS users_phone_unique ON users(phone) WHERE phone IS NOT NULL"
            )
            if "public_id" not in columns:
                conn.execute("ALTER TABLE users ADD COLUMN public_id TEXT")
            conn.execute(
                """
                UPDATE users
                SET public_id = lower(hex(randomblob(16)))
                WHERE public_id IS NULL OR public_id = ''
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS users_public_id_unique ON users(public_id)"
            )
            try:
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS users_username_nocase ON users(username COLLATE NOCASE)"
                )
            except sqlite3.IntegrityError:
                pass
            token_cols = {row["name"] for row in conn.execute("PRAGMA table_info(tokens)")}
            if "expires_at" not in token_cols:
                conn.execute("ALTER TABLE tokens ADD COLUMN expires_at TEXT")
            later = (datetime.utcnow() + timedelta(days=30)).isoformat(timespec="seconds")
            conn.execute(
                "UPDATE tokens SET expires_at = ? WHERE expires_at IS NULL",
                (later,),
            )
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS reset_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    code_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS blocks (
                    blocker_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    blocked_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (blocker_id, blocked_id)
                );

                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reporter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    target_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    post_id INTEGER REFERENCES posts(id) ON DELETE SET NULL,
                    comment_id INTEGER REFERENCES comments(id) ON DELETE SET NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def register(self, username: str, password: str, display_name: str = None, email: str = None, phone: str = None) -> Dict:
        username = (username or "").strip()
        if len(username) < 3:
            raise ValueError("Username must be at least 3 characters")
        if len(password or "") < 6:
            raise ValueError("Password must be at least 6 characters")
        email = self._normalize_email(email)
        phone = self._normalize_phone(phone)
        if not email and not phone:
            raise ValueError("Add an email or a phone number so you can reset your password")
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO users (username, password_hash, display_name, created_at, email, phone, public_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        username,
                        generate_password_hash(password),
                        display_name or username,
                        now,
                        email,
                        phone,
                        secrets.token_hex(16),
                    ),
                )
            except sqlite3.IntegrityError as e:
                raise ValueError(self._taken_message(e)) from e
            user_id = cur.lastrowid
        return self.create_session(user_id)

    def login(self, username: str, password: str) -> Dict:
        with self._conn() as conn:
            row = self._find_account(conn, username, allow_username=True)
        if not row or not check_password_hash(row["password_hash"], password or ""):
            raise ValueError("Wrong email, phone, or password")
        return self.create_session(row["id"])

    def request_reset(self, contact: str) -> Optional[Dict]:
        """Create a 15-minute code. None means no matching account. The code is not logged."""
        with self._conn() as conn:
            row = self._find_account(conn, contact, allow_username=False)
            if not row:
                return None
            code = f"{secrets.randbelow(1000000):06d}"
            now = datetime.utcnow()
            conn.execute("DELETE FROM reset_codes WHERE user_id = ?", (row["id"],))
            conn.execute(
                """
                INSERT INTO reset_codes (user_id, code_hash, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    row["id"],
                    generate_password_hash(code),
                    (now + timedelta(minutes=15)).isoformat(timespec="seconds"),
                    now.isoformat(timespec="seconds"),
                ),
            )
            email = row["email"]
            phone = row["phone"]
        return {"email": email, "phone": phone, "code": code}

    def confirm_reset(self, contact: str, code: str, password: str) -> None:
        if len(password or "") < 6:
            raise ValueError("Password must be at least 6 characters")
        cleaned = "".join(ch for ch in str(code or "") if ch.isdigit())
        with self._conn() as conn:
            row = self._find_account(conn, contact, allow_username=False)
            match = None
            if row and len(cleaned) == 6:
                codes = conn.execute(
                    """
                    SELECT * FROM reset_codes
                    WHERE user_id = ?
                    ORDER BY id DESC
                    LIMIT 5
                    """,
                    (row["id"],),
                ).fetchall()
                now = datetime.utcnow()
                for item in codes:
                    try:
                        expires = datetime.fromisoformat(item["expires_at"])
                    except ValueError:
                        continue
                    if expires > now and check_password_hash(item["code_hash"], cleaned):
                        match = item
                        break
            if not match:
                raise ValueError("That code is wrong or expired")
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash(password), row["id"]),
            )
            conn.execute("DELETE FROM reset_codes WHERE user_id = ?", (row["id"],))
            conn.execute("DELETE FROM tokens WHERE user_id = ?", (row["id"],))

    def create_session(self, user_id: int) -> Dict:
        token = secrets.token_urlsafe(32)
        now = datetime.utcnow()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO tokens (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (
                    token,
                    user_id,
                    now.isoformat(timespec="seconds"),
                    (now + timedelta(days=30)).isoformat(timespec="seconds"),
                ),
            )
            user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return {
            "token": token,
            "user": self._user_public(user, include_contact=True),
        }

    def user_from_token(self, token: str) -> Optional[Dict]:
        if not token:
            return None
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT u.*, t.expires_at AS token_expires
                FROM users u
                JOIN tokens t ON t.user_id = u.id
                WHERE t.token = ?
                """,
                (token,),
            ).fetchone()
            if not row:
                return None
            try:
                expires = datetime.fromisoformat(row["token_expires"] or "")
            except ValueError:
                expires = datetime.utcnow()
            if expires <= datetime.utcnow():
                conn.execute("DELETE FROM tokens WHERE token = ?", (token,))
                return None
            user = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
        return self._user_public(user, include_contact=True) if user else None

    def logout(self, token: str) -> None:
        if not token:
            return
        with self._conn() as conn:
            conn.execute("DELETE FROM tokens WHERE token = ?", (token,))

    def change_password(self, user_id: int, current: str, new_password: str, keep_token: str = None) -> None:
        if len(new_password or "") < 6:
            raise ValueError("Password must be at least 6 characters")
        with self._conn() as conn:
            row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row or not check_password_hash(row["password_hash"], current or ""):
                raise ValueError("Current password is wrong")
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash(new_password), user_id),
            )
            conn.execute(
                "DELETE FROM tokens WHERE user_id = ? AND token != ?",
                (user_id, keep_token or ""),
            )

    def delete_account(self, user_id: int) -> List[str]:
        with self._conn() as conn:
            user = conn.execute("SELECT avatar_path FROM users WHERE id = ?", (user_id,)).fetchone()
            posts = conn.execute(
                "SELECT image_path FROM posts WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            paths = []
            if user and user["avatar_path"]:
                paths.append(user["avatar_path"])
            paths.extend(row["image_path"] for row in posts if row["image_path"])
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return paths

    def delete_post(self, user_id: int, post_id: int) -> str:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT image_path FROM posts WHERE id = ? AND user_id = ?",
                (post_id, user_id),
            ).fetchone()
            if not row:
                raise ValueError("Post not found")
            conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        return row["image_path"]

    def _normalize_email(self, value: str) -> Optional[str]:
        email = (value or "").strip().lower()
        if not email:
            return None
        if " " in email or "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("Enter a valid email")
        return email

    def _normalize_phone(self, value: str) -> Optional[str]:
        raw = (value or "").strip()
        if not raw:
            return None
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) < 7:
            raise ValueError("Enter a valid phone number")
        return digits

    def _taken_message(self, error: sqlite3.IntegrityError) -> str:
        message = str(error).lower()
        return "That email, phone, or username is already in use"

    def _find_account(self, conn, contact: str, allow_username: bool):
        text = (contact or "").strip()
        if not text:
            return None
        if "@" in text:
            return conn.execute(
                "SELECT * FROM users WHERE email = ?",
                (text.lower(),),
            ).fetchone()
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) >= 7:
            row = conn.execute(
                "SELECT * FROM users WHERE phone = ?",
                (digits,),
            ).fetchone()
            if row or not allow_username:
                return row
        if not allow_username:
            return None
        return conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (text,),
        ).fetchone()

    def _user_public(self, row, include_contact: bool = False) -> Dict:
        avatar_path = row["avatar_path"] if "avatar_path" in row.keys() else None
        summary = self.received_rating(row["id"])
        data = {
            "id": row["id"],
            "public_id": row["public_id"] if "public_id" in row.keys() else None,
            "username": row["username"],
            "display_name": row["display_name"] or row["username"],
            "avatar_url": f"/uploads/{os.path.basename(avatar_path)}" if avatar_path else None,
            "created_at": row["created_at"],
            "average_rating": summary["average_rating"],
            "rating_count": summary["rating_count"],
        }
        if include_contact:
            keys = row.keys()
            data["email"] = row["email"] if "email" in keys else None
            data["phone"] = row["phone"] if "phone" in keys else None
        return data

    def received_rating(self, user_id: int) -> Dict:
        """Mean of every rating left on this person's posts."""
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT AVG(r.score) AS average_rating, COUNT(r.score) AS rating_count
                FROM ratings r
                JOIN posts p ON p.id = r.post_id
                WHERE p.user_id = ?
                """,
                (user_id,),
            ).fetchone()
        count = int(row["rating_count"] or 0)
        average = row["average_rating"]
        return {
            "average_rating": round(float(average), 1) if count and average is not None else None,
            "rating_count": count,
        }

    def update_profile(self, user_id: int, display_name: str = None, username: str = None, email: str = None, phone: str = None, update_contact: bool = False) -> Dict:
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
            new_email = user["email"] if "email" in user.keys() else None
            new_phone = user["phone"] if "phone" in user.keys() else None
            if update_contact:
                new_email = self._normalize_email(email)
                new_phone = self._normalize_phone(phone)
                if not new_email and not new_phone:
                    raise ValueError("Keep an email or a phone number on the account")
            try:
                conn.execute(
                    "UPDATE users SET display_name = ?, username = ?, email = ?, phone = ? WHERE id = ?",
                    (new_name, new_username, new_email, new_phone, user_id),
                )
            except sqlite3.IntegrityError as e:
                raise ValueError(self._taken_message(e)) from e
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._user_public(row, include_contact=True)

    def set_avatar(self, user_id: int, image_path: str) -> Dict:
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET avatar_path = ? WHERE id = ?",
                (image_path, user_id),
            )
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._user_public(row, include_contact=True)

    def clear_avatar(self, user_id: int):
        """Drop the profile photo and return (user, previous file path)."""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            old_path = row["avatar_path"] if row and "avatar_path" in row.keys() else None
            conn.execute("UPDATE users SET avatar_path = NULL WHERE id = ?", (user_id,))
            updated = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._user_public(updated, include_contact=True), old_path

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
            relations = self._friend_relations(conn, exclude_user_id) if exclude_user_id else {}
            hidden = self._hidden_user_ids(conn, exclude_user_id) if exclude_user_id else set()
        users = []
        for row in rows:
            if exclude_user_id and row["id"] == exclude_user_id:
                continue
            if row["id"] in hidden:
                continue
            user = self._user_public(row)
            user.update(relations.get(row["id"], {"relation": "none", "friendship_id": None}))
            users.append(user)
        return users

    def _friend_relations(self, conn, user_id: int) -> Dict:
        relations = {}
        rel_rows = conn.execute(
            """
            SELECT * FROM friendships
            WHERE requester_id = ? OR addressee_id = ?
            """,
            (user_id, user_id),
        ).fetchall()
        for rel in rel_rows:
            other_id = rel["addressee_id"] if rel["requester_id"] == user_id else rel["requester_id"]
            if rel["status"] == "accepted":
                kind = "friends"
            elif rel["requester_id"] == user_id:
                kind = "outgoing"
            else:
                kind = "incoming"
            relations[other_id] = {"relation": kind, "friendship_id": rel["id"]}
        return relations

    def _hidden_user_ids(self, conn, user_id: int) -> set:
        rows = conn.execute(
            """
            SELECT blocked_id AS other_id FROM blocks WHERE blocker_id = ?
            UNION
            SELECT blocker_id AS other_id FROM blocks WHERE blocked_id = ?
            """,
            (user_id, user_id),
        ).fetchall()
        return {row["other_id"] for row in rows}

    def _are_friends(self, conn, left_id: int, right_id: int) -> bool:
        row = conn.execute(
            """
            SELECT 1 FROM friendships
            WHERE status = 'accepted'
              AND (
                (requester_id = ? AND addressee_id = ?)
                OR (requester_id = ? AND addressee_id = ?)
              )
            """,
            (left_id, right_id, right_id, left_id),
        ).fetchone()
        return row is not None

    def _can_view_posts(self, conn, viewer_id: int, owner_id: int) -> bool:
        if not viewer_id or not owner_id:
            return False
        if owner_id in self._hidden_user_ids(conn, viewer_id):
            return False
        if viewer_id == owner_id:
            return True
        return self._are_friends(conn, viewer_id, owner_id)

    def _require_visible_post(self, conn, viewer_id: int, post_id: int):
        row = conn.execute("SELECT id, user_id FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not row or not self._can_view_posts(conn, viewer_id, row["user_id"]):
            raise ValueError("Post not found")
        return row

    def _phone_lookup_keys(self, value: str) -> List[str]:
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        if len(digits) < 7:
            return []
        keys = [digits]
        if len(digits) == 11 and digits.startswith("1"):
            keys.append(digits[1:])
        elif len(digits) == 10:
            keys.append("1" + digits)
        return keys

    def suggest_from_contacts(self, user_id: int, emails, phones) -> List[Dict]:
        """Match account email or phone against a contact list. The list is not stored."""
        email_keys = []
        seen_emails = set()
        for raw in (emails or [])[:1000]:
            try:
                email = self._normalize_email(str(raw))
            except ValueError:
                continue
            if email and email not in seen_emails:
                seen_emails.add(email)
                email_keys.append(email)

        phone_keys = []
        seen_phones = set()
        for raw in (phones or [])[:1000]:
            for key in self._phone_lookup_keys(raw):
                if key not in seen_phones:
                    seen_phones.add(key)
                    phone_keys.append(key)

        if not email_keys and not phone_keys:
            return []

        matched = {}
        with self._conn() as conn:
            for chunk in self._chunks(email_keys, 400):
                marks = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT * FROM users WHERE email IN ({marks})",
                    tuple(chunk),
                ).fetchall()
                for row in rows:
                    matched[row["id"]] = row
            for chunk in self._chunks(phone_keys, 400):
                marks = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT * FROM users WHERE phone IN ({marks})",
                    tuple(chunk),
                ).fetchall()
                for row in rows:
                    matched[row["id"]] = row
            relations = self._friend_relations(conn, user_id)
            hidden = self._hidden_user_ids(conn, user_id)

        people = []
        for row in matched.values():
            if row["id"] == user_id or row["id"] in hidden:
                continue
            person = self._user_public(row)
            person.update(relations.get(row["id"], {"relation": "none", "friendship_id": None}))
            people.append(person)
        people.sort(key=lambda person: (person.get("display_name") or "").lower())
        return people

    @staticmethod
    def _chunks(values: List, size: int):
        for start in range(0, len(values), size):
            yield values[start:start + size]

    def request_friend(self, requester_id: int, username: str) -> Dict:
        username = (username or "").strip().lstrip("@")
        with self._conn() as conn:
            other = conn.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                (username,),
            ).fetchone()
            if not other:
                raise ValueError("User not found")
            if other["id"] == requester_id:
                raise ValueError("Cannot friend yourself")
            if other["id"] in self._hidden_user_ids(conn, requester_id):
                raise ValueError("You can't add this person")
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

    def cancel_request(self, user_id: int, friendship_id: int) -> None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM friendships WHERE id = ?",
                (friendship_id,),
            ).fetchone()
            if not row or row["requester_id"] != user_id or row["status"] != "pending":
                raise ValueError("Friend request not found")
            conn.execute("DELETE FROM friendships WHERE id = ?", (friendship_id,))

    def unfriend(self, user_id: int, friendship_id: int) -> None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM friendships WHERE id = ?",
                (friendship_id,),
            ).fetchone()
            if not row or row["status"] != "accepted":
                raise ValueError("Friend not found")
            if user_id not in (row["requester_id"], row["addressee_id"]):
                raise ValueError("Friend not found")
            conn.execute("DELETE FROM friendships WHERE id = ?", (friendship_id,))

    def block_user(self, user_id: int, public_id: str) -> None:
        with self._conn() as conn:
            other = conn.execute(
                "SELECT id FROM users WHERE public_id = ?",
                ((public_id or "").strip(),),
            ).fetchone()
            if not other or other["id"] == user_id:
                raise ValueError("User not found")
            now = datetime.utcnow().isoformat(timespec="seconds")
            conn.execute(
                """
                INSERT INTO blocks (blocker_id, blocked_id, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(blocker_id, blocked_id) DO NOTHING
                """,
                (user_id, other["id"], now),
            )
            conn.execute(
                """
                DELETE FROM friendships
                WHERE (requester_id = ? AND addressee_id = ?)
                   OR (requester_id = ? AND addressee_id = ?)
                """,
                (user_id, other["id"], other["id"], user_id),
            )

    def unblock_user(self, user_id: int, public_id: str) -> None:
        with self._conn() as conn:
            other = conn.execute(
                "SELECT id FROM users WHERE public_id = ?",
                ((public_id or "").strip(),),
            ).fetchone()
            if not other:
                raise ValueError("User not found")
            conn.execute(
                "DELETE FROM blocks WHERE blocker_id = ? AND blocked_id = ?",
                (user_id, other["id"]),
            )

    def create_report(
        self,
        reporter_id: int,
        reason: str,
        target_public_id: str = None,
        post_id: int = None,
        comment_id: int = None,
    ) -> Dict:
        reason = " ".join((reason or "").split())
        if not reason:
            raise ValueError("Add a reason")
        if len(reason) > 500:
            raise ValueError("Reason is too long")
        with self._conn() as conn:
            target_id = None
            if target_public_id:
                target = conn.execute(
                    "SELECT id FROM users WHERE public_id = ?",
                    (str(target_public_id).strip(),),
                ).fetchone()
                if not target or target["id"] == reporter_id:
                    raise ValueError("User not found")
                target_id = target["id"]
            if post_id:
                post = conn.execute("SELECT id, user_id FROM posts WHERE id = ?", (int(post_id),)).fetchone()
                if not post:
                    raise ValueError("Post not found")
                target_id = target_id or post["user_id"]
            if comment_id:
                comment = conn.execute(
                    "SELECT id, user_id, post_id FROM comments WHERE id = ?",
                    (int(comment_id),),
                ).fetchone()
                if not comment:
                    raise ValueError("Comment not found")
                target_id = target_id or comment["user_id"]
                post_id = post_id or comment["post_id"]
            if not target_id and not post_id and not comment_id:
                raise ValueError("Choose a person or a post to report")
            now = datetime.utcnow().isoformat(timespec="seconds")
            cur = conn.execute(
                """
                INSERT INTO reports
                (reporter_id, target_user_id, post_id, comment_id, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (reporter_id, target_id, post_id, comment_id, reason, now),
            )
            report_id = cur.lastrowid
        return {"id": report_id, "reason": reason}

    def list_reports(self, limit: int = 100) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT r.*,
                       reporter.username AS reporter_username,
                       target.username AS target_username
                FROM reports r
                JOIN users reporter ON reporter.id = r.reporter_id
                LEFT JOIN users target ON target.id = r.target_user_id
                ORDER BY r.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "reporter": row["reporter_username"],
                "target": row["target_username"],
                "post_id": row["post_id"],
                "comment_id": row["comment_id"],
                "reason": row["reason"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def activity(self, user_id: int) -> Dict:
        with self._conn() as conn:
            hidden = self._hidden_user_ids(conn, user_id)
            incoming = conn.execute(
                """
                SELECT f.id AS friendship_id, f.created_at, f.requester_id,
                       u.username, u.display_name, u.public_id
                FROM friendships f
                JOIN users u ON u.id = f.requester_id
                WHERE f.addressee_id = ? AND f.status = 'pending'
                ORDER BY f.created_at DESC
                """,
                (user_id,),
            ).fetchall()
            comments = conn.execute(
                """
                SELECT c.id, c.post_id, c.body, c.created_at, c.user_id,
                       u.username, u.display_name
                FROM comments c
                JOIN posts p ON p.id = c.post_id
                JOIN users u ON u.id = c.user_id
                WHERE p.user_id = ? AND c.user_id != ?
                ORDER BY c.created_at DESC
                LIMIT 30
                """,
                (user_id, user_id),
            ).fetchall()
        return {
            "incoming": [
                {
                    "friendship_id": row["friendship_id"],
                    "public_id": row["public_id"],
                    "username": row["username"],
                    "display_name": row["display_name"] or row["username"],
                    "created_at": row["created_at"],
                }
                for row in incoming
                if row["requester_id"] not in hidden
            ],
            "comments": [
                {
                    "id": row["id"],
                    "post_id": row["post_id"],
                    "body": row["body"],
                    "username": row["username"],
                    "display_name": row["display_name"] or row["username"],
                    "created_at": row["created_at"],
                }
                for row in comments
                if row["user_id"] not in hidden
            ],
        }

    def user_id_from_public(self, public_id: str) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE public_id = ?",
                ((public_id or "").strip(),),
            ).fetchone()
        if not row:
            raise ValueError("User not found")
        return row["id"]

    def list_friends(self, user_id: int) -> Dict:
        with self._conn() as conn:
            accepted = conn.execute(
                """
                SELECT f.id AS friendship_id, u.* FROM users u
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
            blocked = conn.execute(
                """
                SELECT u.* FROM users u
                JOIN blocks b ON b.blocked_id = u.id
                WHERE b.blocker_id = ?
                ORDER BY u.username
                """,
                (user_id,),
            ).fetchall()
        return {
            "friends": [
                {**self._user_public(r), "friendship_id": r["friendship_id"], "relation": "friends"}
                for r in accepted
            ],
            "incoming": [
                {**self._user_public(r), "friendship_id": r["friendship_id"], "relation": "incoming"}
                for r in incoming
            ],
            "outgoing": [
                {**self._user_public(r), "friendship_id": r["friendship_id"], "relation": "outgoing"}
                for r in outgoing
            ],
            "blocked": [self._user_public(r) for r in blocked],
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
        return self.get_post(post_id, viewer_id=user_id)

    def public_profile(self, user_id: int, viewer_id: int = None) -> Dict:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                raise ValueError("User not found")
            if viewer_id and user_id in self._hidden_user_ids(conn, viewer_id):
                raise ValueError("User not found")
            friend_count = conn.execute(
                """
                SELECT COUNT(*) AS n FROM friendships
                WHERE status = 'accepted'
                  AND (requester_id = ? OR addressee_id = ?)
                """,
                (user_id, user_id),
            ).fetchone()["n"]
            visible = self._can_view_posts(conn, viewer_id or user_id, user_id)
        user = self._user_public(row)
        user["friend_count"] = int(friend_count or 0)
        return {
            "user": user,
            "posts": self.posts_for_user(user_id, viewer_id=viewer_id) if visible else [],
            "posts_visible": visible,
        }

    def posts_for_user(self, user_id: int, viewer_id: int = None) -> List[Dict]:
        viewer = viewer_id if viewer_id is not None else user_id
        with self._conn() as conn:
            if not self._can_view_posts(conn, viewer, user_id):
                return []
            rows = conn.execute(
                """
                SELECT p.*, u.username, u.display_name, u.avatar_path, u.public_id
                FROM posts p JOIN users u ON u.id = p.user_id
                WHERE p.user_id = ?
                ORDER BY p.created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [self._post_public(r, viewer) for r in rows]

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
        return self.get_post(post_id, viewer_id=user_id)

    def get_post(self, post_id: int, viewer_id: int = None) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT p.*, u.username, u.display_name, u.avatar_path, u.public_id
                FROM posts p JOIN users u ON u.id = p.user_id
                WHERE p.id = ?
                """,
                (post_id,),
            ).fetchone()
        return self._post_public(row, viewer_id) if row else None

    def toggle_like(self, user_id: int, post_id: int) -> Dict:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            self._require_visible_post(conn, user_id, post_id)
            existing = conn.execute(
                "SELECT 1 FROM likes WHERE user_id = ? AND post_id = ?",
                (user_id, post_id),
            ).fetchone()
            if existing:
                conn.execute(
                    "DELETE FROM likes WHERE user_id = ? AND post_id = ?",
                    (user_id, post_id),
                )
            else:
                conn.execute(
                    "INSERT INTO likes (user_id, post_id, created_at) VALUES (?, ?, ?)",
                    (user_id, post_id, now),
                )
        post = self.get_post(post_id, viewer_id=user_id)
        if not post:
            raise ValueError("Post not found")
        return post

    def rate_post(self, user_id: int, post_id: int, score: int) -> Dict:
        try:
            score = int(score)
        except (TypeError, ValueError) as e:
            raise ValueError("Rate from 1 to 10") from e
        if score < 1 or score > 10:
            raise ValueError("Rate from 1 to 10")
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            self._require_visible_post(conn, user_id, post_id)
            conn.execute(
                """
                INSERT INTO ratings (user_id, post_id, score, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, post_id) DO UPDATE SET
                    score = excluded.score,
                    created_at = excluded.created_at
                """,
                (user_id, post_id, score, now),
            )
        post = self.get_post(post_id, viewer_id=user_id)
        if not post:
            raise ValueError("Post not found")
        return post

    def add_comment(self, user_id: int, post_id: int, body: str) -> Dict:
        body = (body or "").strip()
        if not body:
            raise ValueError("Write a comment first")
        if len(body) > 400:
            raise ValueError("Comment is too long")
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            self._require_visible_post(conn, user_id, post_id)
            conn.execute(
                """
                INSERT INTO comments (user_id, post_id, body, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, post_id, body, now),
            )
        post = self.get_post(post_id, viewer_id=user_id)
        if not post:
            raise ValueError("Post not found")
        return post

    def delete_comment(self, user_id: int, post_id: int, comment_id: int) -> Dict:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT c.user_id AS author_id, p.user_id AS post_user_id
                FROM comments c
                JOIN posts p ON p.id = c.post_id
                WHERE c.id = ? AND c.post_id = ?
                """,
                (comment_id, post_id),
            ).fetchone()
            if not row:
                raise ValueError("Comment not found")
            if row["author_id"] != user_id and row["post_user_id"] != user_id:
                raise ValueError("You can only delete your own comments, or comments on your post")
            conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
        post = self.get_post(post_id, viewer_id=user_id)
        if not post:
            raise ValueError("Post not found")
        return post

    def feed_for_user(self, user_id: int, limit: int = 50) -> List[Dict]:
        """Posts from accepted friends, newest first. Your own posts stay on your profile."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT p.*, u.username, u.display_name, u.avatar_path, u.public_id
                FROM posts p
                JOIN users u ON u.id = p.user_id
                WHERE p.user_id IN (
                    SELECT CASE
                        WHEN requester_id = ? THEN addressee_id
                        ELSE requester_id
                    END
                    FROM friendships
                    WHERE status = 'accepted'
                      AND (requester_id = ? OR addressee_id = ?)
                )
                AND p.user_id NOT IN (
                    SELECT blocked_id FROM blocks WHERE blocker_id = ?
                    UNION
                    SELECT blocker_id FROM blocks WHERE blocked_id = ?
                )
                ORDER BY p.created_at DESC
                LIMIT ?
                """,
                (user_id, user_id, user_id, user_id, user_id, limit),
            ).fetchall()
        return [self._post_public(r, user_id) for r in rows]

    def _post_public(self, row, viewer_id: int = None) -> Dict:
        keys = row.keys()
        avatar_path = row["avatar_path"] if "avatar_path" in keys else None
        post_id = row["id"]
        with self._conn() as conn:
            like_count = conn.execute(
                "SELECT COUNT(*) AS n FROM likes WHERE post_id = ?",
                (post_id,),
            ).fetchone()["n"]
            liked = False
            my_rating = None
            if viewer_id:
                liked = conn.execute(
                    "SELECT 1 FROM likes WHERE post_id = ? AND user_id = ?",
                    (post_id, viewer_id),
                ).fetchone() is not None
                mine = conn.execute(
                    "SELECT score FROM ratings WHERE post_id = ? AND user_id = ?",
                    (post_id, viewer_id),
                ).fetchone()
                my_rating = int(mine["score"]) if mine else None
            rating = conn.execute(
                "SELECT AVG(score) AS average_rating, COUNT(*) AS n FROM ratings WHERE post_id = ?",
                (post_id,),
            ).fetchone()
            rating_count = int(rating["n"] or 0)
            comments = conn.execute(
                """
                SELECT * FROM (
                    SELECT c.id, c.user_id, c.body, c.created_at,
                           u.username, u.display_name, u.avatar_path, u.public_id
                    FROM comments c
                    JOIN users u ON u.id = c.user_id
                    WHERE c.post_id = ?
                    ORDER BY c.created_at DESC
                    LIMIT 30
                )
                ORDER BY created_at ASC
                """,
                (post_id,),
            ).fetchall()
            comment_count = conn.execute(
                "SELECT COUNT(*) AS n FROM comments WHERE post_id = ?",
                (post_id,),
            ).fetchone()["n"]
            hidden = self._hidden_user_ids(conn, viewer_id) if viewer_id else set()
        visible_comments = [c for c in comments if c["user_id"] not in hidden]
        return {
            "id": post_id,
            "user_id": row["user_id"],
            "public_id": row["public_id"] if "public_id" in keys else None,
            "username": row["username"],
            "display_name": row["display_name"] or row["username"],
            "avatar_url": f"/uploads/{os.path.basename(avatar_path)}" if avatar_path else None,
            "image_url": f"/uploads/{os.path.basename(row['image_path'])}",
            "caption": row["caption"] or "",
            "location_name": row["location_name"] or "",
            "sunset_date": row["sunset_date"] or "",
            "aesthetic_score": row["aesthetic_score"],
            "created_at": row["created_at"],
            "like_count": int(like_count or 0),
            "liked": liked,
            "rating_average": round(float(rating["average_rating"]), 1) if rating_count else None,
            "rating_count": rating_count,
            "my_rating": my_rating,
            "comment_count": len(visible_comments) if hidden else int(comment_count or 0),
            "comments": [self._comment_public(c) for c in visible_comments],
        }

    def _comment_public(self, row) -> Dict:
        avatar_path = row["avatar_path"] if "avatar_path" in row.keys() else None
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "public_id": row["public_id"] if "public_id" in row.keys() else None,
            "username": row["username"],
            "display_name": row["display_name"] or row["username"],
            "avatar_url": f"/uploads/{os.path.basename(avatar_path)}" if avatar_path else None,
            "body": row["body"],
            "created_at": row["created_at"],
        }
