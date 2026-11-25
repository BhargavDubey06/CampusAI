"""Application configuration. All secrets come from environment variables / .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default):
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        return float(value)
    except ValueError:
        return default


class Config:
    # ---- Flask ----
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = _int("PORT", 5000)
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    MAX_CONTENT_LENGTH = _int("MAX_UPLOAD_MB", 50) * 1024 * 1024

    # ---- Paths ----
    BASE_DIR = BASE_DIR
    FRONTEND_DIR = BASE_DIR / "frontend"
    UPLOAD_DIR = BASE_DIR / "uploads"
    VECTOR_DIR = BASE_DIR / "vector_store"
    DATABASE_PATH = Path(os.getenv("DATABASE_PATH", BASE_DIR / "campusai.db"))

    # ---- Admin account (seeded on first start) ----
    ADMIN_NAME = os.getenv("ADMIN_NAME", "Administrator")
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@campusai.local").lower()
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

    # ---- LLM ----
    # LLM_PROVIDER: "anthropic" or "openai" (any OpenAI-compatible endpoint:
    # OpenAI, Groq, OpenRouter, Together, a local Ollama/LM Studio server, ...)
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5-5")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")  # only for provider "openai"
    LLM_MAX_TOKENS = _int("LLM_MAX_TOKENS", 1024)
    LLM_TIMEOUT = _int("LLM_TIMEOUT", 60)

    # ---- Embeddings / RAG ----
    EMBEDDING_MODEL = os.getenv(
        "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
    )
    CHUNK_SIZE = _int("CHUNK_SIZE", 900)        # characters
    CHUNK_OVERLAP = _int("CHUNK_OVERLAP", 150)  # characters
    TOP_K = _int("TOP_K", 5)
    # None -> use the embedder's own sensible default
    MIN_SCORE = _float("MIN_SCORE", None)
    HISTORY_TURNS = _int("HISTORY_TURNS", 6)    # past messages sent to the LLM

    # ---- OCR (scanned PDFs) ----
    OCR_ENABLED = os.getenv("OCR_ENABLED", "1") == "1"
    OCR_MIN_CHARS_PER_PAGE = _int("OCR_MIN_CHARS_PER_PAGE", 40)

    CATEGORIES = [
        "College FAQs",
        "Fee Structure",
        "Examination Notices",
        "Academic Documents",
        "College Circulars",
        "Other Documents",
    ]

    NOT_FOUND_MESSAGE = "I could not find this information in the available college documents."
