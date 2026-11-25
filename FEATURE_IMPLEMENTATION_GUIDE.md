# CampusAI – Integrated Feature Implementation Guide

This source package keeps the original CampusAI Flask/RAG chatbot and adds six requested feature areas. The additions are a starter implementation that should be tested with your college's documents and user accounts before a public deployment.

## Feature 1 — Smart Notice Analyzer

**Admin page:** `Smart Features` (`/features`)

1. Log in using the administrator account.
2. Upload a PDF notice from the Smart Notice Analyzer form.
3. CampusAI runs its existing PDF text extraction/OCR processing and adds the notice PDF to the document knowledge base.
4. If an LLM API key is configured, it requests structured fields (title, deadline, event date, applicable students/course/year, action, required documents and contact). The prompt directs the model to extract only facts present and leave missing fields blank.
5. If AI extraction is unavailable, rule/regex extraction is used as a fallback.
6. Review the displayed metadata and extracted text. Publish only after verifying it against the original notice.
7. Published notices are visible to students; drafts remain admin-only.

Notices are linked to the existing document ID and are searchable through the original chatbot RAG index.

## Feature 2 — Interactive Checklists

- Notice action and required-document lines create checklist suggestion templates.
- Students can open Smart Features, check suggested tasks, and add their own personal tasks.
- Checklist entries and checked state are saved in SQLite against the logged-in student.
- A template is saved to a student's personal checklist the first time they check it.

## Feature 3 — Smart Reminders

- Students create reminders with a title, reminder time and deadline time.
- The background scheduler in `backend/reminder_scheduler.py` changes scheduled reminders to triggered once they are due.
- `run.py` starts the scheduler. The Smart Features page checks triggered reminders once per minute.
- To receive desktop/browser notifications, open Smart Features and click **Enable browser notifications**. The page needs to remain open to poll the server.
- The reminder list is persisted; reminders can be deleted.

This local scheduler is a single-process implementation. A multi-instance production deployment should use a dedicated scheduler/worker instead of running a scheduler in every web process.

## Feature 4 — Voice Interaction

- Existing microphone speech-to-text is retained in the chatbot. It uses browser SpeechRecognition/WebkitSpeechRecognition and language selection (English, Hindi, Marathi).
- The new speaker action uses browser SpeechSynthesis to read an assistant answer.
- Voice availability depends on the browser and installed speech language voices.

## Feature 5 — Feedback and Incorrect Answer Reports

- Like/dislike actions remain available.
- The new report/flag action prompts the student for a description of the incorrect or missing answer.
- Reports are saved with the relevant assistant message ID and can be viewed/deleted in Admin → Feedback.

## Feature 6 — Knowledge Gap Detection

- If retrieval returns no supporting chunks, the user query is saved to `unanswered_queries`.
- Similar question strings are grouped using token overlap and a text-similarity ratio. This is a basic string-matching approach, not embedding-based semantic clustering.
- Admin → Smart Features displays unresolved groups and repeat counts. Mark a group resolved after uploading the missing document/information.
- Re-index the knowledge base using the existing Admin → Overview reindex action after document updates.

## Database additions

New tables are created automatically:

- `notices`
- `checklist_templates`
- `student_checklists`
- `reminders`
- `unanswered_queries`

Existing tables (`users`, `documents`, `chunks`, `chat_history`, `feedback`, etc.) are preserved. The feature schema includes a small migration for the `analysis_method` field on the notices table.

## New/modified code files

- `backend/features.py` — API routes, notice analyzer, feature database schema, checklists, reminders, reports and unanswered query tracking.
- `backend/reminder_scheduler.py` — local reminder trigger worker.
- `frontend/features.html` — feature page.
- `frontend/js/features.js` — student feature page and admin feature controls.
- `frontend/chatbot.html` — sidebar navigation link.
- `frontend/js/chatbot.js` — speech synthesis and answer-report action (existing speech-to-text retained).
- `frontend/admin.html` — Smart Features navigation link.
- `backend/app.py` — feature routes registration, page route and generated admin-password safety improvement.
- `backend/chatbot.py` — records no-retrieval questions for knowledge-gap detection.

## API routes added

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/notices/upload` | Admin uploads/analyzes notice PDF |
| GET | `/api/notices` | Published notices for students; all notices for admin |
| POST | `/api/admin/notices/<id>/publish` | Publish notice |
| POST | `/api/admin/notices/<id>/unpublish` | Unpublish notice |
| DELETE | `/api/admin/notices/<id>` | Delete notice and linked feature records |
| GET | `/api/checklists` | Student checklist |
| POST | `/api/checklists` | Add personal item or save a notice template |
| PATCH | `/api/checklists/<id>` | Update checked state |
| DELETE | `/api/checklists/<id>` | Delete item |
| POST | `/api/reminders` | Create reminder |
| GET | `/api/reminders` | List reminders |
| GET | `/api/reminders/due` | List triggered reminders awaiting notification |
| PATCH | `/api/reminders/<id>/dismiss` | Dismiss triggered reminder |
| DELETE | `/api/reminders/<id>` | Delete reminder |
| POST | `/api/feedback/report` | Submit incorrect-answer report |
| GET | `/api/admin/knowledge-gaps` | Admin unresolved gap list |
| PATCH | `/api/admin/knowledge-gaps/<id>` | Mark gap resolved |
| GET | `/api/admin/feature-summary` | Feature counters |

## Setup / run on Windows

1. Extract the ZIP.
2. Open the extracted `CampusAI` folder in VS Code.
3. Copy `.env.example` to `.env`.
4. Put your actual LLM API key and a strong administrator password in `.env`. Do not share or commit `.env`.
5. In the VS Code terminal:

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

6. Open `http://127.0.0.1:5000`.
7. Sign in as admin, then open **Smart Features** to upload/analyze notices and review knowledge gaps.
8. Register/login as a student to use personal checklists and reminders.

## Test checklist before presentation

- [ ] Admin uploads a valid text PDF notice and sees extracted fields.
- [ ] Admin uploads a scanned PDF notice with OCR installed.
- [ ] Admin verifies the fields and publishes a notice.
- [ ] Student sees only published notices.
- [ ] Student checks a suggested checklist item and refreshes; state remains saved.
- [ ] Student adds a personal checklist task and checks it.
- [ ] Student saves a reminder and verifies it appears in the reminder list.
- [ ] Scheduler marks a reminder triggered when its time passes.
- [ ] Browser notification works after notification permission is enabled and Smart Features page is open.
- [ ] Student reports an incorrect answer; admin sees it under Feedback.
- [ ] A question with no document match appears in Admin knowledge gaps.
- [ ] Similar unanswered wording increments a repeat count.
- [ ] Admin uploads the missing document, reindexes and marks the gap resolved.
- [ ] Existing chatbot, login, chat history, documents and FAQs still work.

## Important limitations

- Notice extraction is automatic but should be reviewed. LLM extraction may be unavailable; the fallback is keyword/date regex extraction.
- Browser notifications are not push notifications: the feature page must be open and browser permission granted. No email/WhatsApp sender is included.
- Knowledge-gap grouping is text similarity only in this version; it is not semantic/embedding clustering.
- The current code was syntax-checked, but full runtime/API tests require installing the Python dependencies. The build environment used to prepare this ZIP did not have Flask installed.
