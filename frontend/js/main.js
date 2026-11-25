/* CampusAI – shared helpers (API, auth, toasts, icons) + welcome-page logic */
const CampusAI = (() => {
  const KEYS = {
    pending: "campusai_pending_question",
    docCtx: "campusai_doc_context",
    conv: "campusai_conversation",
    lang: "campusai_language",
  };
  const state = { user: null, categories: [], llmConfigured: true };
  const listeners = [];

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icons = () => { if (window.lucide) window.lucide.createIcons(); };

  async function api(path, opts = {}) {
    const o = { credentials: "same-origin", ...opts };
    if (o.body && !(o.body instanceof FormData)) {
      o.headers = { "Content-Type": "application/json", ...(o.headers || {}) };
      o.body = JSON.stringify(o.body);
    }
    let res;
    try { res = await fetch(path, o); }
    catch { throw new Error("Cannot reach the server. Is CampusAI running?"); }
    let data = {};
    try { data = await res.json(); } catch { /* non-JSON */ }
    if (!res.ok) { const e = new Error(data.error || `Request failed (${res.status})`); e.status = res.status; e.data = data; throw e; }
    return data;
  }

  function toast(msg, type = "") {
    let stack = document.querySelector(".toast-stack");
    if (!stack) { stack = document.createElement("div"); stack.className = "toast-stack"; document.body.appendChild(stack); }
    const t = document.createElement("div");
    t.className = `c-toast ${type}`; t.textContent = msg; stack.appendChild(t);
    setTimeout(() => t.remove(), 4200);
  }

  const fmtSize = (b) => b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(1)} KB` : `${(b / 1048576).toFixed(1)} MB`;
  const fmtDate = (s) => { if (!s) return ""; const d = new Date(s.replace(" ", "T") + "Z"); return isNaN(d) ? s : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }); };
  const initials = (n) => (n || "?").split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();

  // ---- auth ---------------------------------------------------------------
  const loginModalHTML = `
  <div class="modal fade" id="authModal" tabindex="-1" aria-hidden="true">
    <div class="modal-dialog modal-dialog-centered"><div class="modal-content c-modal">
      <div class="modal-header"><h5 class="modal-title" id="authTitle">Welcome back</h5><button class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div>
      <form class="modal-body" id="authForm" novalidate>
        <div class="mb-3" id="authNameWrap" hidden><label class="c-label">Full name</label><input class="c-input" id="authName" autocomplete="name"></div>
        <div class="mb-3"><label class="c-label">Email</label><input class="c-input" id="authEmail" type="email" autocomplete="email" required></div>
        <div class="mb-2"><label class="c-label">Password</label><input class="c-input" id="authPass" type="password" autocomplete="current-password" required></div>
        <div class="form-error mb-2" id="authError"></div>
        <button class="btn-grad w-100" id="authSubmit" type="submit">Log in</button>
        <p class="text-center mt-3 mb-0" style="font-size:.85rem;color:var(--muted)"><span id="authSwitchText">New here?</span> <button type="button" class="link-orange" id="authSwitch">Create an account</button></p>
      </form>
    </div></div>
  </div>`;
  let authMode = "login", authModal;

  function setAuthMode(mode) {
    authMode = mode;
    const reg = mode === "register";
    document.getElementById("authTitle").textContent = reg ? "Create your account" : "Welcome back";
    document.getElementById("authNameWrap").hidden = !reg;
    document.getElementById("authSubmit").textContent = reg ? "Sign up" : "Log in";
    document.getElementById("authSwitchText").textContent = reg ? "Already registered?" : "New here?";
    document.getElementById("authSwitch").textContent = reg ? "Log in" : "Create an account";
    document.getElementById("authError").textContent = "";
  }

  function openLogin(mode = "login") {
    if (!authModal) return;
    setAuthMode(mode);
    authModal.show();
    setTimeout(() => document.getElementById(mode === "register" ? "authName" : "authEmail").focus(), 300);
  }

  function initAuthModal() {
    document.body.insertAdjacentHTML("beforeend", loginModalHTML);
    authModal = new bootstrap.Modal(document.getElementById("authModal"));
    document.getElementById("authSwitch").onclick = () => setAuthMode(authMode === "login" ? "register" : "login");
    document.getElementById("authForm").onsubmit = async (e) => {
      e.preventDefault();
      const btn = document.getElementById("authSubmit"), err = document.getElementById("authError");
      btn.disabled = true; err.textContent = "";
      try {
        const body = { email: document.getElementById("authEmail").value, password: document.getElementById("authPass").value };
        if (authMode === "register") body.name = document.getElementById("authName").value;
        const data = await api(`/api/auth/${authMode}`, { method: "POST", body });
        state.user = data.user; authModal.hide();
        toast(`Signed in as ${data.user.name}`, "ok");
        listeners.forEach((fn) => fn(state.user));
      } catch (ex) { err.textContent = ex.message; }
      finally { btn.disabled = false; }
    };
  }

  async function logout() {
    await api("/api/auth/logout", { method: "POST" });
    state.user = null; sessionStorage.removeItem(KEYS.conv);
    listeners.forEach((fn) => fn(null));
    if (document.body.classList.contains("theme-admin")) location.href = "index.html";
  }

  /** Renders login button / user dropdown inside `el`. variant: "pill" (chat) | "nav" */
  function renderUserArea(el, variant = "nav") {
    if (!el) return;
    const u = state.user;
    if (!u) {
      el.innerHTML = variant === "pill"
        ? `<button class="profile-pill" data-act="login"><span class="avatar"><i data-lucide="user" class="i i-sm"></i></span><span class="nm">Log in</span></button>`
        : `<button class="btn-ghost" data-act="login"><i data-lucide="log-in" class="i i-sm"></i>Login</button>`;
    } else {
      el.innerHTML = `
        <div class="dropdown">
          <button class="profile-pill" data-bs-toggle="dropdown" aria-expanded="false"><span class="avatar">${esc(initials(u.name))}</span><span class="nm">${esc(u.name)}</span></button>
          <ul class="dropdown-menu dropdown-menu-end c-dropdown">
            <li class="dd-head"><b>${esc(u.name)}</b><small>${esc(u.email)} · ${esc(u.role)}</small></li>
            ${u.role === "admin" ? `<li><a class="dropdown-item" href="admin.html"><i data-lucide="layout-dashboard" class="i i-sm"></i> Admin dashboard</a></li>` : ""}
            <li><button class="dropdown-item" data-act="logout"><i data-lucide="log-out" class="i i-sm"></i> Log out</button></li>
          </ul>
        </div>`;
    }
    el.querySelector('[data-act="login"]')?.addEventListener("click", () => openLogin());
    el.querySelector('[data-act="logout"]')?.addEventListener("click", logout);
    icons();
  }

  async function loadMe() {
    try {
      const d = await api("/api/me");
      state.user = d.user; state.categories = d.categories; state.llmConfigured = d.llm_configured;
    } catch (e) { toast(e.message, "error"); }
    return state;
  }

  const onAuthChange = (fn) => listeners.push(fn);

  // ---- shared page chrome -------------------------------------------------
  function initParticles() {
    const cv = document.getElementById("particles");
    if (!cv) return;
    const ctx = cv.getContext("2d");
    let w, h, dots = [];
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    function resize() {
      w = cv.width = window.innerWidth; h = cv.height = window.innerHeight;
      const n = Math.min(90, Math.floor((w * h) / 18000));
      dots = Array.from({ length: n }, () => ({
        x: Math.random() * w, y: Math.random() * h, r: Math.random() * 1.6 + .4,
        vy: -(Math.random() * .35 + .08), vx: (Math.random() - .5) * .15, a: Math.random() * .6 + .2,
        t: Math.random() * Math.PI * 2,
      }));
    }
    function frame() {
      ctx.clearRect(0, 0, w, h);
      for (const d of dots) {
        d.x += d.vx; d.y += d.vy; d.t += .02;
        if (d.y < -5) { d.y = h + 5; d.x = Math.random() * w; }
        const alpha = d.a * (0.6 + 0.4 * Math.sin(d.t)) * Math.min(1, d.y / h + .25);
        ctx.beginPath(); ctx.arc(d.x, d.y, d.r, 0, 6.283);
        ctx.fillStyle = `rgba(255,${140 + (d.r * 40) | 0},80,${alpha})`;
        ctx.shadowColor = "rgba(255,113,56,.9)"; ctx.shadowBlur = 8; ctx.fill();
      }
      if (!reduce) requestAnimationFrame(frame);
    }
    resize(); frame(); window.addEventListener("resize", resize);
  }

  function initDocsNav() {
    const nav = document.querySelector(".top-nav");
    nav?.querySelector(".nav-toggle")?.addEventListener("click", () => nav.classList.toggle("open"));
  }

  function autoGrow(ta) {
    const fit = () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 180) + "px"; };
    ta.addEventListener("input", fit); fit();
  }

  async function boot() {
    initAuthModal();
    initParticles();
    initDocsNav();
    await loadMe();
    document.querySelectorAll("[data-user-area]").forEach((el) => {
      const render = () => renderUserArea(el, el.dataset.userArea);
      render(); onAuthChange(render);
    });
    document.querySelectorAll("[data-open-login]").forEach((b) => b.addEventListener("click", (e) => { e.preventDefault(); openLogin(); }));
    icons();
    document.dispatchEvent(new CustomEvent("campusai:ready"));
  }

  return { KEYS, state, api, toast, esc, icons, fmtSize, fmtDate, initials, openLogin, onAuthChange, renderUserArea, autoGrow, boot };
})();

/* ------------------------------ PAGE 1: welcome ---------------------------- */
document.addEventListener("DOMContentLoaded", () => {
  CampusAI.boot();
  if (!document.body.classList.contains("theme-orange")) return;

  const input = document.getElementById("heroInput"), send = document.getElementById("heroSend");
  CampusAI.autoGrow(input);
  const go = () => {
    const q = input.value.trim();
    if (!q) { CampusAI.toast("Type a question first, or press “Start Chatting”."); input.focus(); return; }
    sessionStorage.setItem(CampusAI.KEYS.pending, q);
    sessionStorage.removeItem(CampusAI.KEYS.conv);          // a typed question starts a fresh chat
    sessionStorage.removeItem(CampusAI.KEYS.docCtx);
    location.href = "chatbot.html";
  };
  send.addEventListener("click", go);
  input.addEventListener("input", () => { send.disabled = !input.value.trim(); });
  send.disabled = true;
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); go(); } });

  // feature cards act as shortcuts
  document.querySelectorAll("[data-card-link]").forEach((c) => c.addEventListener("click", () => { location.href = c.dataset.cardLink; }));
  // nav link smooth scrolling
  document.querySelectorAll('a[href^="#"]').forEach((a) => a.addEventListener("click", (e) => {
    const t = document.querySelector(a.getAttribute("href"));
    if (t) { e.preventDefault(); t.scrollIntoView({ behavior: "smooth" }); }
  }));
});
