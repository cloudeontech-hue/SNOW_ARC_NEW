import os
import tempfile
from datetime import datetime, timedelta
from typing import Iterator
from backend.integrations.base import AttachmentSource, AttachmentRecord, sanitize_filename
from backend.integrations._http import build_retry_session

class ServiceNowSource(AttachmentSource):
    def test_connection(self) -> tuple[bool, str]:
        url = self.credentials.get("instance_url", "").strip("/")
        username = self.credentials.get("username", "")
        password = self.credentials.get("password", "")
        
        if not url or not username or not password:
            return False, "Missing credentials"
            
        test_url = f"{url}/api/now/table/incident?sysparm_limit=1"
        session = build_retry_session()
        try:
            response = session.get(test_url, auth=(username, password), timeout=15)
            if response.status_code == 200:
                content_type = response.headers.get("Content-Type", "")
                if "html" in content_type.lower() or "hibernating" in response.text:
                    return False, "Instance is hibernating or returned HTML instead of JSON"
                try:
                    response.json()
                    return True, "Connection successful"
                except ValueError:
                    return False, "Returned invalid JSON"
            elif response.status_code == 401:
                return False, "Invalid credentials (401 Unauthorized)"
            elif response.status_code == 403:
                return False, "Access forbidden (403 Forbidden)"
            else:
                return False, f"Server returned status code {response.status_code}"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"

    def iter_attachments(self, older_than_days: int, tmp_dir: str) -> Iterator[AttachmentRecord]:
        url = self.credentials.get("instance_url", "").strip("/")
        username = self.credentials.get("username", "")
        password = self.credentials.get("password", "")
        
        if not url or not username or not password:
            return
            
        session = build_retry_session()
        cutoff = datetime.utcnow() - timedelta(days=older_than_days)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        
        offset = 0
        limit = 100
        
        while True:
            incidents_url = f"{url}/api/now/table/incident"
            params = {
                "sysparm_query": f"sys_created_on<{cutoff_str}",
                "sysparm_limit": limit,
                "sysparm_offset": offset
            }
            
            response = session.get(incidents_url, auth=(username, password), params=params, timeout=30)
            response.raise_for_status()
            
            incidents = response.json().get("result", [])
            if not incidents:
                break
                
            for incident in incidents:
                sys_id = incident.get("sys_id")
                number = incident.get("number", "UNKNOWN")
                sys_created_on = incident.get("sys_created_on", "")
                
                try:
                    created_dt = datetime.strptime(sys_created_on, "%Y-%m-%d %H:%M:%S")
                    created_iso = created_dt.isoformat() + "Z"
                except Exception:
                    created_iso = sys_created_on
                
                # Fetch attachments for this incident
                attachment_meta_url = f"{url}/api/now/attachment"
                meta_params = {"sysparm_query": f"table_sys_id={sys_id}"}
                
                meta_response = session.get(attachment_meta_url, auth=(username, password), params=meta_params, timeout=30)
                meta_response.raise_for_status()
                
                attachments = meta_response.json().get("result", [])
                # ponytail: Only yield records that actually have attachments
                if attachments:
                    for att in attachments:
                        att_id = att.get("sys_id")
                        file_name = att.get("file_name")
                        content_type = att.get("content_type")
                        
                        safe_file_name = sanitize_filename(file_name, content_type)
                        
                        # Download the attachment binary
                        download_url = f"{url}/api/now/attachment/{att_id}/file"
                        
                        temp_file_fd, temp_file_path = tempfile.mkstemp(dir=tmp_dir, prefix="sn_att_")
                        try:
                            with os.fdopen(temp_file_fd, 'wb') as f:
                                with session.get(download_url, auth=(username, password), stream=True, timeout=60) as r:
                                    r.raise_for_status()
                                    for chunk in r.iter_content(chunk_size=8192):
                                        f.write(chunk)
                            
                            yield AttachmentRecord(
                                record_type="incident",
                                record_id=number,
                                created_on=created_iso,
                                file_name=file_name,
                                safe_file_name=safe_file_name,
                                content_type=content_type,
                                source_id=att_id,
                                local_path=temp_file_path
                            )
                        except Exception as e:
                            if os.path.exists(temp_file_path):
                                os.remove(temp_file_path)
                            print(f"Error downloading attachment {att_id}: {e}")
                            
            if len(incidents) < limit:
                break
            offset += limit
