/* CampusAI – admin dashboard */
(() => {
  const { api, toast, esc, icons, state, fmtSize, fmtDate } = CampusAI;
  const $ = (id) => document.getElementById(id);
  const root = $("adminRoot");
  let tab = "overview", faqModal, editingFaq = null;

  const isAdmin = () => state.user?.role === "admin";

  function gate() {
    if (isAdmin()) return true;
    root.innerHTML = `<div class="panel-light login-card text-center">
      <div class="up-icon mx-auto mb-3" style="width:54px;height:54px;border-radius:16px;display:grid;place-items:center;background:var(--grad);color:#fff"><i data-lucide="shield-check" class="i i-lg"></i></div>
      <h3>${state.user ? "Administrator access required" : "Administrator login"}</h3>
      <p style="color:#6b635e;font-size:.9rem">${state.user ? "Your account does not have admin rights." : "Log in with the admin account to manage the knowledge base."}</p>
      ${state.user ? "" : `<button class="btn-grad" id="gateLogin">Log in</button>`}</div>`;
    $("gateLogin")?.addEventListener("click", () => CampusAI.openLogin());
    icons(); return false;
  }

  function shell() {
    const tabs = [["overview", "layout-dashboard", "Overview"], ["documents", "files", "Documents"], ["faqs", "circle-help", "FAQs"], ["feedback", "message-square-heart", "Feedback"]];
    root.innerHTML = `<div class="admin-tabs" role="tablist">${tabs.map(([k, ic, l]) =>
      `<button class="cat-pill${tab === k ? " active" : ""}" data-tab="${k}" role="tab"><i data-lucide="${ic}" class="i i-sm" style="vertical-align:-3px;margin-right:6px"></i>${l}</button>`).join("")}</div><div id="tabBody"></div>`;
    root.querySelectorAll("[data-tab]").forEach((b) => b.onclick = () => { tab = b.dataset.tab; render(); });
    icons();
  }

  async function render() {
    if (!gate()) return;
    shell();
    const body = $("tabBody");
    body.innerHTML = `<p style="color:var(--muted)">Loading…</p>`;
    try {
      if (tab === "overview") await renderOverview(body);
      if (tab === "documents") await renderDocuments(body);
      if (tab === "faqs") await renderFaqs(body);
      if (tab === "feedback") await renderFeedback(body);
    } catch (e) { body.innerHTML = `<div class="err-box">${esc(e.message)}</div>`; }
    icons();
  }

  // ------------------------------------------------------------ overview
  async function renderOverview(body) {
    const { stats: s, store, llm_configured } = await api("/api/admin/stats");
    const cards = [
      ["files", s.documents, "Uploaded documents", `${s.documents_ready} ready`],
      ["circle-help", s.faqs, "FAQs", ""],
      ["messages-square", s.conversations, "Conversations", `${s.messages} messages`],
      ["message-square-heart", s.feedback, "Feedback items", `${s.likes} likes · ${s.dislikes} dislikes`],
    ];
    body.innerHTML = `
      <div class="row g-3 mb-4">${cards.map(([ic, v, l, sub]) => `
        <div class="col-6 col-lg-3"><div class="stat-card"><div class="ic"><i data-lucide="${ic}" class="i"></i></div><div class="v">${v}</div><div class="l">${l}${sub ? ` · ${sub}` : ""}</div></div></div>`).join("")}</div>
      <div class="row g-3">
        <div class="col-lg-8"><div class="panel-light"><h3>Recent uploads</h3>
          ${s.recent_uploads.length ? `<div class="table-scroll"><table class="table-c"><thead><tr><th>Title</th><th>Category</th><th>Status</th><th>Size</th><th>Uploaded</th></tr></thead><tbody>
          ${s.recent_uploads.map((d) => `<tr><td><a href="documents.html?doc=${d.id}"><b>${esc(d.title)}</b></a></td><td>${esc(d.category)}</td><td><span class="badge-status ${d.status}">${d.status}</span></td><td>${fmtSize(d.size_bytes)}</td><td>${fmtDate(d.created_at)}</td></tr>`).join("")}</tbody></table></div>`
            : `<p style="color:#8a817c">No documents uploaded yet.</p>`}
          <a class="btn-grad mt-3" href="documents.html"><i data-lucide="cloud-upload" class="i i-sm"></i>Upload documents</a></div></div>
        <div class="col-lg-4"><div class="panel-light"><h3>System status</h3>
          <table class="table-c"><tbody>
            <tr><td>AI model (LLM)</td><td><span class="badge-status ${llm_configured ? "ready" : "failed"}">${llm_configured ? "configured" : "API key missing"}</span></td></tr>
            <tr><td>Embedding model</td><td style="word-break:break-all">${esc(store.embedder)}</td></tr>
            <tr><td>Vector index</td><td>${store.faiss ? "FAISS" : "NumPy (faiss not installed)"}</td></tr>
            <tr><td>Indexed chunks</td><td>${store.chunks}</td></tr>
            <tr><td>Registered users</td><td>${s.users}</td></tr>
          </tbody></table>
          <button class="btn-light mt-3" id="reindexBtn"><i data-lucide="refresh-cw" class="i i-sm"></i>Rebuild search index</button></div></div>
      </div>`;
    $("reindexBtn").onclick = async (e) => {
      e.target.closest("button").disabled = true;
      try { await api("/api/admin/reindex", { method: "POST" }); toast("Search index rebuilt", "ok"); render(); }
      catch (err) { toast(err.message, "error"); e.target.closest("button").disabled = false; }
    };
  }

  // ----------------------------------------------------------- documents
  async function renderDocuments(body) {
    const { documents } = await api("/api/documents");
    body.innerHTML = `<div class="panel-light"><div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-2"><h3 class="mb-0">Document management</h3>
      <a class="btn-grad" href="documents.html"><i data-lucide="cloud-upload" class="i i-sm"></i>Upload PDFs</a></div>
      ${documents.length ? `<div class="table-scroll"><table class="table-c"><thead><tr><th>Title</th><th>Category</th><th>Status</th><th>Size</th><th>Uploaded</th><th></th></tr></thead><tbody>
      ${documents.map((d) => `<tr data-id="${d.id}"><td><b>${esc(d.title)}</b><br><small style="color:#8a817c">${esc(d.filename)}</small></td>
        <td><select class="c-select cat-sel" style="background:#fff;color:#222;border-color:#e4ddd9;padding:.35rem .6rem;font-size:.8rem">${state.categories.map((c) => `<option${c === d.category ? " selected" : ""}>${esc(c)}</option>`).join("")}</select></td>
        <td><span class="badge-status ${d.status}" title="${esc(d.error || "")}">${d.status}</span></td><td>${fmtSize(d.size_bytes)}</td><td>${fmtDate(d.created_at)}</td>
        <td><div class="row-actions"><a class="mini-btn" href="documents.html?doc=${d.id}" title="Open"><i data-lucide="eye" class="i i-sm"></i></a>
          <button class="mini-btn" data-act="reprocess" title="Reprocess"><i data-lucide="refresh-cw" class="i i-sm"></i></button>
          <button class="mini-btn danger" data-act="delete" title="Delete"><i data-lucide="trash-2" class="i i-sm"></i></button></div></td></tr>`).join("")}
      </tbody></table></div>` : `<p style="color:#8a817c">No documents yet.</p>`}</div>`;
    body.querySelectorAll("tr[data-id]").forEach((tr) => {
      const id = tr.dataset.id;
      tr.querySelector(".cat-sel").onchange = async (e) => {
        try { await api(`/api/documents/${id}`, { method: "PATCH", body: { category: e.target.value } }); toast("Category updated", "ok"); }
        catch (err) { toast(err.message, "error"); }
      };
      tr.querySelector('[data-act="reprocess"]').onclick = async () => {
        try { await api(`/api/documents/${id}/reprocess`, { method: "POST" }); toast("Reprocessing started", "ok"); setTimeout(render, 1500); }
        catch (err) { toast(err.message, "error"); }
      };
      tr.querySelector('[data-act="delete"]').onclick = async () => {
        if (!confirm("Delete this document and remove it from the knowledge base?")) return;
        try { await api(`/api/documents/${id}`, { method: "DELETE" }); toast("Document deleted", "ok"); render(); }
        catch (err) { toast(err.message, "error"); }
      };
    });
  }

  // ---------------------------------------------------------------- FAQs
  async function renderFaqs(body) {
    const { faqs } = await api("/api/faqs");
    body.innerHTML = `<div class="panel-light"><div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-2"><h3 class="mb-0">FAQ management</h3>
      <button class="btn-grad" id="addFaq"><i data-lucide="plus" class="i i-sm"></i>Add FAQ</button></div>
      ${faqs.length ? `<div class="table-scroll"><table class="table-c"><thead><tr><th>Question</th><th>Answer</th><th>Category</th><th></th></tr></thead><tbody>
      ${faqs.map((f) => `<tr data-id="${f.id}"><td style="min-width:200px"><b>${esc(f.question)}</b></td><td style="min-width:240px;color:#57504c">${esc(f.answer.length > 160 ? f.answer.slice(0, 160) + "…" : f.answer)}</td><td>${esc(f.category)}</td>
        <td><div class="row-actions"><button class="mini-btn" data-act="edit" title="Edit"><i data-lucide="pencil" class="i i-sm"></i></button>
        <button class="mini-btn danger" data-act="delete" title="Delete"><i data-lucide="trash-2" class="i i-sm"></i></button></div></td></tr>`).join("")}</tbody></table></div>`
      : `<p style="color:#8a817c">No FAQs yet. Add common questions and answers; the chatbot will use them alongside your documents.</p>`}</div>`;
    $("addFaq").onclick = () => openFaqModal(null);
    body.querySelectorAll("tr[data-id]").forEach((tr) => {
      const f = faqs.find((x) => x.id === +tr.dataset.id);
      tr.querySelector('[data-act="edit"]').onclick = () => openFaqModal(f);
      tr.querySelector('[data-act="delete"]').onclick = async () => {
        if (!confirm("Delete this FAQ?")) return;
        try { await api(`/api/faqs/${f.id}`, { method: "DELETE" }); toast("FAQ deleted", "ok"); render(); }
        catch (err) { toast(err.message, "error"); }
      };
    });
  }

  function openFaqModal(f) {
    editingFaq = f;
    $("faqModalTitle").textContent = f ? "Edit FAQ" : "Add FAQ";
    $("faqQ").value = f?.question || ""; $("faqA").value = f?.answer || "";
    $("faqCat").innerHTML = state.categories.map((c) => `<option${c === (f?.category || "College FAQs") ? " selected" : ""}>${esc(c)}</option>`).join("");
    $("faqErr").textContent = "";
    (faqModal ||= new bootstrap.Modal($("faqModal"))).show();
  }
  $("faqForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("faqSave"); btn.disabled = true; $("faqErr").textContent = "";
    const body = { question: $("faqQ").value, answer: $("faqA").value, category: $("faqCat").value };
    try {
      if (editingFaq) await api(`/api/faqs/${editingFaq.id}`, { method: "PUT", body });
      else await api("/api/faqs", { method: "POST", body });
      faqModal.hide(); toast("FAQ saved", "ok"); render();
    } catch (err) { $("faqErr").textContent = err.message; } finally { btn.disabled = false; }
  });

  // ------------------------------------------------------------ feedback
  async function renderFeedback(body) {
    const { feedback } = await api("/api/admin/feedback");
    const label = { like: ["ready", "👍 Like"], dislike: ["failed", "👎 Dislike"], general: ["processing", "💬 General"], report: ["failed", "🚩 Incorrect answer report"] };
    body.innerHTML = `<div class="panel-light"><h3>Feedback management</h3>
      ${feedback.length ? `<div class="table-scroll"><table class="table-c"><thead><tr><th>Type</th><th>Details</th><th>Contact</th><th>Date</th><th></th></tr></thead><tbody>
      ${feedback.map((f) => `<tr><td><span class="badge-status ${label[f.kind][0]}">${label[f.kind][1]}</span></td>
        <td style="min-width:240px">${f.comment ? esc(f.comment) : ""}${f.answer_excerpt ? `<div style="color:#8a817c;font-size:.78rem;margin-top:4px">On answer: “${esc(f.answer_excerpt)}…”</div>` : ""}</td>
        <td>${esc(f.contact || "—")}</td><td>${fmtDate(f.created_at)}</td>
        <td><button class="mini-btn danger" data-del="${f.id}" title="Delete"><i data-lucide="trash-2" class="i i-sm"></i></button></td></tr>`).join("")}</tbody></table></div>`
      : `<p style="color:#8a817c">No feedback received yet.</p>`}</div>`;
    body.querySelectorAll("[data-del]").forEach((b) => b.onclick = async () => {
      try { await api(`/api/admin/feedback/${b.dataset.del}`, { method: "DELETE" }); render(); } catch (err) { toast(err.message, "error"); }
    });
  }

  document.addEventListener("campusai:ready", () => { CampusAI.onAuthChange(render); render(); });
})();
