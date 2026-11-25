"""Flask application: serves the frontend and exposes the JSON API."""
import logging
import secrets
import re
import threading
import uuid
from functools import wraps

from flask import Flask, jsonify, request, send_file, send_from_directory, session
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash

from backend import database as db
from backend.chatbot import ChatService
from backend.config import Config
from backend.document_processor import InvalidPDF, process_document, save_pdf, title_from_filename
from backend.rag import VectorStore
from backend.features import register_feature_routes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("campusai.app")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LANGUAGES = {"English", "Hindi", "Marathi"}


def create_app():
    app = Flask(__name__, static_folder=str(Config.FRONTEND_DIR), static_url_path="")
    app.config.update(SECRET_KEY=Config.SECRET_KEY, MAX_CONTENT_LENGTH=Config.MAX_CONTENT_LENGTH,
                      SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True)

    db.init_db()
    _seed_admin()
    store = VectorStore()
    chat = ChatService(store)
    _index_faqs(store)

    # ------------------------------------------------------------ helpers
    def current_user():
        uid = session.get("user_id")
        return db.get_user(uid) if uid else None

    def owner_key():
        user = current_user()
        if user:
            return f"u{user['id']}", user["id"]
        if "sid" not in session:
            session["sid"] = uuid.uuid4().hex
        return f"s{session['sid']}", None

    def admin_required(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            user = current_user()
            if not user:
                return jsonify(error="Please log in as an administrator."), 401
            if user["role"] != "admin":
                return jsonify(error="Administrator access is required."), 403
            return fn(*a, **kw)
        return wrapper

    def public_user(u):
        return {"id": u["id"], "name": u["name"], "email": u["email"], "role": u["role"]}

    register_feature_routes(app, current_user=current_user, owner_key=owner_key, admin_required=admin_required, store=store)

    # -------------------------------------------------------------- pages
    @app.route("/")
    def page_home():
        return send_from_directory(app.static_folder, "index.html")

    @app.route("/chatbot")
    @app.route("/documents")
    @app.route("/admin")
    @app.route("/features")
    def page_clean_urls():
        return send_from_directory(app.static_folder, request.path.strip("/") + ".html")

    # --------------------------------------------------------------- auth
    @app.get("/api/me")
    def api_me():
        user = current_user()
        return jsonify(user=public_user(user) if user else None,
                       categories=Config.CATEGORIES,
                       llm_configured=bool(Config.LLM_API_KEY),
                       store=store.stats())

    @app.post("/api/auth/register")
    def api_register():
        d = request.get_json(silent=True) or {}
        name, email, pw = (d.get("name") or "").strip(), (d.get("email") or "").strip().lower(), d.get("password") or ""
        if not name or not EMAIL_RE.match(email):
            return jsonify(error="Enter your name and a valid email address."), 400
        if len(pw) < 6:
            return jsonify(error="Password must be at least 6 characters."), 400
        if db.get_user_by_email(email):
            return jsonify(error="An account with this email already exists."), 409
        uid = db.create_user(name, email, generate_password_hash(pw), "student")
        _login(uid)
        return jsonify(user=public_user(db.get_user(uid))), 201

    @app.post("/api/auth/login")
    def api_login():
        d = request.get_json(silent=True) or {}
        user = db.get_user_by_email((d.get("email") or "").strip())
        if not user or not check_password_hash(user["password_hash"], d.get("password") or ""):
            return jsonify(error="Incorrect email or password."), 401
        _login(user["id"])
        return jsonify(user=public_user(user))

    def _login(uid):
        guest_owner = f"s{session['sid']}" if "sid" in session else None
        session["user_id"] = uid
        if guest_owner:  # keep chats made before logging in
            db.migrate_owner(guest_owner, f"u{uid}", uid)

    @app.post("/api/auth/logout")
    def api_logout():
        session.clear()
        return jsonify(ok=True)

    # --------------------------------------------------------------- chat
    @app.post("/api/chat")
    def api_chat():
        d = request.get_json(silent=True) or {}
        message = (d.get("message") or "").strip()
        if not message:
            return jsonify(error="Please type a question."), 400
        if len(message) > 2000:
            return jsonify(error="Question is too long (max 2000 characters)."), 400
        document_id = d.get("document_id")
        if document_id is not None:
            doc = db.get_document(int(document_id), with_text=False) if str(document_id).isdigit() else None
            if not doc:
                return jsonify(error="The selected document no longer exists."), 404
            if doc["status"] != "ready":
                return jsonify(error="That document is still being processed. Try again shortly."), 409
            document_id = doc["id"]
        language = d.get("language") if d.get("language") in LANGUAGES else "English"
        owner, uid = owner_key()
        cid = d.get("conversation_id") or None
        if cid and not re.fullmatch(r"[0-9a-f]{32}", str(cid)):
            return jsonify(error="Invalid conversation."), 400
        result = chat.answer(owner, uid, message, cid, document_id, language)
        return jsonify(result)

    @app.get("/api/conversations")
    def api_conversations():
        owner, _ = owner_key()
        return jsonify(conversations=db.list_conversations(owner))

    @app.get("/api/conversations/<cid>")
    def api_conversation(cid):
        owner, _ = owner_key()
        return jsonify(messages=db.get_conversation_messages(owner, cid))

    @app.delete("/api/conversations/<cid>")
    def api_delete_conversation(cid):
        owner, _ = owner_key()
        db.delete_conversation(owner, cid)
        return jsonify(ok=True)

    @app.delete("/api/conversations")
    def api_clear_conversations():
        owner, _ = owner_key()
        db.delete_all_conversations(owner)
        return jsonify(ok=True)

    # ----------------------------------------------------------- feedback
    @app.post("/api/feedback")
    def api_feedback():
        d = request.get_json(silent=True) or {}
        kind = d.get("kind")
        if kind not in ("like", "dislike", "general"):
            return jsonify(error="Invalid feedback type."), 400
        comment = (d.get("comment") or "").strip()[:2000]
        if kind == "general" and not comment:
            return jsonify(error="Please write your feedback."), 400
        owner, _ = owner_key()
        chat_id = d.get("chat_id")
        if chat_id is not None:
            msg = db.get_chat_message(int(chat_id)) if str(chat_id).isdigit() else None
            if not msg or msg["owner"] != owner:
                return jsonify(error="Message not found."), 404
        fid = db.add_feedback(kind, comment, (d.get("contact") or "").strip()[:200],
                              int(chat_id) if chat_id is not None else None, owner)
        return jsonify(ok=True, id=fid)

    # ---------------------------------------------------------- documents
    @app.get("/api/documents")
    def api_documents():
        cat = request.args.get("category") or None
        if cat and cat not in Config.CATEGORIES:
            return jsonify(error="Unknown category."), 400
        return jsonify(documents=db.list_documents(cat, (request.args.get("q") or "").strip() or None))

    @app.get("/api/documents/<int:doc_id>")
    def api_document(doc_id):
        doc = db.get_document(doc_id)
        if not doc:
            return jsonify(error="Document not found."), 404
        doc.pop("stored_name", None)
        return jsonify(document=doc)

    @app.get("/api/documents/<int:doc_id>/file")
    def api_document_file(doc_id):
        doc = db.get_document(doc_id, with_text=False)
        path = Config.UPLOAD_DIR / doc["stored_name"] if doc else None
        if not doc or not path.exists():
            return jsonify(error="File not found."), 404
        return send_file(path, mimetype="application/pdf", as_attachment=False,
                         download_name=doc["filename"])

    @app.post("/api/documents")
    @admin_required
    def api_upload_documents():
        files = [f for f in request.files.getlist("files") if f and f.filename]
        if not files:
            return jsonify(error="Choose at least one PDF file."), 400
        category = request.form.get("category") or "Other Documents"
        if category not in Config.CATEGORIES:
            return jsonify(error="Unknown category."), 400
        user = current_user()
        created, errors = [], []
        for f in files:
            try:
                stored, size = save_pdf(f)
            except InvalidPDF as exc:
                errors.append(str(exc))
                continue
            doc_id = db.create_document(title_from_filename(f.filename), f.filename, stored,
                                        category, size, user["id"])
            threading.Thread(target=process_document, args=(doc_id, store), daemon=True).start()
            created.append(db.get_document(doc_id, with_text=False))
        status = 201 if created else 400
        return jsonify(documents=created, errors=errors,
                       error=errors[0] if errors and not created else None), status

    @app.patch("/api/documents/<int:doc_id>")
    @admin_required
    def api_update_document(doc_id):
        d = request.get_json(silent=True) or {}
        if not db.get_document(doc_id, with_text=False):
            return jsonify(error="Document not found."), 404
        fields = {}
        if (d.get("title") or "").strip():
            fields["title"] = d["title"].strip()[:200]
        if d.get("category") in Config.CATEGORIES:
            fields["category"] = d["category"]
        db.update_document(doc_id, **fields)
        if "title" in fields:  # source names in the index must follow the title
            threading.Thread(target=process_document, args=(doc_id, store), daemon=True).start()
        return jsonify(document=db.get_document(doc_id, with_text=False))

    @app.post("/api/documents/<int:doc_id>/reprocess")
    @admin_required
    def api_reprocess(doc_id):
        if not db.get_document(doc_id, with_text=False):
            return jsonify(error="Document not found."), 404
        threading.Thread(target=process_document, args=(doc_id, store), daemon=True).start()
        return jsonify(ok=True)

    @app.delete("/api/documents/<int:doc_id>")
    @admin_required
    def api_delete_document(doc_id):
        doc = db.get_document(doc_id, with_text=False)
        if not doc:
            return jsonify(error="Document not found."), 404
        store.remove(document_id=doc_id)
        db.delete_document(doc_id)
        try:
            (Config.UPLOAD_DIR / doc["stored_name"]).unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Could not delete file: %s", exc)
        return jsonify(ok=True)

    # --------------------------------------------------------------- FAQs
    @app.get("/api/faqs")
    def api_faqs():
        return jsonify(faqs=db.list_faqs())

    def _faq_payload():
        d = request.get_json(silent=True) or {}
        q, a = (d.get("question") or "").strip(), (d.get("answer") or "").strip()
        cat = d.get("category") if d.get("category") in Config.CATEGORIES else "College FAQs"
        return q, a, cat

    def _index_faq(faq):
        rows = db.replace_faq_chunks(faq["id"], "College FAQ",
                                     f"Question: {faq['question']}\nAnswer: {faq['answer']}")
        store.remove(faq_id=faq["id"])
        store.add(rows)

    @app.post("/api/faqs")
    @admin_required
    def api_create_faq():
        q, a, cat = _faq_payload()
        if not q or not a:
            return jsonify(error="Both question and answer are required."), 400
        faq = db.get_faq(db.create_faq(q, a, cat))
        _index_faq(faq)
        return jsonify(faq=faq), 201

    @app.put("/api/faqs/<int:faq_id>")
    @admin_required
    def api_update_faq(faq_id):
        q, a, cat = _faq_payload()
        if not db.get_faq(faq_id):
            return jsonify(error="FAQ not found."), 404
        if not q or not a:
            return jsonify(error="Both question and answer are required."), 400
        db.update_faq(faq_id, q, a, cat)
        faq = db.get_faq(faq_id)
        _index_faq(faq)
        return jsonify(faq=faq)

    @app.delete("/api/faqs/<int:faq_id>")
    @admin_required
    def api_delete_faq(faq_id):
        if not db.get_faq(faq_id):
            return jsonify(error="FAQ not found."), 404
        store.remove(faq_id=faq_id)
        db.delete_faq(faq_id)
        return jsonify(ok=True)

    # -------------------------------------------------------------- admin
    @app.get("/api/admin/stats")
    @admin_required
    def api_admin_stats():
        return jsonify(stats=db.get_stats(), store=store.stats(),
                       llm_configured=bool(Config.LLM_API_KEY))

    @app.get("/api/admin/feedback")
    @admin_required
    def api_admin_feedback():
        return jsonify(feedback=db.list_feedback())

    @app.delete("/api/admin/feedback/<int:fid>")
    @admin_required
    def api_admin_delete_feedback(fid):
        db.delete_feedback(fid)
        return jsonify(ok=True)

    @app.post("/api/admin/reindex")
    @admin_required
    def api_admin_reindex():
        store.reindex_all()
        return jsonify(ok=True, store=store.stats())

    # ------------------------------------------------------------- errors
    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_):
        return jsonify(error=f"Upload too large (limit {Config.MAX_CONTENT_LENGTH // 1048576} MB)."), 413

    @app.errorhandler(HTTPException)
    def http_error(e):
        if request.path.startswith("/api/"):
            return jsonify(error=e.description), e.code
        return e

    @app.errorhandler(Exception)
    def unhandled(e):
        log.exception("Unhandled error")
        return jsonify(error="Something went wrong on the server."), 500

    return app


def _seed_admin():
    if db.get_user_by_email(Config.ADMIN_EMAIL):
        return
    password = Config.ADMIN_PASSWORD
    if not password:
        password = secrets.token_urlsafe(18)
        log.warning("ADMIN_PASSWORD not set: generated a one-time admin password for %s: %s. Save it and set ADMIN_PASSWORD in .env.", Config.ADMIN_EMAIL, password)
    db.create_user(Config.ADMIN_NAME, Config.ADMIN_EMAIL, generate_password_hash(password), "admin")
    log.info("Created admin account %s", Config.ADMIN_EMAIL)


def _index_faqs(store):
    """Make sure every FAQ in the DB has a chunk in the index (e.g. after manual DB edits)."""
    changed = False
    have = {c["faq_id"] for c in db.all_chunks() if c["faq_id"]}
    for faq in db.list_faqs():
        if faq["id"] not in have:
            db.replace_faq_chunks(faq["id"], "College FAQ",
                                  f"Question: {faq['question']}\nAnswer: {faq['answer']}")
            changed = True
    if changed:
        store.reindex_all()
