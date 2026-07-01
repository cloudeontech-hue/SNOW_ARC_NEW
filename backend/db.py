import os
import sqlite3
from datetime import datetime

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_PATH = os.path.join(DB_DIR, "attachments.db")

def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS attachments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         TEXT NOT NULL,
            platform        TEXT NOT NULL,
            record_type     TEXT NOT NULL,
            record_id       TEXT NOT NULL,
            created_on      TEXT,
            file_name       TEXT,               -- NULL for placeholder rows (no attachment)
            safe_file_name  TEXT,
            content_type    TEXT,
            source_id       TEXT,               -- NULL for placeholder rows
            storage_mode    TEXT,               -- "s3" | "local" | NULL for placeholders
            storage_key     TEXT,               -- S3 object key or absolute local path; NULL for placeholders
            retrieved_at    TEXT NOT NULL
        );
        """)
        cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_attachments_dedup
            ON attachments(user_id, platform, record_id, COALESCE(source_id, ''));
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_attachments_user_platform
            ON attachments(user_id, platform);
        """)
        conn.commit()
    finally:
        conn.close()

def upsert_attachment(row: dict):
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO attachments (
            user_id, platform, record_type, record_id, created_on,
            file_name, safe_file_name, content_type, source_id,
            storage_mode, storage_key, retrieved_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row["user_id"],
            row["platform"],
            row["record_type"],
            row["record_id"],
            row.get("created_on"),
            row.get("file_name"),
            row.get("safe_file_name"),
            row.get("content_type"),
            row.get("source_id"),
            row.get("storage_mode"),
            row.get("storage_key"),
            row.get("retrieved_at", datetime.utcnow().isoformat())
        ))
        conn.commit()
    finally:
        conn.close()

def get_attachments(user_id: str, platform: str) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT id, user_id, platform, record_type, record_id, created_on,
               file_name, safe_file_name, content_type, source_id,
               storage_mode, storage_key, retrieved_at
        FROM attachments
        WHERE user_id = ? AND platform = ?
        ORDER BY created_on DESC, id DESC
        """, (user_id, platform))
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_attachment_by_source_id(user_id: str, platform: str, source_id: str) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT id, user_id, platform, record_type, record_id, created_on,
               file_name, safe_file_name, content_type, source_id,
               storage_mode, storage_key, retrieved_at
        FROM attachments
        WHERE user_id = ? AND platform = ? AND source_id = ?
        """, (user_id, platform, source_id))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def delete_attachment(user_id: str, platform: str, source_id: str | None):
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        if source_id is None:
            cursor.execute("""
            DELETE FROM attachments
            WHERE user_id = ? AND platform = ? AND source_id IS NULL
            """, (user_id, platform))
        else:
            cursor.execute("""
            DELETE FROM attachments
            WHERE user_id = ? AND platform = ? AND source_id = ?
            """, (user_id, platform, source_id))
        conn.commit()
    finally:
        conn.close()
