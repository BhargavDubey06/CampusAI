"""CampusAI add-on features: notices, checklists, reminders and knowledge gaps.
Feature APIs are registered from app.py with its authentication helpers.
"""
import json, re, sqlite3, uuid, difflib
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request
from backend import database as db
from backend.config import Config
from backend.document_processor import InvalidPDF, save_pdf, title_from_filename, process_document
from backend.chatbot import call_llm, LLMError, LLMNotConfigured

bp = Blueprint("features", __name__)

FEATURE_SCHEMA = """
CREATE TABLE IF NOT EXISTS notices (
 id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER UNIQUE, title TEXT NOT NULL,
 deadline TEXT, event_date TEXT, applicable TEXT, action TEXT, required_documents TEXT,
 contact TEXT, raw_text TEXT DEFAULT '', analysis_method TEXT DEFAULT 'rules', status TEXT DEFAULT 'draft', created_by INTEGER,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, published_at TEXT
);
CREATE TABLE IF NOT EXISTS checklist_templates (
 id INTEGER PRIMARY KEY AUTOINCREMENT, notice_id INTEGER, title TEXT NOT NULL, item TEXT NOT NULL,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS student_checklists (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, template_id INTEGER,
 notice_id INTEGER, item TEXT NOT NULL, checked INTEGER DEFAULT 0,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS reminders (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, notice_id INTEGER,
 title TEXT NOT NULL, due_at TEXT NOT NULL, remind_at TEXT NOT NULL,
 status TEXT DEFAULT 'scheduled', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 triggered_at TEXT, dismissed_at TEXT
);
CREATE TABLE IF NOT EXISTS unanswered_queries (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, question TEXT NOT NULL,
 normalized TEXT NOT NULL, category TEXT DEFAULT 'Other', count INTEGER DEFAULT 1,
 last_seen TEXT DEFAULT CURRENT_TIMESTAMP, resolved INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_reminders_user_status ON reminders(user_id,status,remind_at);
CREATE INDEX IF NOT EXISTS idx_checklists_user ON student_checklists(user_id);
"""

def init_feature_tables():
    with db.get_conn() as c:
        c.executescript(FEATURE_SCHEMA)
        cols={r['name'] for r in c.execute('PRAGMA table_info(notices)').fetchall()}
        if 'analysis_method' not in cols: c.execute("ALTER TABLE notices ADD COLUMN analysis_method TEXT DEFAULT 'rules'")

def _conn():
    return db.get_conn()

def _analyze_notice(text, fallback_title):
    clean = re.sub(r'\s+', ' ', text or '').strip()
    title = fallback_title
    for line in (text or '').splitlines():
        line = line.strip()
        if line and len(line) < 140 and any(k in line.lower() for k in ('notice','circular','exam','scholarship','admission','submission')):
            title = line; break
    dates = re.findall(r'\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*\d{0,4})\b', text or '', re.I)
    deadline = ''
    for m in re.finditer(r'(?:last date|deadline|on or before|before|by)\s*[:\-]?\s*([^\n.;]{4,45})', text or '', re.I):
        deadline = m.group(1).strip(); break
    if not deadline and dates: deadline = dates[-1]
    event_date = dates[0] if dates else ''
    course = ''
    for pat in (r'\b(?:all\s+)?(?:FY|SY|TY|first|second|third|final)\s*(?:students|year|years)?\b', r'\b(?:B\.?(?:A|Sc|Com|CS)|M\.?(?:A|Sc|Com)|MBA|MCA|BBA|BCA)\b'):
        m = re.search(pat, text or '', re.I)
        if m: course = m.group(0); break
    action = ''
    for line in (text or '').splitlines():
        if re.search(r'\b(submit|apply|register|pay|attend|collect|fill|upload|complete)\b', line, re.I):
            action = re.sub(r'\s+', ' ', line.strip())[:300]; break
    docs=[]
    for line in (text or '').splitlines():
        if re.search(r'\b(document|certificate|photocopy|copy|marksheet| Aadhaar|ID proof|fee receipt)\b', line, re.I):
            docs.append(line.strip()[:200])
    contact = ''
    email = re.search(r'[\w.+-]+@[\w.-]+\.\w+', text or '')
    phone = re.search(r'(?:\+?\d[\d\s-]{8,14}\d)', text or '')
    if email: contact=email.group(0)
    elif phone: contact=phone.group(0)
    extracted={'title': title, 'deadline': deadline, 'event_date': event_date, 'applicable': course,
            'action': action, 'required_documents': docs[:10], 'contact': contact, 'raw_text': clean[:30000], 'analysis_method':'rules'}
    if Config.LLM_API_KEY and clean:
        prompt=("Extract structured information from this college notice. Do not guess. Return ONLY valid JSON with keys: title, deadline, event_date, applicable, action, required_documents (array of strings), contact. Use empty string or [] when information is not present. Preserve dates as written.\n\nNOTICE TEXT:\n"+clean[:12000])
        try:
            response=call_llm("You are a careful college-notice information extractor. Only extract facts explicitly present in the notice; never invent.", [{'role':'user','content':prompt}])
            match=re.search(r'\{.*\}',response,re.S)
            if match:
                data=json.loads(match.group(0))
                for key in ('title','deadline','event_date','applicable','action','contact'):
                    val=data.get(key)
                    if isinstance(val,str): extracted[key]=val.strip()[:300]
                if isinstance(data.get('required_documents'),list): extracted['required_documents']=[str(x)[:200] for x in data['required_documents'][:10]]
                extracted['analysis_method']='AI extraction with rules fallback'
        except (LLMError,LLMNotConfigured,ValueError,TypeError,KeyError):
            pass
    return extracted

def register_feature_routes(app, *, current_user, owner_key, admin_required, store):
    init_feature_tables()
    def user_id():
        u=current_user(); return u['id'] if u else None
    def ensure_student():
        u=current_user()
        if not u: return None, (jsonify(error='Please log in to use personal checklists and reminders.'),401)
        if u['role']=='admin': return None, (jsonify(error='Student features require a student account.'),403)
        return u,None
    @app.post('/api/notices/upload')
    @admin_required
    def notice_upload():
        f=request.files.get('file')
        if not f or not f.filename: return jsonify(error='Select a notice PDF.'),400
        try: stored,size=save_pdf(f)
        except InvalidPDF as e: return jsonify(error=str(e)),400
        title=title_from_filename(f.filename)
        u=current_user(); docid=db.create_document(title,f.filename,stored,'Examination Notices',size,u['id'])
        # synchronous processing here ensures notice analysis can read text immediately
        process_document(docid,store)
        doc=db.get_document(docid)
        if doc['status']!='ready': return jsonify(error='PDF processing failed: '+(doc.get('error') or 'Unknown error'),document_id=docid),422
        fields=_analyze_notice(doc['extracted_text'],title)
        with _conn() as c:
            cur=c.execute("INSERT INTO notices(document_id,title,deadline,event_date,applicable,action,required_documents,contact,raw_text,analysis_method,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (docid,fields['title'],fields['deadline'],fields['event_date'],fields['applicable'],fields['action'],json.dumps(fields['required_documents']),fields['contact'],fields['raw_text'],fields.get('analysis_method','rules'),u['id']))
            nid=cur.lastrowid
            suggested=[x for x in [fields['action'],*(fields['required_documents'] or [])] if x]
            for item in suggested[:12]: c.execute('INSERT INTO checklist_templates(notice_id,title,item) VALUES(?,?,?)',(nid,fields['title'],item))
        return jsonify(notice=get_notice(nid),extracted_text=fields['raw_text'][:12000]),201
    def get_notice(nid):
        with _conn() as c:
            r=c.execute('SELECT * FROM notices WHERE id=?',(nid,)).fetchone()
            if not r:return None
            d=dict(r); d['required_documents']=json.loads(d['required_documents'] or '[]'); d.pop('raw_text',None); return d
    @app.get('/api/notices')
    def notices_list():
        u=current_user()
        sql='SELECT * FROM notices '+('WHERE status="published" ' if not u or u['role']!='admin' else '')+'ORDER BY created_at DESC'
        with _conn() as c: rows=c.execute(sql).fetchall()
        out=[]
        for r in rows:
            d=dict(r); d['required_documents']=json.loads(d['required_documents'] or '[]'); d.pop('raw_text',None); out.append(d)
        return jsonify(notices=out)
    @app.post('/api/admin/notices/<int:nid>/publish')
    @admin_required
    def notice_publish(nid):
        with _conn() as c:
            r=c.execute('SELECT id FROM notices WHERE id=?',(nid,)).fetchone()
            if not r:return jsonify(error='Notice not found.'),404
            c.execute("UPDATE notices SET status='published',published_at=CURRENT_TIMESTAMP WHERE id=?",(nid,))
        return jsonify(notice=get_notice(nid))
    @app.post('/api/admin/notices/<int:nid>/unpublish')
    @admin_required
    def notice_unpublish(nid):
        with _conn() as c:c.execute("UPDATE notices SET status='draft' WHERE id=?",(nid,))
        return jsonify(notice=get_notice(nid))
    @app.delete('/api/admin/notices/<int:nid>')
    @admin_required
    def notice_delete(nid):
        with _conn() as c:
            c.execute('DELETE FROM student_checklists WHERE notice_id=?',(nid,)); c.execute('DELETE FROM checklist_templates WHERE notice_id=?',(nid,)); c.execute('DELETE FROM reminders WHERE notice_id=?',(nid,)); c.execute('DELETE FROM notices WHERE id=?',(nid,))
        return jsonify(ok=True)
    @app.get('/api/checklists')
    def checklist_get():
        u,err=ensure_student()
        if err:return err
        with _conn() as c:
            templates=c.execute("SELECT t.*,n.status notice_status FROM checklist_templates t JOIN notices n ON n.id=t.notice_id WHERE n.status='published' ORDER BY t.id").fetchall()
            saved=c.execute('SELECT * FROM student_checklists WHERE user_id=? ORDER BY id',(u['id'],)).fetchall()
        savedmap={(r['template_id'],r['notice_id'],r['item']):dict(r) for r in saved}
        result=[]
        for t in templates:
            key=(t['id'],t['notice_id'],t['item']); r=savedmap.get(key)
            result.append({'template_id':t['id'],'notice_id':t['notice_id'],'title':t['title'],'item':t['item'],'checked':bool(r and r['checked']),'id':r['id'] if r else None})
        result.extend({'template_id':None,'notice_id':r['notice_id'],'title':'Personal task','item':r['item'],'checked':bool(r['checked']),'id':r['id']} for r in saved if not r['template_id'])
        return jsonify(items=result)
    @app.post('/api/checklists')
    def checklist_add():
        u,err=ensure_student()
        if err:return err
        d=request.get_json(silent=True) or {}; item=(d.get('item') or '').strip()[:500]
        if not item:return jsonify(error='Checklist item is required.'),400
        template_id=d.get('template_id')
        with _conn() as c:
            if template_id:
                t=c.execute('SELECT id,notice_id,item FROM checklist_templates WHERE id=?',(template_id,)).fetchone()
                if not t:return jsonify(error='Checklist template not found.'),404
                existing=c.execute('SELECT id FROM student_checklists WHERE user_id=? AND template_id=?',(u['id'],template_id)).fetchone()
                if existing:return jsonify(id=existing['id'],item=t['item'],checked=False)
                item=t['item']; notice_id=t['notice_id']
            else: notice_id=d.get('notice_id')
            checked=1 if d.get('checked') else 0
            cur=c.execute('INSERT INTO student_checklists(user_id,item,notice_id,template_id,checked) VALUES(?,?,?,?,?)',(u['id'],item,notice_id,template_id,checked))
        return jsonify(id=cur.lastrowid,item=item,checked=bool(checked)),201
    @app.patch('/api/checklists/<int:item_id>')
    def checklist_update(item_id):
        u,err=ensure_student()
        if err:return err
        d=request.get_json(silent=True) or {}
        with _conn() as c:
            r=c.execute('SELECT id FROM student_checklists WHERE id=? AND user_id=?',(item_id,u['id'])).fetchone()
            if not r:return jsonify(error='Checklist item not found.'),404
            c.execute('UPDATE student_checklists SET checked=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(1 if d.get('checked') else 0,item_id))
        return jsonify(ok=True)
    @app.delete('/api/checklists/<int:item_id>')
    def checklist_delete(item_id):
        u,err=ensure_student()
        if err:return err
        with _conn() as c:c.execute('DELETE FROM student_checklists WHERE id=? AND user_id=?',(item_id,u['id']))
        return jsonify(ok=True)
    @app.post('/api/reminders')
    def reminder_create():
        u,err=ensure_student()
        if err:return err
        d=request.get_json(silent=True) or {}; title=(d.get('title') or '').strip()[:200]
        try: due=datetime.fromisoformat(d['due_at']); remind=datetime.fromisoformat(d.get('remind_at') or d['due_at'])
        except Exception:return jsonify(error='Use valid ISO date/time for due_at and remind_at.'),400
        if due.tzinfo is None: due=due.astimezone()
        if remind.tzinfo is None: remind=remind.astimezone()
        if not title:return jsonify(error='Reminder title is required.'),400
        with _conn() as c:
            cur=c.execute('INSERT INTO reminders(user_id,notice_id,title,due_at,remind_at) VALUES(?,?,?,?,?)',(u['id'],d.get('notice_id'),title,due.isoformat(),remind.isoformat()))
        return jsonify(id=cur.lastrowid,title=title,due_at=due.isoformat(),remind_at=remind.isoformat(),status='scheduled'),201
    @app.get('/api/reminders')
    def reminder_list():
        u,err=ensure_student()
        if err:return err
        with _conn() as c:rows=c.execute('SELECT * FROM reminders WHERE user_id=? ORDER BY remind_at',(u['id'],)).fetchall()
        return jsonify(reminders=[dict(r) for r in rows])
    @app.get('/api/reminders/due')
    def reminder_due():
        u,err=ensure_student()
        if err:return err
        now=datetime.now().astimezone().isoformat()
        with _conn() as c:rows=c.execute("SELECT * FROM reminders WHERE user_id=? AND status='triggered' AND dismissed_at IS NULL ORDER BY remind_at",(u['id'],)).fetchall()
        return jsonify(reminders=[dict(r) for r in rows])
    @app.post('/api/reminders/tick')
    @admin_required
    def reminder_tick():
        from backend.reminder_scheduler import _tick
        _tick()
        return jsonify(ok=True)
    @app.patch('/api/reminders/<int:rid>/dismiss')
    def reminder_dismiss(rid):
        u,err=ensure_student()
        if err:return err
        with _conn() as c:c.execute("UPDATE reminders SET status='dismissed',dismissed_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",(rid,u['id']))
        return jsonify(ok=True)
    @app.delete('/api/reminders/<int:rid>')
    def reminder_delete(rid):
        u,err=ensure_student()
        if err:return err
        with _conn() as c:c.execute("DELETE FROM reminders WHERE id=? AND user_id=?",(rid,u['id']))
        return jsonify(ok=True)
    @app.post('/api/feedback/report')
    def feedback_report():
        d=request.get_json(silent=True) or {}; owner,uid=owner_key(); chat_id=d.get('chat_id'); comment=(d.get('comment') or '').strip()[:2000]
        if not comment:return jsonify(error='Describe what was incorrect.'),400
        if chat_id:
            msg=db.get_chat_message(int(chat_id)) if str(chat_id).isdigit() else None
            if not msg or msg['owner']!=owner:return jsonify(error='Message not found.'),404
        fid=db.add_feedback('report',comment,'',int(chat_id) if chat_id else None,owner)
        return jsonify(ok=True,id=fid),201
    @app.get('/api/admin/knowledge-gaps')
    @admin_required
    def gaps_admin():
        with _conn() as c:rows=c.execute('SELECT * FROM unanswered_queries WHERE resolved=0 ORDER BY count DESC,last_seen DESC').fetchall()
        return jsonify(gaps=[dict(r) for r in rows])
    @app.patch('/api/admin/knowledge-gaps/<int:gid>')
    @admin_required
    def gap_resolve(gid):
        with _conn() as c:c.execute('UPDATE unanswered_queries SET resolved=1 WHERE id=?',(gid,))
        return jsonify(ok=True)
    @app.post('/api/admin/knowledge-gaps/reindex')
    @admin_required
    def gap_reindex():
        store.reindex_all(); return jsonify(ok=True,store=store.stats())
    @app.get('/api/admin/feature-summary')
    @admin_required
    def feature_summary():
        with _conn() as c:
            return jsonify(notices=c.execute('SELECT COUNT(*) FROM notices').fetchone()[0],published=c.execute("SELECT COUNT(*) FROM notices WHERE status='published'").fetchone()[0],gaps=c.execute('SELECT COUNT(*) FROM unanswered_queries WHERE resolved=0').fetchone()[0],reports=c.execute("SELECT COUNT(*) FROM feedback WHERE kind='report'").fetchone()[0])
    return bp


def record_unanswered(user_id, question):
    question=(question or '').strip()
    if not question:return
    normalized=re.sub(r'[^a-z0-9 ]',' ',question.lower())
    normalized=re.sub(r'\s+',' ',normalized).strip()[:300]
    category='Other'
    for cat,keys in {'Examination':['exam','revaluation','result','timetable','form'],'Scholarship':['scholarship','renewal'],'Admission':['admission','apply','application'],'Fees':['fee','fees','payment'],'Hostel':['hostel','room']}.items():
        if any(k in normalized for k in keys):category=cat;break
    with _conn() as c:
        rows=c.execute('SELECT id,normalized FROM unanswered_queries WHERE resolved=0').fetchall()
        match=None
        tokens=set(normalized.split())
        for r in rows:
            old=set((r['normalized'] or '').split())
            overlap=len(tokens & old)/max(1,len(tokens|old))
            ratio=difflib.SequenceMatcher(None,normalized,r['normalized'] or '').ratio()
            if overlap>=0.60 or ratio>=0.76:
                match=r['id']; break
        if match:c.execute('UPDATE unanswered_queries SET count=count+1,last_seen=CURRENT_TIMESTAMP WHERE id=?',(match,))
        else:c.execute('INSERT INTO unanswered_queries(user_id,question,normalized,category) VALUES(?,?,?,?)',(user_id,question[:1000],normalized,category))
