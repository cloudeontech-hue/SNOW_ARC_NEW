import re
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator

CONTENT_TYPE_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "application/pdf": "pdf",
    "application/zip": "zip",
    "application/json": "json",
    "application/xml": "xml",
    "text/plain": "txt",
    "text/html": "html",
    "text/csv": "csv",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
}

def sanitize_filename(name: str | None, content_type: str | None = None) -> str:
    if not name:
        name = "attachment"
    
    # Strip illegal chars: < > : " / \ | ? * and control chars
    name = re.sub(r'[\<\>\:\"\/\\\|\?\*\x00-\x1f]', '', name)
    
    # Collapse whitespace/underscores
    name = re.sub(r'[\s_]+', '_', name)
    name = name.strip('_')
    
    if not name:
        name = "attachment"
        
    # Check if name has an extension
    _, ext = os.path.splitext(name)
    if not ext and content_type:
        expected_ext = CONTENT_TYPE_EXTENSIONS.get(content_type.lower())
        if expected_ext:
            name = f"{name}.{expected_ext}"
            
    return name

@dataclass
class AttachmentRecord:
    record_type: str        # "incident" / "ticket"
    record_id: str          # "INC0000053" / "482"
    created_on: str         # ISO timestamp of the parent record
    file_name: str | None = None        # original filename, None if no attachment
    safe_file_name: str | None = None   # sanitized, filesystem-safe name
    content_type: str | None = None
    source_id: str | None = None        # platform's attachment unique ID; None for placeholder rows
    local_path: str | None = None       # temp file path during retrieval

class AttachmentSource(ABC):
    def __init__(self, credentials: dict):
        self.credentials = credentials

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        pass

    @abstractmethod
    def iter_attachments(self, older_than_days: int, tmp_dir: str) -> Iterator[AttachmentRecord]:
        pass

PLATFORM_CREDENTIAL_FIELDS = {
    "servicenow": ["instance_url", "username", "password"],
    "freshdesk":  ["domain_url", "api_key"],
}
PLATFORM_SECRET_FIELDS = {
    "servicenow": ["password"],
    "freshdesk":  ["api_key"],
}

PLATFORM_SOURCES: dict[str, type[AttachmentSource]] = {}

def register_sources():
    from backend.integrations.servicenow import ServiceNowSource
    from backend.integrations.freshdesk import FreshdeskSource
    PLATFORM_SOURCES["servicenow"] = ServiceNowSource
    PLATFORM_SOURCES["freshdesk"] = FreshdeskSource

# Register them at load time
register_sources()
