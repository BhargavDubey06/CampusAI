/* CampusAI – chatbot page logic */
(() => {
  const { api, toast, esc, icons, KEYS, state } = CampusAI;
  const $ = (id) => document.getElementById(id);
  const el = {
    welcome: $("welcome"), messages: $("messages"), body: $("chatBody"), form: $("chatForm"),
    input: $("chatInput"), send: $("sendBtn"), mic: $("micBtn"), lang: $("langSelect"),
    historyList: $("historyList"), docCtx: $("docContext"), docCtxName: $("docContextName"),
    sidebar: $("sidebar"), backdrop: $("backdrop"),
  };
  let conversationId = sessionStorage.getItem(KEYS.conv) || null;
  let docContext = null;
  let busy = false;
  const modals = {};
  const modal = (id) => (modals[id] ||= new bootstrap.Modal($(id)));

  // ---------------------------------------------------------------- helpers
  function renderMarkdown(text) {
    if (window.marked && window.DOMPurify) {
      return DOMPurify.sanitize(marked.parse(text, { breaks: true, gfm: true }));
    }
    return `<p>${esc(text).replace(/\n/g, "<br>")}</p>`;
  }
  const scrollDown = () => requestAnimationFrame(() => { el.body.scrollTop = el.body.scrollHeight; });

  function showMessagesView() {
    el.welcome.hidden = true; el.messages.hidden = false;
  }
  function showWelcome() {
    el.messages.innerHTML = ""; el.messages.hidden = true; el.welcome.hidden = false;
  }
  function setBusy(b) {
    busy = b; el.send.disabled = b || !el.input.value.trim();
    el.input.disabled = b;
    if (!b) el.input.focus();
  }

  // ------------------------------------------------------------ rendering
  function addUserMessage(text) {
    showMessagesView();
    const d = document.createElement("div");
    d.className = "msg user";
    d.innerHTML = `<div class="bubble-user">${esc(text)}</div>`;
    el.messages.appendChild(d); scrollDown();
  }

  function addTyping() {
    const d = document.createElement("div");
    d.className = "msg"; d.id = "typing";
    d.innerHTML = `<div class="ai-avatar"></div><div class="ai-body"><div class="typing" aria-label="CampusAI is typing"><i></i><i></i><i></i></div></div>`;
    el.messages.appendChild(d); scrollDown();
  }
  const removeTyping = () => $("typing")?.remove();

  function sourceChip(s) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "source-chip"; b.title = s.excerpt || "";
    b.innerHTML = `<i data-lucide="${s.type === "faq" ? "circle-help" : "file-text"}" class="i i-sm"></i>${esc(s.name)}${s.page ? `<span class="pg">p.${s.page}</span>` : ""}`;
    b.onclick = () => {
      if (s.document_id) location.href = `documents.html?doc=${s.document_id}`;
      else openFaqs();
    };
    return b;
  }

  function addAIMessage(text, sources = [], chatId = null, opts = {}) {
    showMessagesView();
    const d = document.createElement("div");
    d.className = "msg";
    d.innerHTML = `<div class="ai-avatar"></div><div class="ai-body"><div class="md"></div></div>`;
    const body = d.querySelector(".ai-body");
    d.querySelector(".md").innerHTML = renderMarkdown(text);
    d.querySelectorAll(".md a").forEach((a) => { a.target = "_blank"; a.rel = "noopener noreferrer"; });

    if (sources.length) {
      const wrap = document.createElement("div"); wrap.className = "sources";
      wrap.innerHTML = `<span class="lbl">Sources</span>`;
      sources.forEach((s) => wrap.appendChild(sourceChip(s)));
      body.appendChild(wrap);
    }
    if (!opts.error) {
      const act = document.createElement("div"); act.className = "msg-actions";
      act.innerHTML = `
        <button class="act-btn" data-a="copy" title="Copy" aria-label="Copy answer"><i data-lucide="copy" class="i i-sm"></i></button>
        <button class="act-btn" data-a="like" title="Helpful" aria-label="Like"><i data-lucide="thumbs-up" class="i i-sm"></i></button>
        <button class="act-btn" data-a="dislike" title="Not helpful" aria-label="Dislike"><i data-lucide="thumbs-down" class="i i-sm"></i></button><button class="act-btn" data-a="report" title="Report incorrect answer" aria-label="Report incorrect answer"><i data-lucide="flag" class="i i-sm"></i></button><button class="act-btn" data-a="speak" title="Read answer aloud" aria-label="Read answer aloud"><i data-lucide="volume-2" class="i i-sm"></i></button>`;
      act.addEventListener("click", async (e) => {
        const b = e.target.closest(".act-btn"); if (!b) return;
        const a = b.dataset.a;
        if (a === "speak") { if (!window.speechSynthesis) { toast("Text-to-speech is unavailable in this browser.", "error"); return; } const utter = new SpeechSynthesisUtterance(text.replace(/[#*`>\[\]]/g, "")); utter.lang = {English:"en-IN",Hindi:"hi-IN",Marathi:"mr-IN"}[el.lang.value] || "en-IN"; speechSynthesis.cancel(); speechSynthesis.speak(utter); return; }
        if (a === "report") { const comment = prompt("What is incorrect or missing in this answer?"); if (!comment || !comment.trim()) return; try { await api("/api/feedback/report", { method: "POST", body: { chat_id: chatId, comment } }); toast("Report sent to the admin.", "ok"); } catch(err) { toast(err.message, "error"); } return; }
        if (a === "copy") {
          try { await navigator.clipboard.writeText(text); toast("Answer copied", "ok"); }
          catch { toast("Could not copy to clipboard", "error"); }
          return;
        }
        if (!chatId) { toast("Feedback is unavailable for this message."); return; }
        try {
          await api("/api/feedback", { method: "POST", body: { kind: a, chat_id: chatId } });
          act.querySelectorAll('[data-a="like"],[data-a="dislike"]').forEach((x) => x.classList.remove("on"));
          b.classList.add("on");
          toast("Thanks for your feedback!", "ok");
        } catch (err) { toast(err.message, "error"); }
      });
      body.appendChild(act);
    }
    el.messages.appendChild(d); icons(); scrollDown();
  }

  // ------------------------------------------------------------- sending
  async function ask(question) {
    question = question.trim();
    if (!question || busy) return;
    addUserMessage(question);
    el.input.value = ""; el.input.style.height = "auto";
    setBusy(true); addTyping();
    try {
      const data = await api("/api/chat", {
        method: "POST",
        body: { message: question, conversation_id: conversationId, document_id: docContext?.id ?? null, language: el.lang.value },
      });
      conversationId = data.conversation_id;
      sessionStorage.setItem(KEYS.conv, conversationId);
      removeTyping();
      addAIMessage(data.answer, data.sources, data.chat_id, { error: data.error === "llm_error" });
      loadHistory();
    } catch (err) {
      removeTyping();
      addAIMessage(`⚠️ ${err.message}`, [], null, { error: true });
    } finally { setBusy(false); }
  }

  el.form.addEventListener("submit", (e) => { e.preventDefault(); ask(el.input.value); });
  el.input.addEventListener("input", () => { el.send.disabled = busy || !el.input.value.trim(); });
  el.input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(el.input.value); } });
  CampusAI.autoGrow(el.input);
  document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => ask(c.dataset.q)));

  // --------------------------------------------------------- conversations
  function setActiveNav(name) {
    document.querySelectorAll(".side-item[data-nav]").forEach((i) => i.classList.toggle("active", i.dataset.nav === name));
  }

  async function loadHistory() {
    try {
      const { conversations } = await api("/api/conversations");
      el.historyList.innerHTML = conversations.length ? "" : `<div class="history-empty">No chats yet</div>`;
      conversations.forEach((c) => {
        const row = document.createElement("div");
        row.className = "history-item" + (c.conversation_id === conversationId ? " current" : "");
        row.innerHTML = `<span title="${esc(c.title)}">${esc(c.title || "Untitled chat")}</span><button aria-label="Delete chat"><i data-lucide="trash-2" class="i i-sm"></i></button>`;
        row.onclick = () => openConversation(c.conversation_id);
        row.querySelector("button").onclick = async (e) => {
          e.stopPropagation();
          await api(`/api/conversations/${c.conversation_id}`, { method: "DELETE" });
          if (c.conversation_id === conversationId) newChat();
          loadHistory();
        };
        el.historyList.appendChild(row);
      });
      icons();
    } catch (e) { el.historyList.innerHTML = `<div class="history-empty">Could not load history</div>`; }
  }

  async function openConversation(id) {
    try {
      const { messages } = await api(`/api/conversations/${id}`);
      if (!messages.length) { newChat(); return; }
      conversationId = id; sessionStorage.setItem(KEYS.conv, id);
      el.messages.innerHTML = "";
      messages.forEach((m) => m.role === "user" ? addUserMessage(m.message) : addAIMessage(m.message, m.sources, m.id));
      setActiveNav("new"); closeSidebar(); loadHistory(); scrollDown();
    } catch (e) { toast(e.message, "error"); }
  }

  function newChat() {
    conversationId = null; sessionStorage.removeItem(KEYS.conv);
    setDocContext(null); showWelcome(); setActiveNav("new"); closeSidebar(); el.input.focus(); loadHistory();
  }

  // ---------------------------------------------------- document context
  function setDocContext(ctx) {
    docContext = ctx;
    if (ctx) sessionStorage.setItem(KEYS.docCtx, JSON.stringify(ctx)); else sessionStorage.removeItem(KEYS.docCtx);
    el.docCtx.hidden = !ctx;
    if (ctx) {
      el.docCtxName.textContent = `Asking about: ${ctx.title}`;
      el.input.placeholder = `Ask a question about “${ctx.title}”...`;
    } else el.input.placeholder = "Ask me anything about your college...";
  }
  $("docContextClear").onclick = () => { setDocContext(null); toast("Now searching all college documents."); };

  // --------------------------------------------------------------- sidebar
  const openSidebar = () => { el.sidebar.classList.add("open"); el.backdrop.classList.add("show"); };
  function closeSidebar() { el.sidebar.classList.remove("open"); el.backdrop.classList.remove("show"); }
  $("menuBtn").onclick = openSidebar; $("sidebarClose").onclick = closeSidebar; el.backdrop.onclick = closeSidebar;

  async function openFaqs() {
    const body = $("faqBody");
    body.innerHTML = `<p class="text-secondary">Loading…</p>`; modal("faqModal").show();
    try {
      const { faqs } = await api("/api/faqs");
      if (!faqs.length) { body.innerHTML = `<div class="empty-state">No FAQs have been added yet.${state.user?.role === "admin" ? ' <a class="link-orange" href="admin.html">Add some</a>' : ""}</div>`; return; }
      body.innerHTML = "";
      faqs.forEach((f) => {
        const d = document.createElement("div"); d.className = "faq-item";
        d.innerHTML = `<div class="cat-tag">${esc(f.category)}</div><h4>${esc(f.question)}</h4><p>${esc(f.answer)}</p><button class="link-orange" style="font-size:.82rem">Ask CampusAI about this →</button>`;
        d.querySelector("button").onclick = () => { modal("faqModal").hide(); ask(f.question); };
        body.appendChild(d);
      });
    } catch (e) { body.innerHTML = `<div class="form-error">${esc(e.message)}</div>`; }
  }

  async function openNotices() {
    const body = $("noticesBody");
    body.innerHTML = `<p class="text-secondary">Loading…</p>`; modal("noticesModal").show();
    try {
      const { documents } = await api("/api/documents");
      const items = documents.filter((d) => ["Examination Notices", "College Circulars"].includes(d.category));
      if (!items.length) { body.innerHTML = `<div class="empty-state">No notices or circulars have been uploaded yet.</div>`; return; }
      body.innerHTML = "";
      items.forEach((d) => {
        const r = document.createElement("div"); r.className = "notice-row";
        r.innerHTML = `<div class="t"><span class="cat-tag">${esc(d.category)}</span><b>${esc(d.title)}</b><small>${CampusAI.fmtDate(d.created_at)}</small></div>
          <a class="btn-ghost" href="documents.html?doc=${d.id}">Open</a>
          <button class="btn-grad"${d.status !== "ready" ? " disabled" : ""}>Ask AI</button>`;
        r.querySelector("button").onclick = () => { setDocContext({ id: d.id, title: d.title }); modal("noticesModal").hide(); newChatKeepContext(); };
        body.appendChild(r);
      });
    } catch (e) { body.innerHTML = `<div class="form-error">${esc(e.message)}</div>`; }
  }
  function newChatKeepContext() {
    const ctx = docContext; newChat(); setDocContext(ctx); el.input.focus();
  }

  document.querySelectorAll(".side-item[data-nav]").forEach((item) => {
    item.addEventListener("click", () => {
      const n = item.dataset.nav;
      if (n === "docs") return;                       // plain link
      if (n === "new") return newChat();
      if (n === "history") { el.historyList.classList.toggle("show"); item.classList.toggle("open"); if (el.historyList.classList.contains("show")) loadHistory(); return; }
      setActiveNav(n);
      if (n === "faqs") openFaqs();
      if (n === "notices") openNotices();
      if (n === "feedback") modal("feedbackModal").show();
      if (n === "settings") openSettings();
    });
  });
  ["faqModal", "noticesModal", "feedbackModal", "settingsModal"].forEach((id) =>
    $(id).addEventListener("hidden.bs.modal", () => setActiveNav("new")));

  // ------------------------------------------------------- feedback / settings
  $("feedbackForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("fbSubmit"), err = $("fbError"); btn.disabled = true; err.textContent = "";
    try {
      await api("/api/feedback", { method: "POST", body: { kind: "general", comment: $("fbText").value, contact: $("fbContact").value } });
      toast("Thank you! Your feedback was sent.", "ok"); $("feedbackForm").reset(); modal("feedbackModal").hide();
    } catch (ex) { err.textContent = ex.message; } finally { btn.disabled = false; }
  });

  function openSettings() {
    $("settingsLang").value = el.lang.value;
    $("settingsStatus").textContent = state.llmConfigured ? "" : "The AI model API key is not configured on the server yet.";
    modal("settingsModal").show();
  }
  $("topSettings").onclick = () => { setActiveNav("settings"); openSettings(); };
  $("settingsLang").onchange = (e) => setLang(e.target.value);
  $("clearHistory").onclick = async () => {
    if (!confirm("Delete all of your chats? This cannot be undone.")) return;
    try { await api("/api/conversations", { method: "DELETE" }); newChat(); modal("settingsModal").hide(); toast("Chat history cleared.", "ok"); }
    catch (e) { toast(e.message, "error"); }
  };
  function setLang(v) { el.lang.value = v; $("settingsLang").value = v; localStorage.setItem(KEYS.lang, v); }
  el.lang.onchange = () => setLang(el.lang.value);

  // ------------------------------------------------------------------ voice
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec = null;
  el.mic.addEventListener("click", () => {
    if (!SR) { toast("Voice input is not supported in this browser. Try Chrome or Edge.", "error"); return; }
    if (rec) { rec.stop(); return; }
    rec = new SR();
    rec.lang = { English: "en-IN", Hindi: "hi-IN", Marathi: "mr-IN" }[el.lang.value] || "en-IN";
    rec.interimResults = true;
    const base = el.input.value ? el.input.value + " " : "";
    rec.onstart = () => el.mic.classList.add("rec");
    rec.onresult = (ev) => {
      el.input.value = base + Array.from(ev.results).map((r) => r[0].transcript).join("");
      el.input.dispatchEvent(new Event("input"));
    };
    rec.onerror = (ev) => toast(ev.error === "not-allowed" ? "Microphone permission was denied." : `Voice input error: ${ev.error}`, "error");
    rec.onend = () => { el.mic.classList.remove("rec"); rec = null; };
    rec.start();
  });

  // ------------------------------------------------------------------ boot
  document.addEventListener("campusai:ready", async () => {
    setLang(localStorage.getItem(KEYS.lang) || "English");
    const updateAdmin = () => { $("adminLink").hidden = state.user?.role !== "admin"; };
    updateAdmin(); CampusAI.onAuthChange(() => { updateAdmin(); loadHistory(); });
    if (state.user?.role === "admin" && !state.llmConfigured) toast("Admin notice: LLM_API_KEY is not set, so answers can't be generated yet.", "error");

    try { const raw = sessionStorage.getItem(KEYS.docCtx); if (raw) setDocContext(JSON.parse(raw)); } catch { setDocContext(null); }

    const pending = sessionStorage.getItem(KEYS.pending);
    if (pending) {                                   // question typed on the welcome page
      sessionStorage.removeItem(KEYS.pending);
      conversationId = null; loadHistory(); ask(pending);
      return;
    }
    if (conversationId) await openConversation(conversationId);
    else loadHistory();
    el.input.focus();
  });
})();
