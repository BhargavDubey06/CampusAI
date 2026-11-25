# CampusAI – AI College Assistant

CampusAI is a chatbot website that answers questions about your college **only from the college's own PDFs and FAQs** (Retrieval-Augmented Generation). If the answer is not in the documents, it says:

> I could not find this information in the available college documents.

**Stack:** HTML5 · CSS3 · Bootstrap 5 · JavaScript · Python Flask · SQLite · FAISS · Hugging Face sentence-transformers · an LLM API (Claude by default, or any OpenAI-compatible API).

## Pages

| Page | File | What it does |
|---|---|---|
| 1. Welcome (orange) | `frontend/index.html` | Landing page. A question typed here is carried into the chatbot. |
| 2. Chatbot (black) | `frontend/chatbot.html` | Chat, history, FAQs, notices, feedback, settings, voice input. |
| 3. Knowledge base | `frontend/documents.html` | Upload / search / preview PDFs, "Ask AI About This Document". |
| Admin | `frontend/admin.html` | Stats, document, FAQ and feedback management. |

## 1. Install

You need **Python 3.10+**.

```bash
cd CampusAI
python -m venv venv
# Windows:  venv\Scripts\activate
# Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
```

The first start downloads the embedding model (~90 MB) once; an internet connection is needed for that.

### Optional: OCR for scanned PDFs
Scanned (image-only) PDFs need the Tesseract program:
- Windows: install from https://github.com/UB-Mannheim/tesseract/wiki and add it to PATH
- Ubuntu/Debian: `sudo apt install tesseract-ocr`
- macOS: `brew install tesseract`

Without Tesseract, normal text PDFs still work; scanned ones show "No readable text found".

## 2. Configure the API key

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

Open `.env` and set at least:

```
LLM_API_KEY=your-api-key
SECRET_KEY=some-long-random-text
ADMIN_EMAIL=admin@campusai.local
ADMIN_PASSWORD=choose-a-strong-password
```

- **Claude (default):** `LLM_PROVIDER=anthropic`, `LLM_MODEL=claude-sonnet-5-5`, key from https://console.anthropic.com
- **OpenAI / Groq / OpenRouter / local Ollama:** `LLM_PROVIDER=openai`, set `LLM_MODEL`, and for non-OpenAI servers set `LLM_BASE_URL` (e.g. `http://localhost:11434/v1`).

Never commit `.env`; it holds your secrets.

## 3. Run

```bash
python run.py
```

Open **http://127.0.0.1:5000**. The database (`campusai.db`) and the admin account are created automatically on first start.

## 4. Upload college PDFs

1. Click **Login** and sign in with the admin email/password from `.env`.
2. Open **Documents**.
3. Pick a category (Fee Structure, Examination Notices, …), then drag & drop PDFs or click **Choose PDFs**.
4. Wait for the status badge to turn **READY** (text is extracted, split into chunks, embedded and stored in FAISS).
5. Optional: in **Admin → FAQs** add common questions and answers; they are searched together with the documents.

Only administrators can upload or delete documents. Students can register, chat and read documents.

## 5. Start chatting

- On the welcome page type a question and press send, or click **Start Chatting**.
- Use the suggestion chips (College Fees, Exam Timetable, …) or type your own question.
- Every answer shows its **source documents** (click a source to open it), and has Copy / Like / Dislike buttons.
- To ask about one specific file: **Documents → select it → Ask AI About This Document**.
- Sidebar: **Chat History**, **College FAQs**, **Notices**, **Feedback**, **Settings** (language, clear history).

## How it works

```
PDF upload → extract text (PyMuPDF/pypdf, OCR if scanned) → clean → chunk (900 chars, 150 overlap)
  → embed (sentence-transformers) → FAISS index
Question → embed → top-5 similar chunks (below a similarity threshold = "not found")
  → LLM with strict "answer only from context" prompt → answer + sources
```

## Project structure

```
CampusAI/
├── frontend/   index.html, chatbot.html, documents.html, admin.html, css/style.css, js/*.js
├── backend/    app.py (Flask + API) · chatbot.py (LLM + chat) · database.py (SQLite)
│               document_processor.py (PDF) · rag.py (embeddings + FAISS) · config.py
├── uploads/        uploaded PDFs
├── vector_store/   saved vectors + FAISS index
├── run.py, requirements.txt, .env.example
```

SQLite tables: `users`, `faqs`, `documents`, `chat_history`, `feedback` (plus `chunks`, which stores the text pieces behind the vector index).

## Troubleshooting

- **"LLM_API_KEY is not set" message in chat** – add your key to `.env` and restart.
- **Retrieval quality is poor / log says "falling back to the hashing embedder"** – `sentence-transformers` is not installed or the model could not be downloaded. Run `pip install sentence-transformers` and restart; the index rebuilds itself automatically.
- **Document stuck on FAILED** – open it to read the reason; scanned PDFs need Tesseract (see above). Use *Reprocess* afterwards.
- **Change the port** – set `PORT=8000` in `.env`.
- **Deploying for real** – set a strong `SECRET_KEY` and `ADMIN_PASSWORD`, run behind HTTPS and a production server (e.g. `gunicorn -w 1 'backend.app:create_app()'`; keep one worker so the in-memory index stays consistent).

## 6. New Smart Features (added in this version)

Open **Smart Features** from the chatbot sidebar or the Admin navigation.

### Smart Notice Analyzer
- Admin uploads a PDF notice from the Smart Features page.
- The existing PDF text extractor/OCR processes it.
- When an LLM API key is configured, CampusAI asks the configured model to extract title, deadline, event date, eligible students, action, required documents and contact details. It asks the model not to guess and requires empty values for missing fields.
- If the AI extraction call is unavailable, simple text/regex extraction is used as a fallback.
- Admin reviews the extracted fields and text, then publishes the notice. Students only see published notices.
- Notice uploads are also stored in the existing document knowledge base and indexed for chatbot retrieval.

### Interactive Checklists
- Student account required.
- Notice-derived checklist suggestions are created from extracted action/document lines.
- Students can check off suggested tasks and add personal tasks. Checklist state is stored per student in SQLite.

### Smart Reminders
- Students can save reminder title, reminder time and due time.
- A single-process background scheduler (started by `python run.py`) checks reminders every minute and changes due reminders to triggered.
- The Smart Features page polls triggered reminders and can display browser notifications. The page must remain open for browser notifications to be polled; grant browser notification permission explicitly.
- For multiple production workers/instances, replace this simple scheduler with a dedicated scheduler/worker (e.g. APScheduler/Celery or an external scheduled process) to avoid duplicated worker loops.

### Voice interaction
- The chat microphone uses the browser SpeechRecognition API for speech-to-text (English/Hindi/Marathi selection).
- A new speaker button uses browser speech synthesis to read the AI response aloud. Browser support and installed language voices vary.

### Feedback and incorrect-answer reporting
- Existing like/dislike buttons remain.
- A new flag/report button asks the student what was wrong and stores a report tied to the chat answer.
- Admin can view reports in the existing Feedback tab.

### Knowledge gap detection
- When retrieval returns no chunks, the question is stored as an unanswered query.
- Similar wording is grouped using token overlap and a text similarity score (not semantic embeddings in this first implementation); count and last-seen are updated.
- Admin sees unresolved groups on the Smart Features page and can mark them resolved. Upload relevant material and rebuild the vector index through the existing Admin tools when needed.

### Feature implementation files
- `backend/features.py` — feature API endpoints, notice parsing, checklist/reminder persistence, feedback reports and gap grouping.
- `backend/reminder_scheduler.py` — reminder trigger worker for the single-process local run.
- `frontend/features.html` / `frontend/js/features.js` — student feature center and admin notice/gap UI.
- `frontend/js/chatbot.js` — response speech, incorrect-answer reporting and existing speech recognition input.

Feature database tables are created automatically when the application starts. Existing CampusAI tables are not replaced.

**Limitations:** notice fields should be reviewed by an administrator before publishing; extraction is model/regex based and may miss or misinterpret details. The current reminder implementation is local/browser-notification based and does not send email or WhatsApp. Knowledge-gap similarity is a lightweight text match rather than a semantic clustering model.

> **Clean source archive:** local database files, previously uploaded college PDFs, saved vector indexes, virtual environments, and any `.env` secrets were excluded from this package. CampusAI will create a fresh SQLite database on first startup; upload your college documents again in your own working copy.
#   C a m p u s A I  
 