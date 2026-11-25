"""SQLite persistence: users, faqs, documents, chunks, chat_history, feedback."""
import json
import sqlite3
from contextlib import contextmanager

from backend.config import Config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'student',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS faqs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'College FAQs',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Other Documents',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    pages INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'processing',
    error TEXT,
    extracted_text TEXT NOT NULL DEFAULT '',
    used_ocr INTEGER NOT NULL DEFAULT 0,
    uploaded_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER,
    faq_id INTEGER,
    source_name TEXT NOT NULL,
    page INTEGER,
    chunk_index INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_faq ON chunks(faq_id);
CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT NOT NULL,
    user_id INTEGER,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    message TEXT NOT NULL,
    sources TEXT NOT NULL DEFAULT '[]',
    document_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chat_owner ON chat_history(owner, conversation_id);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    owner TEXT,
    kind TEXT NOT NULL,            -- like | dislike | general
    comment TEXT NOT NULL DEFAULT '',
    contact TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@contextmanager
def get_conn():
    DATABASE_PATH ="campusai_schema_demo.db"
    conn = sqlite3.connect(str(Config.DATABASE_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _rows(cur):
    return [dict(r) for r in cur.fetchall()]


def init_db():
    Config.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as c:
        c.executescript(SCHEMA)


# ------------------------------------------------------------------ users
def create_user(name, email, password_hash, role="student"):
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?,?,?,?)",
            (name, email.lower(), password_hash, role),
        )
        return cur.lastrowid


def get_user_by_email(email):
    with get_conn() as c:
        r = c.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
        return dict(r) if r else None


def get_user(user_id):
    with get_conn() as c:
        r = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(r) if r else None


def update_user_password(user_id, password_hash):
    with get_conn() as c:
        c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))


# -------------------------------------------------------------- documents
def create_document(title, filename, stored_name, category, size_bytes, uploaded_by):
    with get_conn() as c:
        cur = c.execute(
            """INSERT INTO documents (title, filename, stored_name, category, size_bytes,
               status, uploaded_by) VALUES (?,?,?,?,?, 'processing', ?)""",
            (title, filename, stored_name, category, size_bytes, uploaded_by),
        )
        return cur.lastrowid


def get_document(doc_id, with_text=True):
    cols = "*" if with_text else (
        "id, title, filename, stored_name, category, size_bytes, pages, status, error,"
        " used_ocr, uploaded_by, created_at"
    )
    with get_conn() as c:
        r = c.execute(f"SELECT {cols} FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return dict(r) if r else None


def list_documents(category=None, query=None, limit=500):
    sql = ("SELECT id, title, filename, category, size_bytes, pages, status, error, used_ocr,"
           " created_at FROM documents WHERE 1=1")
    args = []
    if category:
        sql += " AND category = ?"
        args.append(category)
    if query:
        sql += " AND (title LIKE ? OR filename LIKE ? OR extracted_text LIKE ?)"
        like = f"%{query}%"
        args += [like, like, like]
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    args.append(limit)
    with get_conn() as c:
        return _rows(c.execute(sql, args))


def update_document(doc_id, **fields):
    allowed = {"title", "category", "status", "error", "pages", "extracted_text", "used_ocr"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    with get_conn() as c:
        c.execute(f"UPDATE documents SET {sets} WHERE id = ?", (*fields.values(), doc_id))


def delete_document(doc_id):
    with get_conn() as c:
        c.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
        c.execute("DELETE FROM documents WHERE id = ?", (doc_id,))


# ----------------------------------------------------------------- chunks
def replace_document_chunks(doc_id, source_name, chunks):
    """chunks: list of dicts {text, page, chunk_index}. Returns inserted rows."""
    with get_conn() as c:
        c.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
        for ch in chunks:
            c.execute(
                "INSERT INTO chunks (document_id, source_name, page, chunk_index, text)"
                " VALUES (?,?,?,?,?)",
                (doc_id, source_name, ch.get("page"), ch["chunk_index"], ch["text"]),
            )
        return _rows(c.execute("SELECT * FROM chunks WHERE document_id = ? ORDER BY id", (doc_id,)))


def replace_faq_chunks(faq_id, source_name, text):
    with get_conn() as c:
        c.execute("DELETE FROM chunks WHERE faq_id = ?", (faq_id,))
        c.execute(
            "INSERT INTO chunks (faq_id, source_name, page, chunk_index, text) VALUES (?,?,?,?,?)",
            (faq_id, source_name, None, 0, text),
        )
        return _rows(c.execute("SELECT * FROM chunks WHERE faq_id = ?", (faq_id,)))


def delete_faq_chunks(faq_id):
    with get_conn() as c:
        c.execute("DELETE FROM chunks WHERE faq_id = ?", (faq_id,))


def all_chunks():
    with get_conn() as c:
        return _rows(c.execute("SELECT * FROM chunks ORDER BY id"))


# -------------------------------------------------------------------- faqs
def create_faq(question, answer, category="College FAQs"):
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO faqs (question, answer, category) VALUES (?,?,?)",
            (question, answer, category),
        )
        return cur.lastrowid


def get_faq(faq_id):
    with get_conn() as c:
        r = c.execute("SELECT * FROM faqs WHERE id = ?", (faq_id,)).fetchone()
        return dict(r) if r else None


def list_faqs():
    with get_conn() as c:
        return _rows(c.execute("SELECT * FROM faqs ORDER BY category, id"))


def update_faq(faq_id, question, answer, category):
    with get_conn() as c:
        c.execute(
            "UPDATE faqs SET question=?, answer=?, category=?, updated_at=CURRENT_TIMESTAMP"
            " WHERE id=?",
            (question, answer, category, faq_id),
        )


def delete_faq(faq_id):
    with get_conn() as c:
        c.execute("DELETE FROM faqs WHERE id = ?", (faq_id,))
        c.execute("DELETE FROM chunks WHERE faq_id = ?", (faq_id,))


# ------------------------------------------------------------ chat history
def add_chat_message(owner, user_id, conversation_id, role, message, sources=None, document_id=None):
    with get_conn() as c:
        cur = c.execute(
            """INSERT INTO chat_history (owner, user_id, conversation_id, role, message, sources,
               document_id) VALUES (?,?,?,?,?,?,?)""",
            (owner, user_id, conversation_id, role, message, json.dumps(sources or []), document_id),
        )
        return cur.lastrowid


def _decode(row):
    row = dict(row)
    try:
        row["sources"] = json.loads(row.get("sources") or "[]")
    except ValueError:
        row["sources"] = []
    return row


def get_conversation_messages(owner, conversation_id, limit=None):
    sql = ("SELECT * FROM chat_history WHERE owner = ? AND conversation_id = ?"
           " ORDER BY id ASC")
    with get_conn() as c:
        rows = [_decode(r) for r in c.execute(sql, (owner, conversation_id)).fetchall()]
    return rows[-limit:] if limit else rows


def list_conversations(owner, limit=50):
    sql = """
    SELECT conversation_id,
           MIN(created_at) AS started_at,
           MAX(created_at) AS updated_at,
           COUNT(*) AS messages,
           (SELECT message FROM chat_history h2
              WHERE h2.owner = h.owner AND h2.conversation_id = h.conversation_id
                AND h2.role = 'user' ORDER BY h2.id ASC LIMIT 1) AS title
    FROM chat_history h WHERE owner = ?
    GROUP BY conversation_id ORDER BY MAX(id) DESC LIMIT ?
    """
    with get_conn() as c:
        return _rows(c.execute(sql, (owner, limit)))


def delete_conversation(owner, conversation_id):
    with get_conn() as c:
        c.execute("DELETE FROM chat_history WHERE owner = ? AND conversation_id = ?",
                  (owner, conversation_id))


def delete_all_conversations(owner):
    with get_conn() as c:
        c.execute("DELETE FROM chat_history WHERE owner = ?", (owner,))


def migrate_owner(old_owner, new_owner, user_id):
    with get_conn() as c:
        c.execute("UPDATE chat_history SET owner = ?, user_id = ? WHERE owner = ?",
                  (new_owner, user_id, old_owner))


def get_chat_message(chat_id):
    with get_conn() as c:
        r = c.execute("SELECT * FROM chat_history WHERE id = ?", (chat_id,)).fetchone()
        return _decode(r) if r else None


# ---------------------------------------------------------------- feedback
def add_feedback(kind, comment="", contact="", chat_id=None, owner=None):
    with get_conn() as c:
        # a like/dislike on the same message replaces the previous vote
        if chat_id and kind in ("like", "dislike"):
            c.execute("DELETE FROM feedback WHERE chat_id = ? AND owner = ? AND kind IN ('like','dislike')",
                      (chat_id, owner))
        cur = c.execute(
            "INSERT INTO feedback (chat_id, owner, kind, comment, contact) VALUES (?,?,?,?,?)",
            (chat_id, owner, kind, comment, contact),
        )
        return cur.lastrowid


def list_feedback(limit=200):
    sql = """SELECT f.*, h.message AS answer_excerpt FROM feedback f
             LEFT JOIN chat_history h ON h.id = f.chat_id
             ORDER BY f.id DESC LIMIT ?"""
    with get_conn() as c:
        rows = _rows(c.execute(sql, (limit,)))
    for r in rows:
        if r.get("answer_excerpt"):
            r["answer_excerpt"] = r["answer_excerpt"][:200]
    return rows


def delete_feedback(feedback_id):
    with get_conn() as c:
        c.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))


# ------------------------------------------------------------------- stats
def get_stats():
    with get_conn() as c:
        one = lambda q: c.execute(q).fetchone()[0]
        return {
            "documents": one("SELECT COUNT(*) FROM documents"),
            "documents_ready": one("SELECT COUNT(*) FROM documents WHERE status='ready'"),
            "faqs": one("SELECT COUNT(*) FROM faqs"),
            "conversations": one("SELECT COUNT(DISTINCT conversation_id) FROM chat_history"),
            "messages": one("SELECT COUNT(*) FROM chat_history"),
            "feedback": one("SELECT COUNT(*) FROM feedback"),
            "likes": one("SELECT COUNT(*) FROM feedback WHERE kind='like'"),
            "dislikes": one("SELECT COUNT(*) FROM feedback WHERE kind='dislike'"),
            "users": one("SELECT COUNT(*) FROM users"),
            "recent_uploads": _rows(c.execute(
                "SELECT id, title, category, status, size_bytes, created_at FROM documents"
                " ORDER BY id DESC LIMIT 5")),
        }
