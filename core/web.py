"""HTTP layer: local-only protection, JSON API and the single page."""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from flask import Blueprint, Flask, current_app, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from . import documents, services
from .ai import GeminiClient, UnconfiguredAI
from .config import BASE_DIR, Settings
from .export import export_docx
from .jobs import JobRunner
from .services import ServiceError, Services
from .store import Store

log = logging.getLogger("documentor.web")
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
ROLES = {"textbook", "notes", "homework"}
MUTATING = {"POST", "PATCH", "PUT", "DELETE"}
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
       "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")

api = Blueprint("api", __name__, url_prefix="/api")


def _store() -> Store:
    return current_app.config["STORE"]


def _services() -> Services:
    return current_app.config["SERVICES"]


def _json_body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _submit(job_type: str, params: dict):
    settings: Settings = current_app.config["SETTINGS"]
    if _store().active_jobs() >= settings.max_queued_jobs:
        return jsonify(error="Too many tasks are waiting. Let some finish first."), 429
    job_id = current_app.config["RUNNER"].submit(job_type, params)
    return jsonify(job_id=job_id), 202


@api.get("/status")
def status():
    settings: Settings = current_app.config["SETTINGS"]
    store = _store()
    return jsonify(
        ai_configured=bool(settings.api_key) or not isinstance(_services().ai, UnconfiguredAI),
        model=getattr(_services().ai, "model", settings.model),
        max_upload_mb=settings.max_upload_mb,
        counts={"documents": len(store.list_documents()), "results": len(store.list_results()),
                "chats": len(store.list_chats())},
        question_types=services.QUESTION_TYPES,
        max_questions=services.MAX_QUESTIONS,
    )


# ---------- documents ----------
@api.get("/documents")
def list_documents():
    return jsonify(documents=_store().list_documents())


@api.post("/documents")
def upload_documents():
    files = request.files.getlist("files")
    if not files or all(not f.filename for f in files):
        return jsonify(error="Choose at least one file to upload."), 400
    forced_role = request.form.get("role")
    if forced_role and forced_role not in ROLES:
        return jsonify(error="Unknown document type."), 400
    uploaded, failed = [], []
    for file in files:
        name = PurePosixPath((file.filename or "").replace("\\", "/")).name[:120] or "document"
        try:
            data = file.read()
            extracted = documents.extract(name, data)
        except documents.DocumentError as exc:
            failed.append({"name": name, "error": str(exc)})
            continue
        role = forced_role or documents.guess_role(name)
        digest = hashlib.sha256(data).hexdigest()
        existing = _store().find_document(digest, role)
        document = existing or _store().add_document(name, role, extracted.kind, digest,
                                                     extracted.segments, extracted.pages)
        uploaded.append({k: document[k] for k in ("id", "name", "role", "kind", "chars", "pages", "created_at")}
                        | {"duplicate": bool(existing)})
    code = 200 if uploaded or not failed else 400
    return jsonify(uploaded=uploaded, failed=failed), code


@api.get("/documents/<doc_id>")
def get_document(doc_id: str):
    document = _store().get_document(doc_id)
    if not document:
        return jsonify(error="That document no longer exists."), 404
    preview = "\n\n".join(s["text"] for s in document["segments"])[:3000]
    return jsonify({k: document[k] for k in ("id", "name", "role", "kind", "chars", "pages", "created_at")}
                   | {"preview": preview, "sections": len(document["segments"])})


@api.patch("/documents/<doc_id>")
def update_document(doc_id: str):
    role = _json_body().get("role")
    if role not in ROLES:
        return jsonify(error="Unknown document type."), 400
    if not _store().update_document_role(doc_id, role):
        return jsonify(error="That document no longer exists."), 404
    return jsonify(ok=True)


@api.delete("/documents/<doc_id>")
def delete_document(doc_id: str):
    if not _store().delete_document(doc_id):
        return jsonify(error="That document no longer exists."), 404
    return jsonify(ok=True)


# ---------- jobs ----------
@api.post("/jobs/<job_type>")
def create_job(job_type: str):
    params = services.validate_job(job_type, _json_body())
    return _submit(job_type, params)


@api.get("/jobs/<job_id>")
def get_job(job_id: str):
    job = _store().get_job(job_id)
    if not job:
        return jsonify(error="That task no longer exists."), 404
    return jsonify(job)


# ---------- results ----------
@api.get("/results")
def list_results():
    return jsonify(results=_store().list_results())


def _load_result(result_id: str):
    return _store().get_result(result_id)


@api.get("/results/<result_id>")
def get_result(result_id: str):
    result = _load_result(result_id)
    if not result:
        return jsonify(error="That result no longer exists."), 404
    return jsonify(services.view(result))


@api.patch("/results/<result_id>")
def update_result(result_id: str):
    result = _load_result(result_id)
    if not result:
        return jsonify(error="That result no longer exists."), 404
    body = _json_body()
    title = None
    if "title" in body:
        title = str(body["title"] or "").strip()[:160]
        if not title:
            return jsonify(error="The title can't be empty."), 400
    if body.get("bulk"):
        services.bulk_decision(result, body["bulk"])
    if body.get("entry_id"):
        services.apply_decision(result, str(body["entry_id"]), body.get("decision"), body.get("text"),
                                bool(body.get("delete")))
    _store().save_result(result_id, result["data"], title)
    return jsonify(services.view(_load_result(result_id)))


@api.delete("/results/<result_id>")
def delete_result(result_id: str):
    if not _store().delete_result(result_id):
        return jsonify(error="That result no longer exists."), 404
    return jsonify(ok=True)


@api.get("/results/<result_id>/export")
def export_result(result_id: str):
    result = _load_result(result_id)
    if not result:
        return jsonify(error="That result no longer exists."), 404
    buffer = export_docx(result, request.args.get("answers") == "1", request.args.get("tags") == "1")
    name = secure_filename(result["title"])[:70] or "documentor"
    return send_file(buffer, as_attachment=True, download_name=f"{name}.docx",
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


# ---------- chats ----------
@api.get("/chats")
def list_chats():
    return jsonify(chats=_store().list_chats())


@api.post("/chats")
def create_chat():
    body = _json_body()
    ids = body.get("document_ids")
    if not isinstance(ids, list) or not ids or len(ids) > 8:
        return jsonify(error="Choose between 1 and 8 documents to chat about."), 400
    ids = [str(i) for i in ids]
    docs = [_store().get_document(i) for i in ids]
    if not all(docs):
        return jsonify(error="One of those documents no longer exists."), 400
    title = str(body.get("title") or "").strip()[:120] or ", ".join(d["name"] for d in docs)[:120]
    return jsonify(chat_id=_store().create_chat(title, ids)), 201


@api.get("/chats/<chat_id>")
def get_chat(chat_id: str):
    chat = _store().get_chat(chat_id)
    if not chat:
        return jsonify(error="This conversation no longer exists."), 404
    return jsonify(chat)


@api.post("/chats/<chat_id>/messages")
def post_message(chat_id: str):
    if not _store().get_chat(chat_id):
        return jsonify(error="This conversation no longer exists."), 404
    question = str(_json_body().get("question") or "").strip()
    if not question:
        return jsonify(error="Type a question first."), 400
    if len(question) > 4000:
        return jsonify(error="That question is too long. Keep it under 4,000 characters."), 400
    return _submit("chat", {"chat_id": chat_id, "question": question})


@api.delete("/chats/<chat_id>")
def delete_chat(chat_id: str):
    if not _store().delete_chat(chat_id):
        return jsonify(error="This conversation no longer exists."), 404
    return jsonify(ok=True)


# ---------- application ----------
def _hostname(value: str) -> str:
    return (urlsplit(f"//{value}").hostname or "").lower()


def create_app(settings: Settings | None = None, ai=None) -> Flask:
    settings = settings or Settings.from_env()
    app = Flask(__name__, root_path=str(BASE_DIR), template_folder="templates", static_folder="static")
    app.config["MAX_CONTENT_LENGTH"] = settings.max_upload_mb * 1024 * 1024
    app.config["SETTINGS"] = settings

    if ai is None:
        ai = (GeminiClient(settings.api_key, settings.model, settings.ai_timeout_s,
                           settings.ai_max_retries, settings.ai_rpm)
              if settings.api_key else UnconfiguredAI())
    store = Store(settings.data_dir)
    service = Services(store, ai)
    app.config["STORE"] = store
    app.config["SERVICES"] = service
    app.config["RUNNER"] = JobRunner(store, {
        "check_homework": service.check_homework,
        "generate_homework": service.generate_homework,
        "correct_notes": service.correct_notes,
        "answer_key": service.answer_key,
        "chat": service.chat,
    }, settings.job_workers)
    app.register_blueprint(api)

    @app.before_request
    def protect_local_app():
        # No login by design, so this app must not be reachable or drivable from elsewhere:
        # the Host check stops DNS rebinding, the Origin check stops other sites posting to it.
        host = _hostname(request.host)
        if not settings.allow_remote and host not in LOOPBACK:
            return jsonify(error="DocuMentor only accepts local connections."), 403
        if request.method in MUTATING:
            origin = request.headers.get("Origin")
            if origin and urlsplit(origin).netloc.lower() != request.host.lower():
                return jsonify(error="Cross-site requests aren't allowed."), 403
            if request.headers.get("Sec-Fetch-Site") == "cross-site":
                return jsonify(error="Cross-site requests aren't allowed."), 403
        return None

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.errorhandler(ServiceError)
    def service_error(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify(error=f"That upload is too large. The limit is {settings.max_upload_mb} MB."), 413

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith("/api/"):
            return jsonify(error=error.description), error.code
        return error

    @app.errorhandler(Exception)
    def unexpected(_error):
        log.exception("Unhandled error on %s", re.sub(r"[\r\n]", "", request.path))
        return jsonify(error="Something went wrong on our side. Please try again."), 500

    return app
