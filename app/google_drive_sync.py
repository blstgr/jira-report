#!/usr/bin/env python3
import base64
import hashlib
import http.server
import json
import os
import socket
import threading
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path


DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/drive/v3"
UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"
TOKEN_FILE = Path(__file__).resolve().parent / "google-drive-token.json"
def load_client_config(path):
    data = json.loads(Path(path).read_text())
    if "installed" in data:
        client = data["installed"]
        return client
    if "web" in data:
        client = data["web"]
        return client
    raise ValueError("Expected Google OAuth client secrets JSON with installed/web config")


def is_placeholder_client_config(path):
    try:
        data = json.loads(Path(path).read_text())
    except Exception:
        return False
    client = data.get("installed") or data.get("web") or {}
    client_id = client.get("client_id", "")
    client_secret = client.get("client_secret", "")
    return client_id.startswith("REPLACE_ME") or client_secret.startswith("REPLACE_ME") or not client_id or not client_secret


def resolve_folder_id(value):
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Missing Google Drive folder id or URL")
    if raw.startswith("https://drive.google.com/"):
        parsed = urllib.parse.urlparse(raw)
        parts = [part for part in parsed.path.split("/") if part]
        if "folders" in parts:
            folder_index = parts.index("folders")
            if folder_index + 1 < len(parts):
                return parts[folder_index + 1]
    if "folderview" in raw and "id=" in raw:
        parsed = urllib.parse.urlparse(raw)
        query = urllib.parse.parse_qs(parsed.query)
        folder_id = query.get("id", [""])[0]
        if folder_id:
            return folder_id
    return raw


def token_request(params):
    body = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            err = json.loads(body).get("error", "")
        except Exception:
            err = ""
        if err == "invalid_grant":
            raise RuntimeError("invalid_grant") from None
        raise


def ensure_token(client_path):
    if TOKEN_FILE.exists():
        token = json.loads(TOKEN_FILE.read_text())
        if "refresh_token" in token:
            try:
                refreshed = token_request({
                    "client_id": token["client_id"],
                    "client_secret": token["client_secret"],
                    "refresh_token": token["refresh_token"],
                    "grant_type": "refresh_token",
                })
                token["access_token"] = refreshed["access_token"]
                token["expires_in"] = refreshed.get("expires_in", 3600)
                TOKEN_FILE.write_text(json.dumps(token, indent=2))
                return token["access_token"]
            except RuntimeError as e:
                if "invalid_grant" in str(e):
                    print("Google Drive token expired — re-authenticating...")
                    TOKEN_FILE.unlink(missing_ok=True)
                else:
                    raise

    client = load_client_config(client_path)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    code_box = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            code_box["code"] = query.get("code", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h1>OAuth complete</h1><p>You can close this tab.</p>")

        def log_message(self, format, *args):
            return

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    redirect_uri = f"http://127.0.0.1:{port}/"
    auth_params = {
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": DRIVE_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    }
    webbrowser.open(f"{AUTH_URL}?{urllib.parse.urlencode(auth_params)}")
    thread.join(timeout=300)
    server.server_close()
    code = code_box.get("code")
    if not code:
        raise RuntimeError("Google OAuth did not return an authorization code")

    token = token_request({
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    })
    token["client_id"] = client["client_id"]
    token["client_secret"] = client["client_secret"]
    TOKEN_FILE.write_text(json.dumps(token, indent=2))
    return token["access_token"]


def authorize(client_secrets_path):
    return ensure_token(client_secrets_path)


def api_json(url, method="GET", headers=None, body=None):
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode()) if r.headers.get_content_type() == "application/json" else r.read()


def multipart_body(metadata, media_bytes, mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"):
    boundary = "====roadmap-boundary-%s====" % hashlib.md5(os.urandom(16)).hexdigest()
    parts = [
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(metadata)}\r\n",
        f"--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n".encode() + media_bytes + b"\r\n",
        f"--{boundary}--\r\n",
    ]
    body = b""
    for part in parts:
        body += part if isinstance(part, bytes) else part.encode()
    return body, boundary


def find_existing_file(access_token, folder_id, filename):
    q = urllib.parse.urlencode({
        "q": f"name='{filename}' and '{folder_id}' in parents and trashed=false",
        "fields": "files(id,name,parents,webViewLink)",
        "spaces": "drive",
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    })
    data = api_json(f"{API_BASE}/files?{q}", headers={"Authorization": f"Bearer {access_token}"})
    files = data.get("files", [])
    return files[0] if files else None


def upload_or_update(local_path, folder_id, filename, client_secrets_path):
    folder_id = resolve_folder_id(folder_id)
    access_token = ensure_token(client_secrets_path)
    existing = find_existing_file(access_token, folder_id, filename)
    media_bytes = Path(local_path).read_bytes()
    if existing:
        metadata = {"name": filename}
        body, boundary = multipart_body(metadata, media_bytes)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f'multipart/related; boundary="{boundary}"',
        }
        url = f"{UPLOAD_BASE}/files/{existing['id']}?uploadType=multipart&fields=id,name,webViewLink&supportsAllDrives=true"
        return api_json(url, method="PATCH", headers=headers, body=body)
    metadata = {"name": filename, "parents": [folder_id]}
    body, boundary = multipart_body(metadata, media_bytes)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": f'multipart/related; boundary="{boundary}"',
    }
    url = f"{UPLOAD_BASE}/files?uploadType=multipart&fields=id,name,webViewLink&supportsAllDrives=true"
    return api_json(url, method="POST", headers=headers, body=body)
