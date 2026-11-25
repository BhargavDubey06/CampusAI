/* CampusAI – documents / knowledge base page */
(() => {
  const { api, toast, esc, icons, KEYS, state, fmtSize, fmtDate } = CampusAI;
  const $ = (id) => document.getElementById(id);
  const MAX_MB = 50;
  let allDocs = [], shown = [], category = "", query = "", selectedId = null, pollTimer = null, tab = "pdf";
  const params = new URLSearchParams(location.search);
  const isAdmin = () => state.user?.role === "admin";

  // ---------------------------------------------------------------- upload
  function renderUploadSection() {
    const box = $("uploadSection");
    if (!isAdmin()) {
      box.innerHTML = `<div class="lock-note"><i data-lucide="lock" class="i" style="vertical-align:-4px;margin-right:6px;color:var(--orange-soft)"></i>
        Only administrators can upload or delete official college documents.
        ${state.user ? "" : ` <button class="link-orange" id="lockLogin">Log in as admin</button>`}</div>`;
      $("lockLogin")?.addEventListener("click", () => CampusAI.openLogin());
      icons(); return;
    }
    box.innerHTML = `
      <div class="upload-zone" id="dropZone" tabindex="0" role="button" aria-label="Upload PDF documents">
        <div class="up-icon"><i data-lucide="cloud-upload" class="i i-lg"></i></div>
        <h3>Upload Your College Documents</h3>
        <p>Drag &amp; drop PDF files here, or click to browse · multiple files supported · up to ${MAX_MB} MB each</p>
        <div class="upload-controls">
          <select class="c-select" id="uploadCategory" aria-label="Document category">${state.categories.map((c) => `<option>${esc(c)}</option>`).join("")}</select>
          <button class="btn-grad" id="browseBtn" type="button"><i data-lucide="file-up" class="i i-sm"></i>Choose PDFs</button>
        </div>
        <input type="file" id="fileInput" accept="application/pdf,.pdf" multiple hidden>
      </div>
      <div class="upload-queue" id="uploadQueue"></div>`;
    const zone = $("dropZone"), input = $("fileInput");
    $("browseBtn").onclick = (e) => { e.stopPropagation(); input.click(); };
    zone.onclick = (e) => { if (!e.target.closest(".upload-controls")) input.click(); };
    zone.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } };
    input.onchange = () => { handleFiles(input.files); input.value = ""; };
    ["dragenter", "dragover"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("drag"); }));
    ["dragleave", "drop"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove("drag"); }));
    zone.addEventListener("drop", (e) => handleFiles(e.dataTransfer.files));
    icons();
  }

  function handleFiles(fileList) {
    const cat = $("uploadCategory").value;
    Array.from(fileList).forEach((f) => {
      const item = document.createElement("div"); item.className = "up-item";
      item.innerHTML = `<i data-lucide="file-text" class="i" style="color:var(--orange-deep)"></i>
        <div class="nm"><span>${esc(f.name)}</span><small>${fmtSize(f.size)} · waiting…</small><div class="progress-track"><div class="progress-fill"></div></div></div>`;
      $("uploadQueue").appendChild(item); icons();
      const small = item.querySelector("small"), fill = item.querySelector(".progress-fill");
      const fail = (msg) => { item.classList.add("err"); small.textContent = msg; toast(msg, "error"); };
      if (!/\.pdf$/i.test(f.name)) return fail(`${f.name}: only PDF files are allowed.`);
      if (f.size > MAX_MB * 1048576) return fail(`${f.name}: larger than ${MAX_MB} MB.`);
      if (f.size === 0) return fail(`${f.name}: the file is empty.`);

      const fd = new FormData(); fd.append("files", f); fd.append("category", cat);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/documents");
      xhr.upload.onprogress = (e) => {
        if (!e.lengthComputable) return;
        const p = Math.round((e.loaded / e.total) * 100); fill.style.width = p + "%";
        small.textContent = `${fmtSize(f.size)} · uploading ${p}%`;
      };
      xhr.onerror = () => fail(`${f.name}: network error during upload.`);
      xhr.onload = async () => {
        let data = {}; try { data = JSON.parse(xhr.responseText); } catch { /* ignore */ }
        if (xhr.status >= 200 && xhr.status < 300 && data.documents?.length) {
          fill.style.width = "100%"; small.textContent = `${fmtSize(f.size)} · uploaded, processing…`;
          toast(`${f.name} uploaded`, "ok");
          await loadDocs(); select(data.documents[0].id);
          setTimeout(() => item.remove(), 3000);
        } else fail(data.error || `${f.name}: upload failed (${xhr.status}).`);
      };
      xhr.send(fd);
    });
  }

  // ------------------------------------------------------------------ list
  function renderPills() {
    const counts = {}; allDocs.forEach((d) => { counts[d.category] = (counts[d.category] || 0) + 1; });
    const pills = [["", "All", allDocs.length], ...state.categories.map((c) => [c, c, counts[c] || 0])];
    $("catPills").innerHTML = pills.map(([v, l, n]) =>
      `<button class="cat-pill${category === v ? " active" : ""}" data-cat="${esc(v)}">${esc(l)}<span class="n">${n}</span></button>`).join("");
    $("catPills").querySelectorAll(".cat-pill").forEach((b) => b.onclick = () => { category = b.dataset.cat; refreshView(); });
  }

  async function refreshView() {
    renderPills();
    if (query) {
      try { shown = (await api(`/api/documents?q=${encodeURIComponent(query)}${category ? `&category=${encodeURIComponent(category)}` : ""}`)).documents; }
      catch (e) { toast(e.message, "error"); shown = []; }
    } else shown = category ? allDocs.filter((d) => d.category === category) : allDocs;
    renderList();
  }

  function renderList() {
    const list = $("docList");
    $("countLabel").textContent = `${shown.length} document${shown.length === 1 ? "" : "s"}`;
    if (!shown.length) {
      list.innerHTML = `<div class="empty-state"><i data-lucide="folder-open" class="i"></i><div>${query ? "No documents match your search." : "No documents here yet."}${isAdmin() ? "<br>Upload a PDF above to get started." : ""}</div></div>`;
      icons(); return;
    }
    list.innerHTML = "";
    shown.forEach((d) => {
      const b = document.createElement("button"); b.type = "button";
      b.className = "doc-card" + (d.id === selectedId ? " selected" : "");
      b.innerHTML = `<div class="doc-ico"><i data-lucide="file-text" class="i"></i></div>
        <div class="info"><h4>${esc(d.title)}</h4>
          <div class="meta"><span class="cat-chip">${esc(d.category)}</span><span>${fmtSize(d.size_bytes)}</span><span>${fmtDate(d.created_at)}</span>
          <span class="badge-status ${d.status}">${d.status}</span></div></div>`;
      b.onclick = () => select(d.id);
      list.appendChild(b);
    });
    icons();
  }

  async function loadDocs() {
    try { allDocs = (await api("/api/documents")).documents; }
    catch (e) { toast(e.message, "error"); allDocs = []; }
    await refreshView();
    schedulePoll();
  }

  function schedulePoll() {
    clearTimeout(pollTimer);
    if (allDocs.some((d) => d.status === "processing")) {
      pollTimer = setTimeout(async () => {
        await loadDocs();
        if (selectedId && tab !== "pdf") select(selectedId, true); else if (selectedId) updateStatusOnly();
      }, 2000);
    }
  }

  // --------------------------------------------------------------- preview
  async function updateStatusOnly() {
    const d = allDocs.find((x) => x.id === selectedId);
    const cur = $("previewPanel").dataset.status;
    if (d && cur && d.status !== cur) select(selectedId, true);
  }

  async function select(id, keepTab = false) {
    selectedId = id; if (!keepTab) tab = "pdf";
    renderList();
    const panel = $("previewPanel");
    let d;
    try { d = (await api(`/api/documents/${id}`)).document; }
    catch (e) { toast(e.message, "error"); return; }
    panel.dataset.status = d.status;
    const ready = d.status === "ready";
    panel.innerHTML = `
      <div class="preview-head">
        <h2>${esc(d.title)}</h2>
        <div class="preview-meta">
          <span><i data-lucide="folder" class="i i-sm"></i>${esc(d.category)}</span>
          <span><i data-lucide="calendar" class="i i-sm"></i>Uploaded ${fmtDate(d.created_at)}</span>
          <span><i data-lucide="hard-drive" class="i i-sm"></i>${fmtSize(d.size_bytes)}${d.pages ? ` · ${d.pages} page${d.pages > 1 ? "s" : ""}` : ""}</span>
          <span class="badge-status ${d.status}">${d.status}</span>
          ${d.used_ocr ? `<span class="badge-status processing">OCR</span>` : ""}
        </div>
        ${d.status === "failed" ? `<div class="err-box"><b>Processing failed.</b> ${esc(d.error || "")}</div>` : ""}
        ${d.status === "processing" ? `<div class="err-box" style="background:#fff0d6;color:#8a5200">Reading the document and building the search index…</div>` : ""}
        <div class="preview-actions">
          <button class="btn-grad" id="askBtn"${ready ? "" : " disabled"}><i data-lucide="sparkles" class="i i-sm"></i>Ask AI About This Document</button>
          <a class="btn-light" href="/api/documents/${d.id}/file" target="_blank" rel="noopener"><i data-lucide="external-link" class="i i-sm"></i>Open PDF</a>
          ${isAdmin() ? `<button class="btn-light" id="reprocessBtn"><i data-lucide="refresh-cw" class="i i-sm"></i>Reprocess</button>
          <button class="btn-light" id="deleteBtn" style="color:#c22"><i data-lucide="trash-2" class="i i-sm"></i>Delete</button>` : ""}
        </div>
      </div>
      <div class="preview-tabs">
        <button class="p-tab${tab === "pdf" ? " active" : ""}" data-tab="pdf">PDF Preview</button>
        <button class="p-tab${tab === "text" ? " active" : ""}" data-tab="text">Extracted Text</button>
      </div>
      <div id="previewBody"></div>`;
    const body = $("previewBody");
    if (tab === "pdf") body.innerHTML = `<iframe class="pdf-frame" title="PDF preview of ${esc(d.title)}" src="/api/documents/${d.id}/file#view=FitH"></iframe>`;
    else {
      const t = document.createElement("div"); t.className = "text-view";
      t.textContent = d.extracted_text || (d.status === "processing" ? "Text extraction in progress…" : "No text could be extracted from this document.");
      body.appendChild(t);
    }
    panel.querySelectorAll(".p-tab").forEach((b) => b.onclick = () => { tab = b.dataset.tab; select(id, true); });
    $("askBtn").onclick = () => askAboutDocument(d);
    $("reprocessBtn")?.addEventListener("click", async () => {
      try { await api(`/api/documents/${id}/reprocess`, { method: "POST" }); toast("Reprocessing started", "ok"); await loadDocs(); select(id, true); }
      catch (e) { toast(e.message, "error"); }
    });
    $("deleteBtn")?.addEventListener("click", async () => {
      if (!confirm(`Delete “${d.title}”? It will be removed from the knowledge base and the AI will no longer use it.`)) return;
      try {
        await api(`/api/documents/${id}`, { method: "DELETE" });
        toast("Document deleted", "ok"); selectedId = null; resetPreview(); await loadDocs();
      } catch (e) { toast(e.message, "error"); }
    });
    icons();
  }

  function resetPreview() {
    $("previewPanel").dataset.status = "";
    $("previewPanel").innerHTML = `<div class="preview-empty"><i data-lucide="file-search" class="i"></i><h5 style="color:#3a3430">Select a document</h5><p>Choose a document from the list to preview it, read the extracted text and ask the AI about it.</p></div>`;
    icons();
  }

  function askAboutDocument(d) {
    sessionStorage.setItem(KEYS.docCtx, JSON.stringify({ id: d.id, title: d.title }));
    sessionStorage.removeItem(KEYS.conv);      // fresh conversation scoped to this document
    sessionStorage.removeItem(KEYS.pending);
    location.href = "chatbot.html";
  }

  // ------------------------------------------------------------------ boot
  let debounce;
  $("searchInput").addEventListener("input", (e) => {
    clearTimeout(debounce);
    debounce = setTimeout(() => { query = e.target.value.trim(); refreshView(); }, 300);
  });

  document.addEventListener("campusai:ready", async () => {
    const sync = () => { $("adminLink").hidden = !isAdmin(); renderUploadSection(); renderList(); if (selectedId) select(selectedId, true); };
    CampusAI.onAuthChange(sync);
    $("adminLink").hidden = !isAdmin();
    renderUploadSection();
    if (params.get("category") && state.categories.includes(params.get("category"))) category = params.get("category");
    await loadDocs();
    const want = parseInt(params.get("doc"), 10);
    if (want) {
      if (allDocs.some((d) => d.id === want)) { category = ""; await refreshView(); select(want); }
      else toast("That document no longer exists.", "error");
    }
  });
})();
