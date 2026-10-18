"""Custom Map repository WSGI service. Run behind Nginx with gunicorn."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import functools
import hashlib
from http.cookies import SimpleCookie
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import time
from xml.etree import ElementTree
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from tools.custom_packages import inspect_package, resolve, MAP_LIMIT, MOD_LIMIT, ManifestError
from tools.custom_maps import semver_compare

LOG = logging.getLogger("custom-map")
STEAM_ENDPOINT = "https://steamcommunity.com/openid/login"
OPENID_NS = "http://specs.openid.net/auth/2.0"
COOKIE = "custom_map_session"


class HTTPError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class Repository:
    def __init__(self, data=None, public_url=None, *, storage_limit=None):
        self.data = Path(data or os.environ.get("CUSTOM_MAP_DATA", "repository/data"))
        self.public_url = (public_url or os.environ.get("CUSTOM_MAP_URL", "http://localhost:8091")).rstrip("/")
        parsed = urlparse(self.public_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path:
            raise ValueError("CUSTOM_MAP_URL must be an origin without a path")
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("public deployments require HTTPS")
        self.secure = parsed.scheme == "https"
        self.storage_limit = int(storage_limit or os.environ.get("CUSTOM_MAP_STORAGE_BYTES", 40_000_000_000))
        self.archive_budget = max(0, self.storage_limit - min(2_000_000_000, self.storage_limit // 10))
        self.owner_limit = int(os.environ.get("CUSTOM_MAP_OWNER_BYTES", 2 * 1024 ** 3))
        self.admins = set(filter(None, os.environ.get("CUSTOM_MAP_ADMIN_STEAM_IDS", "").split(",")))
        for directory in (self.data, self.data / "blobs", self.data / "uploads"):
            directory.mkdir(parents=True, exist_ok=True)
        self.database = self.data / "repository.sqlite3"
        with self.db() as db:
            db.executescript('''
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, created INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS user_profiles (user_id TEXT PRIMARY KEY REFERENCES users(id), name TEXT NOT NULL, avatar_url TEXT NOT NULL, expires INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS sessions (hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf TEXT NOT NULL, expires INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS tokens (hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, label TEXT NOT NULL, created INTEGER NOT NULL, expires INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS auth_states (hash TEXT PRIMARY KEY, expires INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS nonces (nonce TEXT PRIMARY KEY, created INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS packages (id TEXT PRIMARY KEY, kind TEXT NOT NULL, owner TEXT NOT NULL, created INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS releases (id TEXT NOT NULL REFERENCES packages(id), version TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL, unpacked INTEGER NOT NULL, manifest TEXT NOT NULL, created INTEGER NOT NULL, PRIMARY KEY(id, version));
              CREATE TABLE IF NOT EXISTS reservations (id TEXT PRIMARY KEY, owner TEXT NOT NULL, size INTEGER NOT NULL, expires INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS comments (id INTEGER PRIMARY KEY, package TEXT NOT NULL REFERENCES packages(id), author TEXT NOT NULL, body TEXT NOT NULL, created INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS issues (id INTEGER PRIMARY KEY, package TEXT NOT NULL REFERENCES packages(id), author TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, version TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS rate_limits (key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires INTEGER NOT NULL);
              CREATE INDEX IF NOT EXISTS comments_package ON comments(package, id);
              CREATE INDEX IF NOT EXISTS issues_package ON issues(package, id);
            ''')
        self.steam_check = self._steam_check
        self.steam_profile = self._steam_profile

    @staticmethod
    def _steam_profile(identifier):
        if not re.fullmatch(r"7656119[0-9]{10}", identifier):
            raise ValueError("Invalid SteamID64")
        request = Request("https://steamcommunity.com/profiles/" + identifier + "/?xml=1", headers={"User-Agent": "CustomMap/1.0", "Accept": "application/xml"})
        with urlopen(request, timeout=4) as response:
            raw = response.read(128 * 1024 + 1)
        if len(raw) > 128 * 1024 or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise ValueError("Invalid Steam profile response")
        root = ElementTree.fromstring(raw)
        if root.findtext("steamID64") != identifier:
            raise ValueError("Steam profile identity mismatch")
        return {"name": root.findtext("steamID"), "avatar_url": root.findtext("avatarMedium") or root.findtext("avatarFull") or ""}

    @staticmethod
    def profile_view(identifier, name=None, avatar_url=None):
        return {"id": identifier, "name": name or "Steam · " + identifier, "avatar_url": avatar_url or None,
                "profile_url": "https://steamcommunity.com/profiles/" + identifier}

    def refresh_profile(self, identifier, *, force=False):
        now = int(time.time())
        with self.db() as db:
            row = db.execute("SELECT * FROM user_profiles WHERE user_id=?", (identifier,)).fetchone()
        if row and row["expires"] > now and not force:
            return self.profile_view(identifier, row["name"], row["avatar_url"])
        name, avatar = (row["name"], row["avatar_url"]) if row else ("Steam · " + identifier, "")
        expires = now + 600
        try:
            profile = self.steam_profile(identifier)
            candidate = profile.get("name")
            if not isinstance(candidate, str) or not candidate.strip() or len(candidate) > 128:
                raise ValueError("Invalid Steam name")
            candidate_avatar = profile.get("avatar_url") or ""
            url = urlparse(candidate_avatar)
            if candidate_avatar and (len(candidate_avatar) > 512 or url.scheme != "https" or url.hostname not in {"avatars.steamstatic.com", "avatars.fastly.steamstatic.com", "avatars.akamai.steamstatic.com", "cdn.akamai.steamstatic.com"} or url.username or url.password or url.port not in {None, 443}):
                raise ValueError("Invalid Steam avatar URL")
            name, avatar, expires = candidate.strip(), candidate_avatar, now + 86400
        except Exception:
            LOG.warning("Steam profile unavailable for %s", identifier)
        with self.db() as db:
            db.execute("INSERT INTO user_profiles VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET name=excluded.name,avatar_url=excluded.avatar_url,expires=excluded.expires", (identifier, name, avatar, expires))
        return self.profile_view(identifier, name, avatar)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def fail(self, condition, status, message):
        if condition:
            raise HTTPError(status, message)

    def json_body(self, env):
        length = self.length(env, 32 * 1024)
        try:
            result = json.loads(env["wsgi.input"].read(length))
            self.fail(not isinstance(result, dict), 400, "Expected a JSON object")
            return result
        except (ValueError, UnicodeError):
            raise HTTPError(400, "Invalid JSON")

    def length(self, env, maximum):
        try:
            length = int(env.get("CONTENT_LENGTH", ""))
        except ValueError:
            raise HTTPError(411, "Content-Length is required")
        self.fail(length <= 0, 400, "Empty body")
        self.fail(length > maximum, 413, "Upload exceeds size limit")
        return length

    def text(self, value, label, limit):
        self.fail(not isinstance(value, str) or not value.strip() or len(value) > limit, 400, f"Invalid {label} (maximum {limit} characters)")
        return value.strip()

    def rate(self, key, maximum, period):
        now = int(time.time())
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM rate_limits WHERE expires < ?", (now,))
            row = db.execute("SELECT count FROM rate_limits WHERE key=?", (key,)).fetchone()
            self.fail(row and row["count"] >= maximum, 429, "Rate limit reached; try again later")
            db.execute("INSERT INTO rate_limits VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1", (key, now + period))

    def current_user(self, env, *, required=False):
        auth = env.get("HTTP_AUTHORIZATION", "")
        now = int(time.time())
        session = None
        with self.db() as db:
            if auth.startswith("Bearer "):
                row = db.execute("SELECT user_id FROM tokens WHERE hash=? AND expires>?", (self.hash(auth[7:]), now)).fetchone()
                if row:
                    return {"id": row["user_id"], "csrf": None, "token": True}
            else:
                cookies = SimpleCookie()
                try:
                    cookies.load(env.get("HTTP_COOKIE", ""))
                    session = cookies[COOKIE].value if COOKIE in cookies else None
                except Exception:
                    pass
                if session:
                    row = db.execute("SELECT user_id,csrf FROM sessions WHERE hash=? AND expires>?", (self.hash(session), now)).fetchone()
                    if row:
                        return {"id": row["user_id"], "csrf": row["csrf"], "session_hash": self.hash(session), "token": False}
        self.fail(required, 401, "Steam login required")
        return None

    def writer(self, env):
        user = self.current_user(env, required=True)
        if not user["token"]:
            self.fail(env.get("HTTP_ORIGIN") != self.public_url, 403, "Invalid request origin")
            self.fail(not secrets.compare_digest(env.get("HTTP_X_CSRF_TOKEN", ""), user["csrf"]), 403, "Invalid CSRF token")
        return user

    @staticmethod
    def hash(value):
        return hashlib.sha256(value.encode()).hexdigest()

    def cookie(self, name, value, age):
        return ("Set-Cookie", f"{name}={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={age}" + ("; Secure" if self.secure else ""))

    def _steam_check(self, params):
        payload = {key: value for key, value in params.items() if key.startswith("openid.")}
        payload["openid.mode"] = "check_authentication"
        request = Request(STEAM_ENDPOINT, urlencode(payload).encode(), {"Content-Type": "application/x-www-form-urlencoded"})
        with urlopen(request, timeout=15) as response:
            values = dict(line.split(":", 1) for line in response.read(8192).decode().splitlines() if ":" in line)
        return values.get("is_valid") == "true"

    def login(self, env):
        address = env.get("REMOTE_ADDR", "unknown")
        if address in {"127.0.0.1", "::1"}:
            address = env.get("HTTP_X_REAL_IP", address)
        self.rate("login:" + address, 30, 3600)
        state = secrets.token_urlsafe(32)
        now = int(time.time())
        with self.db() as db:
            db.execute("DELETE FROM auth_states WHERE expires<?", (now,))
            db.execute("DELETE FROM sessions WHERE expires<?", (now,))
            db.execute("DELETE FROM tokens WHERE expires<?", (now,))
            db.execute("DELETE FROM nonces WHERE created<?", (now - 900,))
            db.execute("INSERT INTO auth_states VALUES (?,?)", (self.hash(state), now + 600))
        return_to = self.public_url + "/auth/steam/callback?state=" + state
        query = urlencode({"openid.ns": OPENID_NS, "openid.mode": "checkid_setup", "openid.return_to": return_to, "openid.realm": self.public_url + "/", "openid.identity": OPENID_NS + "/identifier_select", "openid.claimed_id": OPENID_NS + "/identifier_select"})
        return 302, [("Location", STEAM_ENDPOINT + "?" + query), self.cookie("custom_map_login", state, 600)], b""

    def callback(self, env, query):
        state = query.get("state", "")
        cookies = SimpleCookie()
        cookies.load(env.get("HTTP_COOKIE", ""))
        browser_state = cookies.get("custom_map_login")
        self.fail(not browser_state or not state or not secrets.compare_digest(state, browser_state.value), 400, "Invalid login state")
        now = int(time.time())
        with self.db() as db:
            deleted = db.execute("DELETE FROM auth_states WHERE hash=? AND expires>?", (self.hash(state), now)).rowcount
        self.fail(not deleted, 400, "Login has expired or already been used")
        expected_return = self.public_url + "/auth/steam/callback?state=" + state
        self.fail(query.get("openid.ns") != OPENID_NS or query.get("openid.mode") != "id_res" or query.get("openid.op_endpoint") != STEAM_ENDPOINT or query.get("openid.return_to") != expected_return, 400, "Invalid Steam assertion")
        claimed = query.get("openid.claimed_id", "")
        match = re.fullmatch(r"https://steamcommunity\.com/openid/id/(7656119[0-9]{10})", claimed)
        self.fail(not match or query.get("openid.identity") != claimed, 400, "Invalid Steam identity")
        signed = set(query.get("openid.signed", "").split(","))
        self.fail(not {"op_endpoint", "claimed_id", "identity", "return_to", "response_nonce", "assoc_handle"} <= signed, 400, "Incomplete Steam signature")
        nonce = query.get("openid.response_nonce", "")
        try:
            stamp = datetime.strptime(nonce[:20], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            raise HTTPError(400, "Invalid Steam nonce")
        self.fail(len(nonce) > 255 or abs(now - stamp) > 300, 400, "Expired Steam assertion")
        self.fail(not self.steam_check(query), 401, "Steam rejected the login assertion")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        user_id = match[1]
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("INSERT INTO nonces VALUES (?,?)", (nonce, now))
            except sqlite3.IntegrityError:
                raise HTTPError(400, "Steam assertion already used")
            db.execute("INSERT OR IGNORE INTO users VALUES (?,?)", (user_id, now))
            db.execute("INSERT INTO sessions VALUES (?,?,?,?)", (self.hash(token), user_id, csrf, now + 604800))
        self.refresh_profile(user_id)
        return 302, [("Location", self.public_url + "/"), self.cookie(COOKIE, token, 604800), self.cookie("custom_map_login", "", 0)], b""

    def release(self, row, package):
        manifest = json.loads(row["manifest"])
        return {"id": package["id"], "kind": package["kind"], "owner": package["owner"], "version": row["version"], "sha256": row["sha256"], "size": row["size"], "unpacked_size": row["unpacked"], "manifest": manifest, "created": row["created"], "download_url": self.public_url + f'/api/v1/downloads/{package["id"]}/{row["version"]}'}

    def releases(self):
        with self.db() as db:
            rows = db.execute("SELECT releases.*,packages.kind,packages.owner FROM releases JOIN packages USING(id)").fetchall()
        return [self.release(row, row) for row in rows]

    def registry(self):
        latest = {}
        for release in self.releases():
            previous = latest.get(release["id"])
            if previous is None or semver_compare(release["version"], previous["version"]) > 0:
                latest[release["id"]] = release
        return {"format": "skieo-registry", "version": 1, "packages": sorted(latest.values(), key=lambda item: item["id"]), "limits": {"map_bytes": MAP_LIMIT, "mod_bytes": MOD_LIMIT, "unpacked_bytes": 1024 ** 3, "storage_bytes": self.storage_limit, "owner_bytes": self.owner_limit}}

    def package(self, identifier):
        with self.db() as db:
            row = db.execute("SELECT * FROM packages WHERE id=?", (identifier,)).fetchone()
        self.fail(not row, 404, "Package not found")
        return dict(row)

    def publish(self, env, kind, *, owner=None):
        self.fail(kind not in {"map", "mod"}, 400, "kind must be map or mod")
        user = {"id": owner} if owner else self.writer(env)
        self.rate("publish:" + user["id"], 20, 86400)
        length = self.length(env, MAP_LIMIT if kind == "map" else MOD_LIMIT)
        reservation = secrets.token_hex(24)
        staged = self.data / "uploads" / reservation
        now = int(time.time())
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            # Stale uploads are never removed while another worker owns them.
            # Gunicorn timeout is 180s, below this 30 minute expiry.
            stale = db.execute("SELECT id FROM reservations WHERE expires<?", (now,)).fetchall()
            for item in stale:
                (self.data / "uploads" / item["id"]).unlink(missing_ok=True)
            db.execute("DELETE FROM reservations WHERE expires<?", (now,))
            used = db.execute("SELECT coalesce(sum(size),0) FROM releases").fetchone()[0]
            reserved = db.execute("SELECT coalesce(sum(size),0) FROM reservations").fetchone()[0]
            owner_used = db.execute("SELECT coalesce(sum(size),0) FROM releases JOIN packages USING(id) WHERE owner=?", (user["id"],)).fetchone()[0]
            owner_reserved = db.execute("SELECT coalesce(sum(size),0) FROM reservations WHERE owner=?", (user["id"],)).fetchone()[0]
            self.fail(used + reserved + length > self.archive_budget, 507, "Repository storage quota reached")
            self.fail(owner_used + owner_reserved + length > self.owner_limit, 413, "Publisher storage quota reached")
            free = os.statvfs(self.data).f_bavail * os.statvfs(self.data).f_frsize
            self.fail(free < reserved + length + 128 * 1024 ** 2, 507, "Insufficient storage")
            db.execute("INSERT INTO reservations VALUES (?,?,?,?)", (reservation, user["id"], length, now + 1800))
        try:
            digest = hashlib.sha256()
            remaining = length
            started = time.monotonic()
            with staged.open("xb") as output:
                while remaining:
                    chunk = env["wsgi.input"].read(min(remaining, 1024 * 1024))
                    self.fail(time.monotonic() - started > 180, 408, "Upload time limit exceeded")
                    self.fail(not chunk, 400, "Truncated upload")
                    output.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
                output.flush()
                os.fsync(output.fileno())
            _, manifest, unpacked = inspect_package(staged, kind)
            self.fail(len(self.encode(manifest)) > 65536, 413, "Repository manifests must not exceed 64 KiB")
            metadata = manifest["metadata"]
            self.text(metadata["name"], "package name", 120)
            self.text(metadata["description"], "description", 12000)
            identifier, version, sha = manifest["id"], metadata["version"], digest.hexdigest()
            self.fail(len(identifier) > 120 or len(version) > 80, 400, "Identifier or version is too long")
            self.fail(staged.stat().st_size != length, 400, "Invalid upload size")
            with self.db() as db:
                db.execute("BEGIN IMMEDIATE")
                package = db.execute("SELECT * FROM packages WHERE id=?", (identifier,)).fetchone()
                self.fail(package and (package["owner"] != user["id"] or package["kind"] != kind), 403, "This package belongs to another publisher or kind")
                self.fail(db.execute("SELECT 1 FROM releases WHERE id=? AND version=?", (identifier, version)).fetchone(), 409, "Published versions are immutable; increment the version")
                self.fail(not package and db.execute("SELECT count(*) FROM packages").fetchone()[0] >= 1024, 507, "Package count limit reached")
                self.fail(db.execute("SELECT count(*) FROM releases WHERE id=?", (identifier,)).fetchone()[0] >= 100, 413, "Package release count limit reached")
                candidates = [self.release(row, row) for row in db.execute("SELECT releases.*,packages.kind,packages.owner FROM releases JOIN packages USING(id)")]
                resolve([*candidates, {"id": identifier, "kind": kind, "version": version, "manifest": manifest}], identifier, "=" + version)
                db.execute("INSERT OR IGNORE INTO packages VALUES (?,?,?,?)", (identifier, kind, user["id"], now))
                db.execute("INSERT INTO releases VALUES (?,?,?,?,?,?,?)", (identifier, version, sha, length, unpacked, json.dumps(manifest, ensure_ascii=False), now))
                blob = self.data / "blobs" / (sha + ".zip")
                os.replace(staged, blob)
                db.execute("DELETE FROM reservations WHERE id=?", (reservation,))
            return {"id": identifier, "version": version, "sha256": sha, "url": self.public_url + "/packages/" + identifier}
        finally:
            staged.unlink(missing_ok=True)
            with self.db() as db:
                db.execute("DELETE FROM reservations WHERE id=?", (reservation,))

    def dispatch(self, env):
        method, path = env.get("REQUEST_METHOD", "GET"), env.get("PATH_INFO", "/")
        parsed_query = parse_qs(env.get("QUERY_STRING", ""), keep_blank_values=True, max_num_fields=50)
        self.fail(any(len(values) != 1 for values in parsed_query.values()), 400, "Duplicate query parameter")
        query = {key: values[0] for key, values in parsed_query.items()}
        if method == "GET" and path == "/auth/steam":
            return self.login(env)
        if method == "GET" and path == "/auth/steam/callback":
            return self.callback(env, query)
        if path == "/api/v1/me" and method == "GET":
            user = self.current_user(env)
            return {"user": {**self.refresh_profile(user["id"]), "admin": user["id"] in self.admins, "csrf": user["csrf"]} if user else None}
        if path == "/api/v1/logout" and method == "POST":
            user = self.writer(env)
            self.fail(user["token"], 400, "Use the token revocation endpoint")
            with self.db() as db:
                db.execute("DELETE FROM sessions WHERE hash=?", (user["session_hash"],))
            return 200, [self.cookie(COOKIE, "", 0)], b'{}'
        if path == "/api/v1/tokens":
            user = self.writer(env) if method != "GET" else self.current_user(env, required=True)
            self.fail(user["token"], 403, "Use a Steam browser session to manage tokens")
            if method == "POST":
                self.rate("token:" + user["id"], 6, 86400)
                label = self.text(self.json_body(env).get("label"), "token label", 80)
                token = secrets.token_urlsafe(40)
                now = int(time.time())
                with self.db() as db:
                    db.execute("INSERT INTO tokens VALUES (?,?,?,?,?)", (self.hash(token), user["id"], label, now, now + 30 * 86400))
                return {"token": token, "expires": now + 30 * 86400}
            if method == "GET":
                with self.db() as db:
                    return {"tokens": [dict(row) for row in db.execute("SELECT hash AS id,label,created,expires FROM tokens WHERE user_id=? AND expires>?", (user["id"], int(time.time())))]}
        match = re.fullmatch(r"/api/v1/tokens/([0-9a-f]{64})", path)
        if match and method == "DELETE":
            user = self.writer(env)
            self.fail(user["token"], 403, "Use a Steam browser session")
            with self.db() as db:
                db.execute("DELETE FROM tokens WHERE hash=? AND user_id=?", (match[1], user["id"]))
            return {}
        if path == "/api/v1/health" and method == "GET":
            with self.db() as db:
                db.execute("SELECT 1").fetchone()
            return {"status": "ok"}
        if path == "/api/v1/registry" and method == "GET":
            registry = self.registry()
            offset = max(0, int(query.get("offset", 0)))
            packages = registry["packages"]
            registry["packages"] = packages[offset:offset + 128]
            registry["next_offset"] = offset + 128 if offset + 128 < len(packages) else None
            return registry
        if path == "/api/v1/packages":
            if method == "POST":
                return 201, [("Content-Type", "application/json; charset=utf-8")], self.encode(self.publish(env, query.get("kind")))
            if method == "GET":
                packages = self.registry()["packages"]
                kind, search = query.get("kind"), query.get("q", "").casefold()[:120]
                packages = [item for item in packages if (not kind or item["kind"] == kind) and (not search or search in (item["id"] + " " + item["manifest"]["metadata"]["name"] + " " + item["manifest"]["metadata"]["description"]).casefold())]
                offset = max(0, int(query.get("offset", 0)))
                return {"packages": packages[offset:offset + 48], "total": len(packages)}
        if path == "/api/v1/resolve" and method == "GET":
            root_id = query.get("id", "")
            self.package(root_id)
            return {"packages": resolve(self.releases(), root_id, query.get("version", "*"))}
        match = re.fullmatch(r"/api/v1/downloads/([a-z0-9._-]+)/([0-9A-Za-z.+-]+)", path)
        if match and method in {"GET", "HEAD"}:
            package = self.package(match[1])
            with self.db() as db:
                release = db.execute("SELECT * FROM releases WHERE id=? AND version=?", match.groups()).fetchone()
            self.fail(not release, 404, "Version not found")
            file = self.data / "blobs" / (release["sha256"] + ".zip")
            self.fail(not file.is_file(), 503, "Package storage unavailable")
            headers = [("Content-Type", "application/zip"), ("Content-Length", str(release["size"])), ("ETag", '"' + release["sha256"] + '"'), ("Cache-Control", "public, max-age=31536000, immutable"), ("Content-Disposition", f'attachment; filename="{match[1]}-{match[2]}.skieo{package["kind"]}"')]
            return 200, headers, [] if method == "HEAD" else self.stream(file)
        match = re.fullmatch(r"/api/v1/packages/([a-z0-9._-]+)(?:/(comments|issues)(?:/([0-9]+))?)?", path)
        if match:
            identifier, section, item_id = match.groups()
            package = self.package(identifier)
            if not section and method == "GET":
                releases = [item for item in self.releases() if item["id"] == identifier]
                releases.sort(key=functools.cmp_to_key(lambda a, b: semver_compare(a["version"], b["version"])), reverse=True)
                return {**package, "releases": releases}
            if section and not item_id and method == "GET":
                before = int(query.get("before", 2 ** 63 - 1))
                with self.db() as db:
                    rows = db.execute(f"SELECT m.*,p.name AS author_name,p.avatar_url AS author_avatar FROM {section} m LEFT JOIN user_profiles p ON p.user_id=m.author WHERE package=? AND m.id<? ORDER BY m.id DESC LIMIT 51", (identifier, before)).fetchall()
                messages = []
                for row in rows[:50]:
                    message = dict(row)
                    message["author_profile"] = self.profile_view(row["author"], message.pop("author_name"), message.pop("author_avatar"))
                    messages.append(message)
                return {section: messages, "next_before": rows[49]["id"] if len(rows) > 50 else None}
            if section and not item_id and method == "POST":
                user = self.writer(env)
                self.rate(section + ":" + user["id"], 30 if section == "comments" else 10, 86400)
                body = self.json_body(env)
                text = self.text(body.get("body"), "message", 4000 if section == "comments" else 8000)
                now = int(time.time())
                with self.db() as db:
                    if section == "comments":
                        cursor = db.execute("INSERT INTO comments(package,author,body,created) VALUES (?,?,?,?)", (identifier, user["id"], text, now))
                    else:
                        title = self.text(body.get("title"), "issue title", 160)
                        version = self.text(body.get("version"), "affected version", 80)
                        self.fail(not db.execute("SELECT 1 FROM releases WHERE id=? AND version=?", (identifier, version)).fetchone(), 400, "Unknown affected version")
                        cursor = db.execute("INSERT INTO issues(package,author,title,body,version,created) VALUES (?,?,?,?,?,?)", (identifier, user["id"], title, text, version, now))
                    return {"id": cursor.lastrowid}
            if section and item_id and method in {"DELETE", "PATCH"}:
                user = self.writer(env)
                with self.db() as db:
                    row = db.execute(f"SELECT * FROM {section} WHERE id=? AND package=?", (item_id, identifier)).fetchone()
                    self.fail(not row, 404, "Message not found")
                    self.fail(user["id"] not in {row["author"], package["owner"], *self.admins}, 403, "Only the author, publisher or moderator may update this message")
                    if method == "DELETE":
                        db.execute(f"DELETE FROM {section} WHERE id=?", (item_id,))
                    elif section == "issues":
                        self.fail(user["id"] not in {package["owner"], *self.admins}, 403, "Only the publisher or moderator may change issue status")
                        status = self.json_body(env).get("status")
                        self.fail(status not in {"open", "closed"}, 400, "Invalid issue status")
                        db.execute("UPDATE issues SET status=? WHERE id=?", (status, item_id))
                    else:
                        raise HTTPError(405, "Method not allowed")
                    return {}
        raise HTTPError(404, "Endpoint not found")

    @staticmethod
    def encode(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def stream(path):
        with path.open("rb") as file:
            while chunk := file.read(1024 * 1024):
                yield chunk

    def __call__(self, env, start_response):
        try:
            result = self.dispatch(env)
            if isinstance(result, tuple):
                status, headers, body = result
                body = [body] if isinstance(body, bytes) else body
            else:
                status, headers, body = 200, [("Content-Type", "application/json; charset=utf-8")], [self.encode(result)]
        except HTTPError as error:
            status, headers, body = error.status, [], [self.encode({"error": error.message})]
        except (ManifestError, ValueError) as error:
            status, headers, body = 400, [], [self.encode({"error": str(error)})]
        except Exception:
            LOG.exception("Repository request failed")
            status, headers, body = 500, [], [b'{"error":"Internal server error"}']
        if not any(key.lower() == "content-type" for key, _ in headers):
            headers.append(("Content-Type", "application/json; charset=utf-8"))
        headers.extend([("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "same-origin")])
        if not any(key.lower() == "cache-control" for key, _ in headers):
            headers.append(("Cache-Control", "no-store"))
        from http import HTTPStatus
        start_response(f"{status} {HTTPStatus(status).phrase}", headers)
        return body


def create_app():
    return Repository()


if __name__ == "__main__":
    from wsgiref.simple_server import make_server
    logging.basicConfig(level=logging.INFO)
    with make_server("127.0.0.1", 8091, create_app()) as server:
        print("Custom Map repository: http://localhost:8091/api/v1/registry")
        server.serve_forever()
