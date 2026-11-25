"""Chat logic: retrieval -> grounded prompt -> LLM -> stored answer with sources."""
import logging
import uuid

import requests

from backend import database as db
from backend.config import Config

log = logging.getLogger("campusai.chatbot")

SYSTEM_PROMPT = """You are CampusAI, the official college assistant for students, parents and staff.

STRICT RULES
1. Answer ONLY from the CONTEXT excerpts provided in the user's message. They come from the
   college's uploaded documents and FAQs.
2. Never invent or guess college-specific facts (fees, dates, rules, names, phone numbers, eligibility).
3. If the context does not contain the answer, reply with exactly:
   "{not_found}"
4. Quote figures, dates and deadlines exactly as written in the context.
5. Format with Markdown: short paragraphs, bullet points or numbered lists, and **bold** for key
   values. Do not add a sources list; the app shows sources separately.
6. Write your answer in {language}. (The not-found sentence in rule 3 stays in English.)
"""


class LLMError(RuntimeError):
    pass


class LLMNotConfigured(LLMError):
    pass


def call_llm(system, messages):
    """Send a chat request to the configured provider and return the reply text."""
    if not Config.LLM_API_KEY:
        raise LLMNotConfigured("LLM_API_KEY is not set.")
    try:
        if Config.LLM_PROVIDER == "anthropic":
            resp = requests.post(
                (Config.LLM_BASE_URL or "https://api.anthropic.com").rstrip("/") + "/v1/messages",
                headers={"x-api-key": Config.LLM_API_KEY,
                         "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": Config.LLM_MODEL, "max_tokens": Config.LLM_MAX_TOKENS,
                      "temperature": 0.2, "system": system, "messages": messages},
                timeout=Config.LLM_TIMEOUT,
            )
            if resp.status_code >= 400:
                raise LLMError(_api_error(resp))
            blocks = resp.json().get("content", [])
            return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()

        # OpenAI-compatible chat completions
        base = (Config.LLM_BASE_URL or "https://api.openai.com/v1").rstrip("/")
        resp = requests.post(
            base + "/chat/completions",
            headers={"Authorization": f"Bearer {Config.LLM_API_KEY}",
                     "content-type": "application/json"},
            json={"model": Config.LLM_MODEL, "max_tokens": Config.LLM_MAX_TOKENS,
                  "temperature": 0.2,
                  "messages": [{"role": "system", "content": system}] + messages},
            timeout=Config.LLM_TIMEOUT,
        )
        if resp.status_code >= 400:
            raise LLMError(_api_error(resp))
        return resp.json()["choices"][0]["message"]["content"].strip()
    except requests.Timeout as exc:
        raise LLMError("The AI service took too long to respond. Please try again.") from exc
    except requests.RequestException as exc:
        raise LLMError(f"Could not reach the AI service: {exc}") from exc
    except (KeyError, IndexError, ValueError) as exc:
        raise LLMError("The AI service returned an unexpected response.") from exc


def _api_error(resp):
    try:
        body = resp.json()
        err = body.get("error", body)
        msg = err.get("message") if isinstance(err, dict) else str(err)
    except ValueError:
        msg = resp.text[:200]
    return f"AI service error ({resp.status_code}): {msg}"


def _build_sources(hits):
    """One entry per (document, page) with the best excerpt."""
    seen, sources = set(), []
    for h in hits:
        key = (h["document_id"], h["faq_id"], h["page"])
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "name": h["source"],
            "type": "faq" if h["faq_id"] else "document",
            "document_id": h["document_id"],
            "faq_id": h["faq_id"],
            "page": h["page"],
            "score": h["score"],
            "excerpt": h["text"][:240].replace("\n", " "),
        })
    return sources


class ChatService:
    def __init__(self, vector_store):
        self.store = vector_store

    # -- helpers
    def _history(self, owner, conversation_id):
        rows = db.get_conversation_messages(owner, conversation_id, limit=Config.HISTORY_TURNS)
        return [{"role": r["role"], "content": r["message"]} for r in rows]

    @staticmethod
    def _retrieval_query(message, history):
        """Short follow-ups ("and for MBA?") borrow context from the previous question."""
        if history and len(message.split()) < 6:
            prev = [h["content"] for h in history if h["role"] == "user"]
            if prev:
                return f"{prev[-1]} {message}"
        return message

    # -- main entry point
    def answer(self, owner, user_id, message, conversation_id=None, document_id=None,
               language="English"):
        message = message.strip()
        conversation_id = conversation_id or uuid.uuid4().hex
        history = self._history(owner, conversation_id)
        db.add_chat_message(owner, user_id, conversation_id, "user", message,
                            document_id=document_id)

        hits = self.store.search(self._retrieval_query(message, history),
                                 k=Config.TOP_K, document_id=document_id)
        sources = _build_sources(hits)
        error = None

        if not hits:
            text = Config.NOT_FOUND_MESSAGE
            sources = []
            try:
                from backend.features import record_unanswered
                record_unanswered(user_id, message)
            except Exception:
                log.exception("Could not record unanswered query")
        else:
            context = "\n\n".join(
                f"[{i}] Source: {h['source']}" + (f" (page {h['page']})" if h["page"] else "")
                + f"\n{h['text']}" for i, h in enumerate(hits, 1))
            prompt = (f"CONTEXT:\n{context}\n\n---\nQUESTION: {message}")
            try:
                text = call_llm(
                    SYSTEM_PROMPT.format(not_found=Config.NOT_FOUND_MESSAGE, language=language),
                    history + [{"role": "user", "content": prompt}])
                if Config.NOT_FOUND_MESSAGE in text and len(text) < len(Config.NOT_FOUND_MESSAGE) + 20:
                    sources = []
            except LLMNotConfigured:
                error = "llm_not_configured"
                text = ("The AI model is not configured yet, so I can't write an answer. "
                        "Ask the administrator to set `LLM_API_KEY` in the `.env` file.\n\n"
                        "Meanwhile, these are the most relevant passages I found:\n\n"
                        + "\n\n".join(f"> {s['excerpt']}…  \n> — *{s['name']}*" for s in sources[:3]))
            except LLMError as exc:
                log.error("LLM failure: %s", exc)
                error = "llm_error"
                text = f"Sorry, I couldn't generate an answer right now. {exc}"
                sources = []

        chat_id = db.add_chat_message(owner, user_id, conversation_id, "assistant", text,
                                      sources=sources, document_id=document_id)
        return {"answer": text, "sources": sources, "chat_id": chat_id,
                "conversation_id": conversation_id, "error": error}
