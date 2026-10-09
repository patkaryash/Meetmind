/* =========================================================
   MeetMind — meeting intelligence workspace (vanilla JS)
   Flow: upload audio → POST /api/analyze → render report.
   No build step. No fake data: every field comes from the
   backend response or stays in its quiet empty state.
   ========================================================= */

"use strict";

/* ================= CONSTANTS ================= */

const MAX_FILE_SIZE = 100 * 1024 * 1024; // 100 MB — mirrors app/config.py
const ALLOWED_EXTENSIONS = new Set([".mp3", ".wav", ".m4a"]);

const STATUS_MESSAGES = [
    "Transcribing the recording…",
    "Extracting key discussion points…",
    "Identifying decisions and action items…",
    "Preparing your meeting report…"
];

/* ================= STATE ================= */

const state = {
    file: null,
    analysis: null,
    analyzing: false,
    analyzedAt: null,
    controller: null,
    timers: []
};

/* ================= DOM ================= */

const $ = id => document.getElementById(id);

const views = {
    upload: $("view-upload"),
    processing: $("view-processing"),
    results: $("view-results"),
    error: $("view-error")
};

const topbarNewBtn = $("new-analysis-btn");
const sideNewBtn = $("side-new-btn");
const sideNav = $("side-nav");
const topbarContext = $("topbar-context");
const backendStatus = $("backend-status");
const backendStatusText = $("backend-status-text");

const dropzone = $("dropzone");
const fileInput = $("file-input");
const browseBtn = $("browse-btn");
const fileRow = $("file-row");
const fileWaveWrap = $("file-wave-wrap");
const fileName = $("file-name");
const fileMeta = $("file-meta");
const fileExt = $("file-ext");
const removeBtn = $("remove-btn");
const analyzeBtn = $("analyze-btn");
const uploadError = $("upload-error");

const procFilename = $("proc-filename");
const procStatus = $("proc-status");
const steps = [$("step-transcribe"), $("step-understand"), $("step-structure")];

/* ================= VIEW SWITCHING ================= */

const VIEW_TITLES = {
    upload: "New analysis",
    processing: "Analyzing meeting",
    results: "Meeting analysis",
    error: "Analysis error"
};

function showView(view) {
    Object.entries(views).forEach(([name, el]) => {
        if (!el) return;
        const active = el === view;
        el.classList.toggle("hidden", !active);
        if (active && VIEW_TITLES[name] && topbarContext) {
            topbarContext.textContent = VIEW_TITLES[name];
        }
    });
    window.scrollTo({ top: 0 });
    // “New analysis” belongs everywhere except the upload screen,
    // which already is a fresh analysis.
    const onUpload = view === views.upload;
    if (topbarNewBtn) topbarNewBtn.classList.toggle("hidden", onUpload);
    // Section index exists only alongside a rendered report.
    if (sideNav) sideNav.classList.toggle("hidden", view !== views.results);
}

function clearTimers() {
    state.timers.forEach(clearTimeout);
    state.timers = [];
}

/* ================= BACKEND STATUS ================= */

async function checkBackend() {
    if (!backendStatusText) return;
    try {
        const res = await fetch("/api/health");
        if (!res.ok) throw new Error("unhealthy");
        const data = await res.json();
        backendStatusText.textContent = data.gemini_configured ? "Ready" : "No AI key";
        backendStatus.classList.remove("is-error");
    } catch {
        backendStatusText.textContent = "Offline";
        backendStatus.classList.add("is-error");
    }
}

/* ================= FILE HANDLING ================= */

function extOf(name) {
    const i = name.lastIndexOf(".");
    return i === -1 ? "" : name.slice(i).toLowerCase();
}

function formatBytes(bytes) {
    if (typeof bytes !== "number" || Number.isNaN(bytes)) return "—";
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function showUploadError(message) {
    if (!uploadError) return;
    uploadError.textContent = message;
    uploadError.classList.remove("hidden");
}

function clearUploadError() {
    if (!uploadError) return;
    uploadError.textContent = "";
    uploadError.classList.add("hidden");
}

function handleFile(file) {
    clearUploadError();
    if (!file) return;

    if (!ALLOWED_EXTENSIONS.has(extOf(file.name || ""))) {
        showUploadError("Unsupported file type. Please upload MP3, WAV, or M4A.");
        return;
    }
    if (file.size > MAX_FILE_SIZE) {
        showUploadError("File is too large. Maximum allowed size is 100 MB.");
        return;
    }

    state.file = file;
    fileName.textContent = file.name;
    fileExt.textContent = extOf(file.name).replace(".", "").toUpperCase() || "AUDIO";
    fileMeta.textContent = formatBytes(file.size);
    fileRow.classList.remove("hidden");
    fileWaveWrap?.classList.remove("hidden");
    dropzone.classList.add("hidden");
    analyzeBtn.disabled = false;
}

function resetUpload() {
    state.file = null;
    if (state.controller) {
        state.controller.abort();
        state.controller = null;
    }
    clearTimers();
    if (fileInput) fileInput.value = "";
    fileRow.classList.add("hidden");
    fileWaveWrap?.classList.add("hidden");
    dropzone.classList.remove("hidden");
    analyzeBtn.disabled = true;
    clearUploadError();
}

/* ================= PROCESSING ================= */

function setStep(index, mode) {
    // mode: "active" | "done"
    const el = steps[index];
    if (!el) return;
    el.classList.remove("is-active", "is-done");
    el.classList.add(mode === "done" ? "is-done" : "is-active");
    el.querySelector(".step-state").textContent = mode === "done" ? "Complete" : "Processing";
}

function resetSteps() {
    steps.forEach(el => {
        if (!el) return;
        el.classList.remove("is-active", "is-done");
        el.querySelector(".step-state").textContent = "Waiting";
    });
}

async function parseApiError(response) {
    try {
        const data = await response.json();
        return data.detail || data.error || "The server could not analyze the meeting.";
    } catch {
        return "The server could not analyze the meeting.";
    }
}

async function analyzeMeeting() {
    if (!state.file || state.analyzing) return;
    state.analyzing = true;
    analyzeBtn.disabled = true;
    clearTimers();

    backendStatus.classList.add("is-busy");
    procFilename.textContent = state.file.name;
    resetSteps();
    setStep(0, "active");
    procStatus.textContent = STATUS_MESSAGES[0];
    showView(views.processing);

    // Cosmetic stage progression; completion is driven by the real response.
    state.timers.push(
        setTimeout(() => { setStep(0, "done"); setStep(1, "active"); procStatus.textContent = STATUS_MESSAGES[1]; }, 1200),
        setTimeout(() => { procStatus.textContent = STATUS_MESSAGES[2]; }, 4000),
        setTimeout(() => { setStep(1, "done"); setStep(2, "active"); procStatus.textContent = STATUS_MESSAGES[3]; }, 9000)
    );

    const formData = new FormData();
    formData.append("audio", state.file);
    state.controller = new AbortController();

    try {
        const response = await fetch("/api/analyze", {
            method: "POST",
            body: formData,
            signal: state.controller.signal
        });
        if (!response.ok) throw new Error(await parseApiError(response));

        const data = await response.json();
        state.analysis = data;
        state.analyzedAt = new Date();
        setStep(0, "done"); setStep(1, "done"); setStep(2, "done");
        renderResults(data);
        showView(views.results);
    } catch (error) {
        if (error.name === "AbortError") return;
        console.error("MeetMind analysis error:", error);
        $("error-message").textContent = error.message || "We couldn't analyze this meeting.";
        showView(views.error);
    } finally {
        state.analyzing = false;
        state.controller = null;
        backendStatus.classList.remove("is-busy");
        analyzeBtn.disabled = !state.file;
    }
}

/* ================= FORMATTERS ================= */

function textOf(value) {
    if (value == null) return "";
    if (typeof value === "string" || typeof value === "number") return String(value);
    if (typeof value === "object") {
        return value.text || value.title || value.question || value.topic || value.name || "";
    }
    return String(value);
}

function formatClock(totalSeconds) {
    const s = Number(totalSeconds);
    if (!Number.isFinite(s) || s < 0) return "—";
    const m = Math.floor(s / 60);
    const r = Math.floor(s % 60);
    return `${m}:${String(r).padStart(2, "0")}`;
}

function formatSecs(value) {
    const n = Number(value);
    return Number.isFinite(n) ? `${n.toFixed(1)}s` : "—";
}

function analyzedAgo() {
    if (!state.analyzedAt) return "just now";
    const s = Math.round((Date.now() - state.analyzedAt.getTime()) / 1000);
    if (s < 60) return "just now";
    const m = Math.floor(s / 60);
    return m === 1 ? "1 minute ago" : `${m} minutes ago`;
}

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
}

/* ================= EVIDENCE ================= */

function evidenceNode(quote) {
    if (!quote || !String(quote).trim()) return null;
    const details = el("details", "evidence");
    const summary = el("summary", null, "Evidence");
    const quoteEl = el("blockquote", null, String(quote).trim());
    details.append(summary, quoteEl);
    return details;
}

/* ================= SECTION RENDERERS ================= */

function setCount(id, n) {
    const node = $(id);
    if (node) node.textContent = String(n).padStart(2, "0");
}

function renderSummary(summary) {
    const body = $("summary-body");
    body.replaceChildren();
    const paras = String(summary || "").split(/\n+/).map(t => t.trim()).filter(Boolean);
    if (!paras.length) {
        body.append(el("p", null, "No summary was generated for this meeting."));
        return;
    }
    paras.forEach(p => body.append(el("p", null, p)));
}

function renderKeyPoints(items) {
    const list = $("keypoints-list");
    list.replaceChildren();
    const arr = Array.isArray(items) ? items : [];
    setCount("keypoints-count", arr.length);
    $("keypoints-empty").classList.toggle("hidden", arr.length > 0);
    arr.forEach((item, i) => {
        const li = el("li", "keypoint");
        li.append(
            el("span", "keypoint-index", String(i + 1).padStart(2, "0")),
            el("p", null, textOf(item))
        );
        list.append(li);
    });
}

function renderDecisions(items) {
    const list = $("decisions-list");
    list.replaceChildren();
    const arr = Array.isArray(items) ? items : [];
    setCount("decisions-count", arr.length);
    $("decisions-empty").classList.toggle("hidden", arr.length > 0);
    arr.forEach(item => {
        const text = item && typeof item === "object"
            ? (item.decision || item.title || item.text || "")
            : textOf(item);
        if (!String(text).trim()) return;
        const li = el("li", "decision");
        const tick = el("span", "decision-tick", "✓");
        tick.setAttribute("aria-hidden", "true");
        const wrap = el("div");
        wrap.append(el("p", "decision-title", String(text).trim()));
        if (item && typeof item === "object" && item.reason) {
            wrap.append(el("p", "decision-reason", String(item.reason).trim()));
        }
        const ev = item && typeof item === "object" ? evidenceNode(item.evidence) : null;
        if (ev) wrap.append(ev);
        li.append(tick, wrap);
        list.append(li);
    });
}

function renderActions(items) {
    const body = $("actions-body");
    body.replaceChildren();
    const arr = Array.isArray(items) ? items : [];
    setCount("actions-count", arr.length);
    $("actions-empty").classList.toggle("hidden", arr.length > 0);
    document.querySelector(".table-wrap").classList.toggle("hidden", arr.length === 0);
    arr.forEach(item => {
        const task = item && typeof item === "object"
            ? (item.task || item.action || item.title || "") : textOf(item);
        if (!String(task).trim()) return;
        const owner = item && typeof item === "object" && item.owner ? String(item.owner) : "";
        const due = item && typeof item === "object" && item.deadline ? String(item.deadline) : "";
        const prio = item && typeof item === "object" && item.priority
            ? String(item.priority).toLowerCase() : "medium";

        const tr = document.createElement("tr");
        const taskTd = el("td", "col-task task-cell");
        taskTd.append(el("strong", null, String(task).trim()));
        const ev = item && typeof item === "object" ? evidenceNode(item.evidence) : null;
        if (ev) taskTd.append(ev);
        tr.append(
            taskTd,
            el("td", "cell-secondary", owner || "—"),
            el("td", "cell-secondary", due || "—"),
            (() => {
                const td = el("td");
                const pill = el("span", `priority priority-${prio}`,
                    prio.charAt(0).toUpperCase() + prio.slice(1));
                td.append(pill);
                return td;
            })()
        );
        if (!owner) tr.children[1].classList.add("empty-cell");
        if (!due) tr.children[2].classList.add("empty-cell");
        body.append(tr);
    });
}

function renderTopics(items) {
    const arr = (Array.isArray(items) ? items : []).map(textOf).filter(Boolean);
    // Inline theme line under the summary.
    const line = $("report-topics");
    const inline = $("topics-inline");
    inline.replaceChildren();
    line.classList.toggle("hidden", arr.length === 0);
    arr.slice(0, 6).forEach(t => inline.append(el("span", "topic-inline-item", t)));
    // Rail chips.
    const rail = $("rail-topics");
    rail.replaceChildren();
    $("rail-topics-empty").classList.toggle("hidden", arr.length > 0);
    arr.slice(0, 12).forEach(t => rail.append(el("span", "chip", t)));
}

function renderQuestions(items) {
    const list = $("questions-list");
    list.replaceChildren();
    const arr = (Array.isArray(items) ? items : []).map(textOf).filter(Boolean);
    setCount("questions-count", arr.length);
    $("questions-empty").classList.toggle("hidden", arr.length > 0);
    arr.forEach((q, i) => {
        const li = el("li");
        li.append(
            el("span", "q-index", String(i + 1).padStart(2, "0")),
            el("span", null, q)
        );
        list.append(li);
    });
}

let transcriptParas = [];

function renderTranscript(transcript) {
    const body = $("transcript-body");
    body.replaceChildren();
    transcriptParas = String(transcript || "")
        .split(/\n{2,}|\r\n\r\n/)
        .map(t => t.trim())
        .filter(Boolean);
    if (!transcriptParas.length && (transcript || "").trim()) {
        transcriptParas = [(transcript || "").trim()];
    }
    $("transcript-hint").textContent = transcriptParas.length
        ? `Show · ${transcriptParas.length} passages` : "Show";
    paintTranscript("");
    collapseTranscript();
}

function paintTranscript(query) {
    const body = $("transcript-body");
    body.replaceChildren();
    const q = (query || "").trim().toLowerCase();
    const frag = document.createDocumentFragment();
    let shown = 0;
    transcriptParas.forEach(p => {
        if (q && !p.toLowerCase().includes(q)) return;
        shown++;
        const para = el("p");
        if (q) {
            // Highlight matches without injecting HTML.
            const lower = p.toLowerCase();
            let i = 0, idx;
            while ((idx = lower.indexOf(q, i)) !== -1) {
                para.append(document.createTextNode(p.slice(i, idx)));
                para.append(el("mark", null, p.slice(idx, idx + q.length)));
                i = idx + q.length;
            }
            para.append(document.createTextNode(p.slice(i)));
        } else {
            para.textContent = p;
        }
        frag.append(para);
    });
    if (!shown) frag.append(el("p", "transcript-empty", "No passages match this filter."));
    body.append(frag);
}

function collapseTranscript() {
    $("transcript-panel").classList.add("hidden");
    $("transcript-toggle").setAttribute("aria-expanded", "false");
    $("transcript-hint").textContent = $("transcript-hint").textContent.replace("Hide", "Show");
}

function renderMeta(data) {
    const name = data.filename || state.file?.name || "Unknown file";
    const dur = formatClock(data.audio_duration_seconds);
    const lang = data.language || "Unknown";
    $("report-title").textContent = data.headline || "Meeting analysis";
    $("meta-file").textContent = name;
    $("meta-duration").textContent = dur;
    $("meta-language").textContent = lang;
    $("meta-analyzed").textContent = `Analyzed ${analyzedAgo()}`;
    $("rail-file").textContent = name;
    $("rail-file").title = name;
    $("rail-duration").textContent = dur;
    $("rail-language").textContent = lang;

    const t = data.timing || {};
    $("rail-transcribe").textContent = formatSecs(t.transcribe_seconds);
    $("rail-analysis").textContent = formatSecs(t.summarize_seconds);
    $("rail-total").textContent = formatSecs(t.total_seconds);

    const b = data.backends || {};
    $("rail-stt").textContent = b.speech_to_text || "Whisper";
    $("rail-model").textContent = b.summarization || "Gemini";
}

function renderResults(data = {}) {
    renderMeta(data);
    renderSummary(data.summary);
    renderKeyPoints(data.key_points);
    renderDecisions(data.decisions);
    renderActions(data.action_items);
    renderTopics(data.topics);
    renderQuestions(data.open_questions);
    renderTranscript(data.transcript);
}

/* ================= WAVEFORM MOTIF ================= */

function buildWaveform(container, bars, maxHeight) {
    // Abstract audio motif, not data: a fixed deterministic pattern so it
    // renders identically on every load and never implies analysis.
    if (!container || container.childElementCount > 0) return;
    let seed = 7;
    const rand = () => {
        seed = (seed * 16807) % 2147483647;
        return seed / 2147483647;
    };
    const frag = document.createDocumentFragment();
    for (let i = 0; i < bars; i++) {
        const bar = document.createElement("i");
        const envelope = Math.sin((i / bars) * Math.PI); // swell in the middle
        const h = Math.max(4, Math.round((0.25 + 0.75 * rand()) * envelope * maxHeight));
        bar.style.height = `${h}px`;
        frag.append(bar);
    }
    container.append(frag);
}

/* ================= REPORT SECTION NAV ================= */

function initSectionNav() {
    const links = Array.from(document.querySelectorAll("#side-nav a[data-section]"));
    if (!links.length || !("IntersectionObserver" in window)) return;
    const byId = new Map(links.map(a => [a.dataset.section, a]));
    links.forEach(a => a.addEventListener("click", () => {
        links.forEach(other => other.classList.remove("is-active"));
        a.classList.add("is-active");
    }));
    const observer = new IntersectionObserver(entries => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            links.forEach(other => other.classList.toggle("is-active", other === byId.get(entry.target.id)));
        });
    }, { rootMargin: "-30% 0px -55% 0px" });
    byId.forEach((_, id) => {
        const section = document.getElementById(id);
        if (section) observer.observe(section);
    });
}

/* ================= NAV / EVENTS ================= */

function startNewAnalysis() {
    state.analysis = null;
    state.analyzing = false;
    resetUpload();
    resetSteps();
    showView(views.upload);
}

browseBtn?.addEventListener("click", e => { e.stopPropagation(); fileInput?.click(); });
dropzone?.addEventListener("click", e => {
    if (e.target.closest("button") || e.target.closest("input")) return;
    fileInput?.click();
});
dropzone?.addEventListener("keydown", e => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput?.click(); }
});
fileInput?.addEventListener("change", e => handleFile(e.target.files?.[0]));

["dragenter", "dragover"].forEach(name =>
    dropzone?.addEventListener(name, e => { e.preventDefault(); dropzone.classList.add("is-dragover"); }));
["dragleave", "drop"].forEach(name =>
    dropzone?.addEventListener(name, e => { e.preventDefault(); dropzone.classList.remove("is-dragover"); }));
dropzone?.addEventListener("drop", e => handleFile(e.dataTransfer?.files?.[0]));

removeBtn?.addEventListener("click", resetUpload);
analyzeBtn?.addEventListener("click", analyzeMeeting);

$("transcript-toggle")?.addEventListener("click", () => {
    const panel = $("transcript-panel");
    panel.classList.toggle("hidden");
    const isOpen = !panel.classList.contains("hidden");
    $("transcript-toggle").setAttribute("aria-expanded", String(isOpen));
    const hint = $("transcript-hint");
    hint.textContent = isOpen
        ? hint.textContent.replace("Show", "Hide")
        : hint.textContent.replace("Hide", "Show");
});

$("transcript-search")?.addEventListener("input", e => paintTranscript(e.target.value));

$("summary-copy")?.addEventListener("click", async e => {
    const btn = e.currentTarget;
    const text = $("summary-body")?.innerText || "";
    if (!text.trim()) return;
    try {
        await navigator.clipboard.writeText(text);
        btn.textContent = "Copied";
        setTimeout(() => { btn.textContent = "Copy"; }, 1600);
    } catch {
        btn.textContent = "Copy failed";
        setTimeout(() => { btn.textContent = "Copy"; }, 1600);
    }
});

topbarNewBtn?.addEventListener("click", startNewAnalysis);
sideNewBtn?.addEventListener("click", startNewAnalysis);
$("error-new-btn")?.addEventListener("click", startNewAnalysis);
$("retry-btn")?.addEventListener("click", () => {
    if (state.file) analyzeMeeting();
    else startNewAnalysis();
});

buildWaveform($("waveform"), 56, 56);
buildWaveform($("file-wave"), 72, 28);
initSectionNav();
checkBackend();
