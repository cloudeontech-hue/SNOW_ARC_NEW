import os
import json
import tempfile

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)

def load_json(filename: str) -> dict:
    ensure_data_dir()
    filepath = os.path.join(DATA_DIR, filename)
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_json(filename: str, data: dict):
    ensure_data_dir()
    filepath = os.path.join(DATA_DIR, filename)
    dir_name = os.path.dirname(filepath)
    
    # Atomic write using temp file and os.replace
    fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix=f".tmp_{filename}_")
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, filepath)
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise e
