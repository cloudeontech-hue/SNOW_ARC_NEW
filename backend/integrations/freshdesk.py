import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Iterator
from backend.integrations.base import AttachmentSource, AttachmentRecord, sanitize_filename
from backend.integrations._http import build_retry_session

class FreshdeskSource(AttachmentSource):
    def test_connection(self) -> tuple[bool, str]:
        url = self.credentials.get("domain_url", "").strip("/")
        api_key = self.credentials.get("api_key", "")
        
        if not url or not api_key:
            return False, "Missing credentials"
            
        test_url = f"{url}/api/v2/tickets?per_page=1"
        session = build_retry_session()
        try:
            response = session.get(test_url, auth=(api_key, "X"), timeout=15)
            if response.status_code == 200:
                try:
                    response.json()
                    return True, "Connection successful"
                except ValueError:
                    return False, "Returned invalid JSON"
            elif response.status_code == 401:
                return False, "Invalid API key (401 Unauthorized)"
            elif response.status_code == 403:
                return False, "Access forbidden (403 Forbidden)"
            else:
                return False, f"Server returned status code {response.status_code}"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"

    def iter_attachments(self, older_than_days: int, tmp_dir: str) -> Iterator[AttachmentRecord]:
        url = self.credentials.get("domain_url", "").strip("/")
        api_key = self.credentials.get("api_key", "")
        
        if not url or not api_key:
            return
            
        session = build_retry_session()
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        
        page = 1
        per_page = 30
        
        while True:
            tickets_url = f"{url}/api/v2/tickets"
            params = {
                "page": page,
                "per_page": per_page
            }
            
            response = session.get(tickets_url, auth=(api_key, "X"), params=params, timeout=30)
            response.raise_for_status()
            
            tickets = response.json()
            if not tickets:
                break
                
            for ticket in tickets:
                ticket_id = str(ticket.get("id"))
                created_at_str = ticket.get("created_at", "")
                
                try:
                    created_dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                except Exception:
                    created_dt = None
                    
                if created_dt and created_dt >= cutoff:
                    continue
                    
                attachments = ticket.get("attachments", [])
                # ponytail: Only yield records that actually have attachments
                if attachments:
                    for att in attachments:
                        att_id = str(att.get("id"))
                        file_name = att.get("name")
                        content_type = att.get("content_type")
                        download_url = att.get("attachment_url")
                        
                        if not download_url:
                            continue
                            
                        safe_file_name = sanitize_filename(file_name, content_type)
                        
                        temp_file_fd, temp_file_path = tempfile.mkstemp(dir=tmp_dir, prefix="fd_att_")
                        try:
                            with os.fdopen(temp_file_fd, 'wb') as f:
                                with session.get(download_url, auth=(api_key, "X"), stream=True, timeout=60) as r:
                                    r.raise_for_status()
                                    for chunk in r.iter_content(chunk_size=8192):
                                        f.write(chunk)
                                        
                            yield AttachmentRecord(
                                record_type="ticket",
                                record_id=ticket_id,
                                created_on=created_at_str,
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
                            
            if len(tickets) < per_page:
                break
            page += 1
