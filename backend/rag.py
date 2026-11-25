"""Retrieval layer: embeddings, FAISS vector store, retrieval.

Embeddings come from Hugging Face sentence-transformers. If that library (or the
model download) is unavailable, a deterministic hashing embedder is used so the
app still runs; the README explains how to get the full-quality model.
"""
import hashlib
import json
import logging
import re
import threading

import numpy as np

from backend import database as db
from backend.config import Config

log = logging.getLogger("campusai.rag")

try:
    import faiss
except Exception:  # pragma: no cover
    faiss = None


# --------------------------------------------------------------- embedders
class SentenceTransformerEmbedder:
    def __init__(self, model_name):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name)
        self.name = model_name
        self.dim = int(self.model.get_sentence_embedding_dimension())
        self.default_min_score = 0.25

    def encode(self, texts):
        vecs = self.model.encode(list(texts), normalize_embeddings=True,
                                 show_progress_bar=False, convert_to_numpy=True)
        return np.asarray(vecs, dtype="float32")


_STOP = set("""a an the and or of to in on for with is are was were be been it this that these those
at by from as about what which who whom how when where why do does did can could should would
i me my we our you your their there any some please tell give""".split())


class HashingEmbedder:
    """Lexical fallback: hashed uni/bi-gram bag of words, L2 normalised."""
    dim = 768
    name = "hashing-768"
    default_min_score = 0.08

    def _tokens(self, text):
        words = [w for w in re.findall(r"\w+", text.lower()) if w not in _STOP]
        return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]

    def encode(self, texts):
        out = np.zeros((len(texts), self.dim), dtype="float32")
        for i, text in enumerate(texts):
            for tok in self._tokens(text):
                h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
                out[i, h % self.dim] += 1.0 if (h >> 100) & 1 else -1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return out / norms


def build_embedder():
    try:
        emb = SentenceTransformerEmbedder(Config.EMBEDDING_MODEL)
        log.info("Using embedding model %s (dim=%s)", emb.name, emb.dim)
        return emb
    except Exception as exc:
        log.warning("sentence-transformers unavailable (%s). Falling back to the hashing "
                    "embedder; retrieval quality will be lower. See README.", exc)
        return HashingEmbedder()


# ------------------------------------------------------------ vector store
class VectorStore:
    def __init__(self, embedder=None):
        self.embedder = embedder or build_embedder()
        self.lock = threading.RLock()
        self.vectors = np.zeros((0, self.embedder.dim), dtype="float32")
        self.meta = []          # aligned with vectors: chunk id, source, page, ...
        self.index = None
        self.dir = Config.VECTOR_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        self._load()

    # -- persistence
    @property
    def _vec_path(self):
        return self.dir / "vectors.npy"

    @property
    def _meta_path(self):
        return self.dir / "meta.json"

    def _save(self):
        np.save(self._vec_path, self.vectors)
        self._meta_path.write_text(json.dumps({"embedder": self.embedder.name, "items": self.meta}))
        if faiss is not None and self.index is not None:
            faiss.write_index(self.index, str(self.dir / "index.faiss"))

    def _load(self):
        db_chunks = db.all_chunks()
        try:
            data = json.loads(self._meta_path.read_text())
            vecs = np.load(self._vec_path)
            same = (data.get("embedder") == self.embedder.name
                    and len(vecs) == len(data["items"])
                    and [m["chunk_id"] for m in data["items"]] == [c["id"] for c in db_chunks])
            if same:
                self.vectors, self.meta = vecs.astype("float32"), data["items"]
                self._build_index()
                return
        except Exception:
            pass
        if db_chunks:
            log.info("Rebuilding vector store from %d stored chunks", len(db_chunks))
        self.reindex_all(db_chunks)

    def _build_index(self):
        if faiss is not None and len(self.vectors):
            self.index = faiss.IndexFlatIP(self.vectors.shape[1])
            self.index.add(self.vectors)
        else:
            self.index = None

    @staticmethod
    def _meta_for(row):
        return {"chunk_id": row["id"], "document_id": row.get("document_id"),
                "faq_id": row.get("faq_id"), "source": row["source_name"],
                "page": row.get("page"), "text": row["text"]}

    # -- mutation
    def reindex_all(self, rows=None):
        with self.lock:
            rows = db.all_chunks() if rows is None else rows
            if rows:
                self.vectors = self._embed([r["text"] for r in rows])
            else:
                self.vectors = np.zeros((0, self.embedder.dim), dtype="float32")
            self.meta = [self._meta_for(r) for r in rows]
            self._build_index()
            self._save()

    def _embed(self, texts, batch=64):
        parts = [self.embedder.encode(texts[i:i + batch]) for i in range(0, len(texts), batch)]
        return np.vstack(parts).astype("float32")

    def add(self, rows):
        if not rows:
            return
        with self.lock:
            new = self._embed([r["text"] for r in rows])
            self.vectors = np.vstack([self.vectors, new]) if len(self.vectors) else new
            self.meta.extend(self._meta_for(r) for r in rows)
            self._build_index()
            self._save()

    def remove(self, document_id=None, faq_id=None):
        with self.lock:
            keep = [i for i, m in enumerate(self.meta)
                    if not ((document_id is not None and m["document_id"] == document_id)
                            or (faq_id is not None and m["faq_id"] == faq_id))]
            if len(keep) == len(self.meta):
                return
            self.vectors = self.vectors[keep] if keep else np.zeros((0, self.embedder.dim), "float32")
            self.meta = [self.meta[i] for i in keep]
            self._build_index()
            self._save()

    # -- retrieval
    @property
    def min_score(self):
        return Config.MIN_SCORE if Config.MIN_SCORE is not None else self.embedder.default_min_score

    def search(self, question, k=None, document_id=None):
        """Return the top-k chunks above the similarity threshold, best first."""
        k = k or Config.TOP_K
        with self.lock:
            if not len(self.vectors):
                return []
            q = self.embedder.encode([question])
            if document_id is not None:
                ids = [i for i, m in enumerate(self.meta) if m["document_id"] == document_id]
                if not ids:
                    return []
                scores = (self.vectors[ids] @ q[0])
                order = np.argsort(-scores)[:k]
                hits = [(ids[j], float(scores[j])) for j in order]
            elif self.index is not None:
                scores, idxs = self.index.search(q, min(k, len(self.vectors)))
                hits = [(int(i), float(s)) for i, s in zip(idxs[0], scores[0]) if i >= 0]
            else:
                scores = self.vectors @ q[0]
                order = np.argsort(-scores)[:k]
                hits = [(int(i), float(scores[i])) for i in order]
            results = []
            for i, score in hits:
                if score < self.min_score:
                    continue
                m = self.meta[i]
                results.append({**m, "score": round(score, 4)})
            return results

    def stats(self):
        return {"chunks": len(self.meta), "embedder": self.embedder.name,
                "faiss": faiss is not None}
