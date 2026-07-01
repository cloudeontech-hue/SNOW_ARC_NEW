import os
import shutil

def test_local_path(path: str) -> tuple[bool, str]:
    if not path:
        return False, "Path is required"
    try:
        os.makedirs(path, exist_ok=True)
        if os.access(path, os.W_OK):
            return True, "Path is writeable"
        return False, "Path is not writeable"
    except Exception as e:
        return False, f"Failed to access path: {str(e)}"

def save_local_file(base_path: str, platform: str, record_type: str, record_id: str, safe_file_name: str, src_path: str) -> str:
    dest_dir = os.path.join(base_path, platform, record_type, record_id)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, safe_file_name)
    shutil.copy2(src_path, dest_path)
    return os.path.abspath(dest_path)
