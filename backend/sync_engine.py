import os
import shutil
import tempfile
from datetime import datetime
from backend.integrations.base import PLATFORM_SOURCES
from backend.db import upsert_attachment
from backend.s3_client import get_s3_client, object_exists, upload_file
from backend.storage import save_local_file

def run_retrieval(user_id: str, platform: str, older_than_days: int, credentials: dict, storage_mode: str, storage_credentials: dict) -> int:
    if platform not in PLATFORM_SOURCES:
        raise ValueError(f"Unknown platform: {platform}")
        
    source_class = PLATFORM_SOURCES[platform]
    source = source_class(credentials)
    
    tmp_dir = tempfile.mkdtemp()
    total_count = 0
    
    try:
        s3_client = None
        bucket = None
        if storage_mode == "s3":
            s3_client = get_s3_client(storage_credentials)
            bucket = storage_credentials.get("bucket", "").strip() or os.environ.get("AWS_S3_BUCKET", "")
            
        for record in source.iter_attachments(older_than_days, tmp_dir):
            total_count += 1
            
            # ponytail: Skip placeholder rows since we only save records with attachments
            if record.source_id is None:
                continue
                
            storage_key = None
            skip_upload = False
            
            # Check S3 or Local existence before transferring
            if storage_mode == "s3":
                prefix = storage_credentials.get("prefix", "").strip("/")
                s3_key = f"{platform}/{record.record_type}/{record.record_id}/{record.safe_file_name}"
                if prefix:
                    s3_key = f"{prefix}/{s3_key}"
                storage_key = s3_key
                
                try:
                    if object_exists(s3_client, bucket, s3_key):
                        skip_upload = True
                except Exception as e:
                    print(f"S3 existence check failed for {s3_key}: {e}")
                    
            elif storage_mode == "local":
                local_path_base = storage_credentials.get("local_path", "").strip()
                if local_path_base:
                    dest_path = os.path.abspath(os.path.join(local_path_base, platform, record.record_type, record.record_id, record.safe_file_name))
                    storage_key = dest_path
                    if os.path.exists(dest_path):
                        skip_upload = True
                        
            # Execute upload if it does not already exist
            if not skip_upload and record.local_path and os.path.exists(record.local_path):
                if storage_mode == "s3":
                    upload_file(s3_client, bucket, storage_key, record.local_path)
                elif storage_mode == "local":
                    local_path_base = storage_credentials.get("local_path", "").strip()
                    if local_path_base:
                        storage_key = save_local_file(
                            local_path_base,
                            platform,
                            record.record_type,
                            record.record_id,
                            record.safe_file_name,
                            record.local_path
                        )
                        
            # Insert or replace in DB
            row = {
                "user_id": user_id,
                "platform": platform,
                "record_type": record.record_type,
                "record_id": record.record_id,
                "created_on": record.created_on,
                "file_name": record.file_name,
                "safe_file_name": record.safe_file_name,
                "content_type": record.content_type,
                "source_id": record.source_id,
                "storage_mode": storage_mode,
                "storage_key": storage_key,
                "retrieved_at": datetime.utcnow().isoformat()
            }
            upsert_attachment(row)
            
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        
    return total_count
