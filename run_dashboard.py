import os
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from http.cookies import SimpleCookie
from datetime import datetime
import dotenv

# Load environment variables
dotenv.load_dotenv()

# Import backend modules
from backend.auth import get_session, login_user, logout_user, register_user
from backend.store import load_json, save_json
from backend.crypto import decrypt_value, encrypt_value
from backend.db import init_db, get_attachments, get_attachment_by_source_id, delete_attachment
from backend.s3_client import test_bucket_access, get_s3_client, presign
from backend.storage import test_local_path
from backend.sync_engine import run_retrieval
from backend.integrations.base import PLATFORM_CREDENTIAL_FIELDS, PLATFORM_SECRET_FIELDS, PLATFORM_SOURCES
from claude_client import ClaudeClient

# Set default SECRET_KEY fallback to allow initial runs, but issue a warning
if not os.environ.get("SECRET_KEY"):
    os.environ["SECRET_KEY"] = "default-antigravity-secret-key-change-me"
    print("WARNING: SECRET_KEY environment variable was not found. Using a default insecure key.")

# Map paths to local HTML files
STATIC_ROUTES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/servicenow": "servicenow.html",
    "/servicenow/": "servicenow.html",
    "/freshdesk": "freshdesk.html",
    "/freshdesk/": "freshdesk.html",
    "/servicenow/dashboard": "servicenow-dashboard.html",
    "/freshdesk/dashboard": "freshdesk-dashboard.html",
    "/servicenow/settings": "servicenow-settings.html",
    "/freshdesk/settings": "freshdesk-settings.html"
}

def get_session_from_cookie(headers, cookie_name: str):
    cookie_str = headers.get("Cookie", "")
    if not cookie_str:
        return None
    cookie = SimpleCookie(cookie_str)
    if cookie_name in cookie:
        token = cookie[cookie_name].value
        session = get_session(token)
        if session:
            return token, session
    return None

def normalize_and_validate_url(url_str: str, suffix: str) -> tuple[str | None, str | None]:
    url_str = url_str.strip()
    if not url_str:
        return None, "URL is required"
        
    if not url_str.startswith("http://") and not url_str.startswith("https://"):
        url_str = "https://" + url_str
        
    try:
        parsed = urllib.parse.urlparse(url_str)
        if parsed.scheme != "https":
            return None, "URL must use https scheme"
            
        hostname = parsed.hostname
        if not hostname:
            return None, "Invalid URL hostname"
            
        hostname = hostname.lower()
        if not hostname.endswith(suffix):
            return None, f"URL hostname must end with {suffix}"
            
        # Strip path, query, and fragment
        normalized = f"https://{hostname}"
        return normalized, None
    except Exception as e:
        return None, f"Invalid URL format: {str(e)}"

class DashboardHandler(BaseHTTPRequestHandler):
    def parse_query(self) -> dict:
        parsed_url = urllib.parse.urlparse(self.path)
        return urllib.parse.parse_qs(parsed_url.query)

    def get_query_param(self, name: str, default: str = "") -> str:
        q = self.parse_query()
        val = q.get(name)
        return val[0] if val else default

    def read_json_body(self) -> dict:
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                return {}
            body = self.rfile.read(content_length)
            return json.loads(body.decode('utf-8'))
        except Exception:
            return {}

    def send_json(self, data, status=200):
        try:
            content = json.dumps(data).encode('utf-8')
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"error": "Internal Server Error"}')

    def send_error_json(self, status, message):
        self.send_json({"error": message}, status=status)

    def serve_static(self, filepath, status=200):
        if not os.path.exists(filepath):
            self.send_error_json(404, f"File {filepath} not found")
            return
            
        content_type = "text/plain"
        if filepath.endswith(".html"):
            content_type = "text/html; charset=utf-8"
        elif filepath.endswith(".css"):
            content_type = "text/css"
        elif filepath.endswith(".js"):
            content_type = "application/javascript"
        elif filepath.endswith(".png"):
            content_type = "image/png"
        elif filepath.endswith(".jpg") or filepath.endswith(".jpeg"):
            content_type = "image/jpeg"
        elif filepath.endswith(".svg"):
            content_type = "image/svg+xml"
            
        try:
            with open(filepath, 'rb') as f:
                content = f.read()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error_json(500, f"Error reading file: {str(e)}")

    def redirect_to(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def check_api_auth(self, platform: str) -> dict | None:
        cookie_name = f"cloudeon_{platform}_session"
        res = get_session_from_cookie(self.headers, cookie_name)
        if not res:
            return None
        token, session = res
        if session and session["portal"] == platform:
            return session
        return None

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # 1. Page routes and redirects
        if path in STATIC_ROUTES:
            html_file = STATIC_ROUTES[path]
            
            # Auth isolation and redirection checks
            if path in ("/servicenow/dashboard", "/servicenow/settings"):
                res = get_session_from_cookie(self.headers, "cloudeon_servicenow_session")
                if not res or res[1]["portal"] != "servicenow":
                    self.redirect_to("/servicenow")
                    return
            elif path in ("/freshdesk/dashboard", "/freshdesk/settings"):
                res = get_session_from_cookie(self.headers, "cloudeon_freshdesk_session")
                if not res or res[1]["portal"] != "freshdesk":
                    self.redirect_to("/freshdesk")
                    return
            elif path in ("/servicenow", "/servicenow/"):
                res = get_session_from_cookie(self.headers, "cloudeon_servicenow_session")
                if res and res[1]["portal"] == "servicenow":
                    self.redirect_to("/servicenow/dashboard")
                    return
            elif path in ("/freshdesk", "/freshdesk/"):
                res = get_session_from_cookie(self.headers, "cloudeon_freshdesk_session")
                if res and res[1]["portal"] == "freshdesk":
                    self.redirect_to("/freshdesk/dashboard")
                    return

            self.serve_static(html_file)
            return

        # 2. API: Account me
        if path == "/api/account/me":
            portal = self.get_query_param("portal")
            if not portal:
                self.send_error_json(400, "portal parameter is required")
                return
            session = self.check_api_auth(portal)
            if not session:
                self.send_error_json(401, "Unauthorized")
                return
            self.send_json({
                "user_id": session["user_id"],
                "email": session["email"],
                "portal": session["portal"]
            })
            return

        # 3. API: Credentials GET
        elif path == "/api/credentials":
            platform = self.get_query_param("platform")
            if not platform or platform not in PLATFORM_CREDENTIAL_FIELDS:
                self.send_error_json(400, "Invalid platform")
                return
            session = self.check_api_auth(platform)
            if not session:
                self.send_error_json(401, "Unauthorized")
                return
            
            user_id = session["user_id"]
            creds = load_json("credentials.json")
            user_creds = creds.get(user_id, {}).get(platform, {})
            
            # Mask secret fields
            masked_creds = {}
            for field in PLATFORM_CREDENTIAL_FIELDS[platform]:
                val = user_creds.get(field, "")
                if field in PLATFORM_SECRET_FIELDS[platform]:
                    masked_creds[field] = "********" if val else ""
                else:
                    masked_creds[field] = val
                    
            self.send_json({"credentials": masked_creds})
            return

        # 4. API: Credentials Reveal
        elif path == "/api/credentials/reveal":
            platform = self.get_query_param("platform")
            if not platform or platform not in PLATFORM_CREDENTIAL_FIELDS:
                self.send_error_json(400, "Invalid platform")
                return
            session = self.check_api_auth(platform)
            if not session:
                self.send_error_json(401, "Unauthorized")
                return
                
            user_id = session["user_id"]
            creds = load_json("credentials.json")
            user_creds = creds.get(user_id, {}).get(platform, {})
            
            revealed = {}
            for field in PLATFORM_SECRET_FIELDS[platform]:
                val = user_creds.get(field, "")
                if val:
                    try:
                        revealed[field] = decrypt_value(val)
                    except Exception:
                        revealed[field] = ""
                else:
                    revealed[field] = ""
                    
            # Decrypt and append storage S3 secret key if it exists
            storage_config = creds.get(user_id, {}).get("storage", {})
            s3_secret = storage_config.get("s3", {}).get("aws_secret_access_key", "")
            if s3_secret:
                try:
                    revealed["aws_secret_access_key"] = decrypt_value(s3_secret)
                except Exception:
                    revealed["aws_secret_access_key"] = ""
            else:
                revealed["aws_secret_access_key"] = ""
                
            self.send_json({"secrets": revealed})
            return

        # 5. API: Storage GET
        elif path == "/api/storage":
            portal = self.get_query_param("portal")
            if not portal:
                self.send_error_json(400, "portal is required")
                return
            session = self.check_api_auth(portal)
            if not session:
                self.send_error_json(401, "Unauthorized")
                return
                
            user_id = session["user_id"]
            creds = load_json("credentials.json")
            storage_config = creds.get(user_id, {}).get("storage", {})
            
            # Mask S3 secret
            s3_config = storage_config.get("s3", {}).copy()
            if s3_config.get("aws_secret_access_key"):
                s3_config["aws_secret_access_key"] = "********"
                
            self.send_json({
                "mode": storage_config.get("mode", "local"),
                "s3": s3_config,
                "local": storage_config.get("local", {})
            })
            return

        # 6. API: Storage Browse Directories
        elif path == "/api/storage/browse":
            portal = self.get_query_param("portal")
            if not portal:
                self.send_error_json(400, "portal is required")
                return
            session = self.check_api_auth(portal)
            if not session:
                self.send_error_json(401, "Unauthorized")
                return
                
            path_param = self.get_query_param("path")
            if not path_param:
                path_param = os.getcwd()
                
            if not os.path.exists(path_param) or not os.path.isdir(path_param):
                self.send_error_json(400, "Directory does not exist")
                return
                
            try:
                directories = []
                for entry in os.scandir(path_param):
                    try:
                        if entry.is_dir() and not entry.name.startswith('.'):
                            directories.append(entry.name)
                    except Exception:
                        pass
                directories.sort()
                parent = os.path.dirname(os.path.abspath(path_param))
                if parent == os.path.abspath(path_param):
                    parent = None
                self.send_json({
                    "path": os.path.abspath(path_param),
                    "parent": parent,
                    "directories": directories
                })
            except Exception as e:
                self.send_error_json(500, f"Error listing directory: {str(e)}")
            return

        # 7. API: Get Attachments
        elif path == "/api/attachments":
            platform = self.get_query_param("platform")
            if not platform:
                self.send_error_json(400, "platform parameter is required")
                return
            session = self.check_api_auth(platform)
            if not session:
                self.send_error_json(401, "Unauthorized")
                return
                
            user_id = session["user_id"]
            rows = get_attachments(user_id, platform)
            
            # Load user S3 settings for presigning S3 files if needed
            creds = load_json("credentials.json")
            storage_config = creds.get(user_id, {}).get("storage", {})
            storage_mode = storage_config.get("mode", "local")
            
            s3_client = None
            bucket = None
            if storage_mode == "s3":
                try:
                    s3_config = storage_config.get("s3", {})
                    s3_client = get_s3_client(s3_config)
                    bucket = s3_config.get("bucket", "").strip() or os.environ.get("AWS_S3_BUCKET", "")
                except Exception as e:
                    print(f"Error instantiating S3 client for presigning: {e}")
            
            processed_attachments = []
            for row in rows:
                r = row.copy()
                download_url = None
                
                # Check actual stored mode in row
                row_mode = r.get("storage_mode")
                if row_mode == "s3" and r.get("storage_key"):
                    if s3_client and bucket:
                        try:
                            download_url = presign(s3_client, bucket, r["storage_key"])
                        except Exception as e:
                            print(f"Error presigning key {r['storage_key']}: {e}")
                elif row_mode == "local" and r.get("source_id"):
                    download_url = f"/api/attachments/file?source_id={r['source_id']}"
                    
                r["download_url"] = download_url
                processed_attachments.append(r)
                
            self.send_json({"attachments": processed_attachments})
            return

        # 8. API: Local File Download Proxy
        elif path == "/api/attachments/file":
            # Check either ServiceNow or Freshdesk cookies
            session = None
            for p in ["servicenow", "freshdesk"]:
                s = self.check_api_auth(p)
                if s:
                    session = s
                    break
            if not session:
                self.send_error_json(401, "Unauthorized")
                return
                
            source_id = self.get_query_param("source_id")
            if not source_id:
                self.send_error_json(400, "source_id is required")
                return
                
            user_id = session["user_id"]
            platform = session["portal"]
            
            row = get_attachment_by_source_id(user_id, platform, source_id)
            if not row:
                self.send_error_json(404, "Attachment record not found")
                return
                
            storage_key = row.get("storage_key")
            if not storage_key or not os.path.exists(storage_key):
                self.send_error_json(404, "File missing from disk")
                return
                
            safe_file_name = row.get("safe_file_name") or "attachment"
            content_type = row.get("content_type") or "application/octet-stream"
            
            try:
                file_size = os.path.getsize(storage_key)
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(file_size))
                self.send_header("Content-Disposition", f'attachment; filename="{safe_file_name}"')
                self.end_headers()
                
                with open(storage_key, 'rb') as f:
                    while True:
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            except Exception as e:
                print(f"Error streaming local file {storage_key}: {e}")
            return

        # Default static file route handler or 404
        # We also check if it matches static files in the directory directly (e.g. index.css if any, or assets)
        clean_path = path.lstrip("/")
        if clean_path and os.path.exists(clean_path) and os.path.isfile(clean_path):
            self.serve_static(clean_path)
            return

        self.send_error_json(404, "Route not found")

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        body = self.read_json_body()

        # 1. API: Account Register
        if path == "/api/account/register":
            email = body.get("email")
            password = body.get("password")
            portal = body.get("portal")
            
            if not email or not password or not portal:
                self.send_error_json(400, "email, password, and portal are required")
                return
                
            success, msg = register_user(email, password, portal)
            if success:
                self.send_json({"message": msg}, status=201)
            else:
                status = 409 if "already exists" in msg else 400
                self.send_error_json(status, msg)
            return

        # 2. API: Account Login
        elif path == "/api/account/login":
            email = body.get("email")
            password = body.get("password")
            portal = body.get("portal")
            
            if not email or not password or not portal:
                self.send_error_json(400, "email, password, and portal are required")
                return
                
            token, msg = login_user(email, password, portal)
            if token:
                cookie_name = f"cloudeon_{portal}_session"
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                # Cookie is HttpOnly and Path=/
                self.send_header("Set-Cookie", f"{cookie_name}={token}; Path=/; HttpOnly")
                self.end_headers()
                self.wfile.write(json.dumps({"message": msg}).encode('utf-8'))
            else:
                self.send_error_json(401, msg)
            return

        # 3. API: Account Logout
        elif path == "/api/account/logout":
            for portal in ["servicenow", "freshdesk"]:
                cookie_name = f"cloudeon_{portal}_session"
                res = get_session_from_cookie(self.headers, cookie_name)
                if res:
                    token, _ = res
                    logout_user(token)
                    
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie", "cloudeon_servicenow_session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT")
            self.send_header("Set-Cookie", "cloudeon_freshdesk_session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT")
            self.end_headers()
            self.wfile.write(json.dumps({"message": "Logout successful"}).encode('utf-8'))
            return

        # 4. API: Save Credentials
        elif path == "/api/credentials":
            platform = body.get("platform")
            if not platform or platform not in PLATFORM_CREDENTIAL_FIELDS:
                self.send_error_json(400, "Invalid platform")
                return
            session = self.check_api_auth(platform)
            if not session:
                self.send_error_json(401, "Unauthorized")
                return
                
            user_id = session["user_id"]
            creds = load_json("credentials.json")
            if user_id not in creds:
                creds[user_id] = {}
            if platform not in creds[user_id]:
                creds[user_id][platform] = {}
                
            stored_platform = creds[user_id][platform]
            
            # Normalize URLs
            url_field = "instance_url" if platform == "servicenow" else "domain_url"
            raw_url = body.get(url_field, "")
            suffix = ".service-now.com" if platform == "servicenow" else ".freshdesk.com"
            
            normalized_url, err = normalize_and_validate_url(raw_url, suffix)
            if err:
                self.send_error_json(400, err)
                return
                
            # Process credential fields
            for field in PLATFORM_CREDENTIAL_FIELDS[platform]:
                val = body.get(field, "")
                if field == url_field:
                    stored_platform[field] = normalized_url
                elif field in PLATFORM_SECRET_FIELDS[platform]:
                    if val == "********":
                        # Keep existing saved encrypted value
                        pass
                    elif val:
                        stored_platform[field] = encrypt_value(val)
                    else:
                        stored_platform[field] = ""
                else:
                    stored_platform[field] = val
                    
            creds[user_id][platform] = stored_platform
            save_json("credentials.json", creds)
            self.send_json({"message": "Credentials saved successfully"})
            return

        # 5. API: Test Connection
        elif path == "/api/credentials/test":
            platform = body.get("platform")
            if not platform or platform not in PLATFORM_CREDENTIAL_FIELDS:
                self.send_error_json(400, "Invalid platform")
                return
            session = self.check_api_auth(platform)
            if not session:
                self.send_error_json(401, "Unauthorized")
                return
                
            user_id = session["user_id"]
            creds = load_json("credentials.json")
            stored_platform = creds.get(user_id, {}).get(platform, {})
            
            # Compile credentials
            compiled = {}
            try:
                url_field = "instance_url" if platform == "servicenow" else "domain_url"
                raw_url = body.get(url_field, "")
                suffix = ".service-now.com" if platform == "servicenow" else ".freshdesk.com"
                normalized_url, err = normalize_and_validate_url(raw_url, suffix)
                if err:
                    self.send_json({"ok": False, "message": err})
                    return
                
                for field in PLATFORM_CREDENTIAL_FIELDS[platform]:
                    val = body.get(field, "")
                    if field == url_field:
                        compiled[field] = normalized_url
                    elif field in PLATFORM_SECRET_FIELDS[platform]:
                        if val == "********":
                            stored_secret = stored_platform.get(field, "")
                            if stored_secret:
                                compiled[field] = decrypt_value(stored_secret)
                            else:
                                compiled[field] = ""
                        else:
                            compiled[field] = val
                    else:
                        compiled[field] = val
            except Exception as e:
                self.send_json({"ok": False, "message": f"Error parsing input: {str(e)}"})
                return
                
            # Instantiate source and test
            try:
                source_class = PLATFORM_SOURCES[platform]
                source_inst = source_class(compiled)
                ok, message = source_inst.test_connection()
                self.send_json({"ok": ok, "message": message})
            except Exception as e:
                self.send_json({"ok": False, "message": f"Test failed: {str(e)}"})
            return

        # 6. API: Save Storage Destination Settings
        elif path == "/api/storage":
            portal = body.get("portal")
            if not portal:
                self.send_error_json(400, "portal parameter is required")
                return
            session = self.check_api_auth(portal)
            if not session:
                self.send_error_json(401, "Unauthorized")
                return
                
            user_id = session["user_id"]
            creds = load_json("credentials.json")
            if user_id not in creds:
                creds[user_id] = {}
                
            mode = body.get("mode", "local")
            s3_data = body.get("s3", {}).copy()
            local_data = body.get("local", {}).copy()
            
            stored_storage = creds[user_id].get("storage", {})
            stored_s3 = stored_storage.get("s3", {})
            
            # Handle S3 secret key
            s3_secret = s3_data.get("aws_secret_access_key", "")
            if s3_secret == "********":
                # Keep existing
                s3_data["aws_secret_access_key"] = stored_s3.get("aws_secret_access_key", "")
            elif s3_secret:
                s3_data["aws_secret_access_key"] = encrypt_value(s3_secret)
            else:
                s3_data["aws_secret_access_key"] = ""
                
            creds[user_id]["storage"] = {
                "mode": mode,
                "s3": s3_data,
                "local": local_data
            }
            save_json("credentials.json", creds)
            self.send_json({"message": "Storage settings saved successfully"})
            return

        # 7. API: Test Storage Destination
        elif path == "/api/storage/test":
            portal = body.get("portal")
            if not portal:
                self.send_error_json(400, "portal is required")
                return
            session = self.check_api_auth(portal)
            if not session:
                self.send_error_json(401, "Unauthorized")
                return
                
            user_id = session["user_id"]
            mode = body.get("mode", "local")
            
            if mode == "s3":
                s3_data = body.get("s3", {}).copy()
                if s3_data.get("aws_secret_access_key") == "********":
                    creds = load_json("credentials.json")
                    stored_secret = creds.get(user_id, {}).get("storage", {}).get("s3", {}).get("aws_secret_access_key", "")
                    s3_data["aws_secret_access_key"] = stored_secret
                ok, message = test_bucket_access(s3_data)
            else:
                local_path = body.get("local", {}).get("local_path", "")
                ok, message = test_local_path(local_path)
                
            self.send_json({"ok": ok, "message": message})
            return

        # 8. API: Run Retrieval (Sync)
        elif path == "/api/retrieve":
            platform = body.get("platform")
            if not platform:
                self.send_error_json(400, "platform parameter is required")
                return
            session = self.check_api_auth(platform)
            if not session:
                self.send_error_json(401, "Unauthorized")
                return
                
            user_id = session["user_id"]
            older_than_days = int(body.get("older_than_days", 0))
            
            creds = load_json("credentials.json")
            user_creds = creds.get(user_id, {})
            
            # Platform Connection details
            platform_creds = user_creds.get(platform, {})
            compiled_platform_creds = {}
            for field in PLATFORM_CREDENTIAL_FIELDS[platform]:
                val = platform_creds.get(field, "")
                if field in PLATFORM_SECRET_FIELDS[platform] and val:
                    try:
                        compiled_platform_creds[field] = decrypt_value(val)
                    except Exception:
                        compiled_platform_creds[field] = ""
                else:
                    compiled_platform_creds[field] = val
                    
            # Storage Details
            storage_config = user_creds.get("storage", {})
            storage_mode = storage_config.get("mode", "local")
            storage_creds = storage_config.get(storage_mode, {})
            
            try:
                total = run_retrieval(
                    user_id=user_id,
                    platform=platform,
                    older_than_days=older_than_days,
                    credentials=compiled_platform_creds,
                    storage_mode=storage_mode,
                    storage_credentials=storage_creds
                )
                self.send_json({
                    "ok": True,
                    "total": total,
                    "message": f"Successfully processed {total} records from {platform}."
                })
            except Exception as e:
                self.send_json({
                    "ok": False,
                    "total": 0,
                    "message": f"Retrieval failed: {str(e)}"
                })
            return

        # 9. API: Delete Attachment record
        elif path == "/api/attachments/delete":
            platform = body.get("platform")
            source_id = body.get("source_id") # None for placeholders is possible
            
            if not platform:
                self.send_error_json(400, "platform is required")
                return
            session = self.check_api_auth(platform)
            if not session:
                self.send_error_json(401, "Unauthorized")
                return
                
            user_id = session["user_id"]
            delete_attachment(user_id, platform, source_id)
            self.send_json({
                "ok": True,
                "message": "Attachment record removed from database."
            })
            return

        # 10. API: Claude Assistant Chat
        elif path == "/api/claude":
            platform = body.get("platform")
            if not platform:
                self.send_error_json(400, "platform parameter is required")
                return
            session = self.check_api_auth(platform)
            if not session:
                self.send_error_json(401, "Unauthorized")
                return
                
            messages = body.get("messages", [])
            context_str = body.get("context", "[]")
            
            claude = ClaudeClient()
            if not claude.is_configured():
                self.send_json({"reply": "Anthropic API key is not configured.", "configured": False})
                return
                
            vocab_word = "incident" if platform == "servicenow" else "ticket"
            system_prompt = (
                f"You are a helpful, professional assistant analyzing helpdesk attachments for {platform}. "
                f"Use '{vocab_word}' vocabulary. When referring to cases, use terms like '{vocab_word} id' or '{vocab_word} details'. "
                f"Below is the JSON context of the currently retrieved attachment records for this user. "
                f"You can answer questions about the file names, content types, associated {vocab_word} IDs, "
                f"creation dates, storage location, and count of files.\n\n"
                f"Records context:\n{context_str}"
            )
            
            reply = claude.generate_reply(messages, system_prompt)
            self.send_json({"reply": reply, "configured": True})
            return

        self.send_error_json(404, "Route not found")

def run(port=7002):
    init_db()
    server_address = ('', port)
    httpd = HTTPServer(server_address, DashboardHandler)
    print(f"Starting dashboard server on port {port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server...")
        httpd.server_close()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 7002))
    run(port=port)
