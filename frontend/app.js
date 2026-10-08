/* =========================================================
   MeetMind Frontend — Optimized Vanilla JavaScript
   ========================================================= */

"use strict";

/* ================= CONFIGURATION & CONSTANTS ================= */

const MAX_FILE_SIZE = 100 * 1024 * 1024; // 100 MB
const ALLOWED_EXTENSIONS = new Set([".mp3", ".wav", ".m4a"]);
const VALID_PRIORITIES = new Set(["HIGH", "LOW"]);

/* ================= STATE ================= */

const state = {
    file: null,
    analysis: null,
    analyzing: false,
    controller: null,
    timers: []
};

/* ================= DOM ELEMENTS ================= */

const $ = id => document.getElementById(id);

const uploadScreen = $("upload-screen");
const loadingScreen = $("loading-screen");
const resultsScreen = $("results-screen");
const errorScreen = $("error-screen");

const dropZone = $("drop-zone");
const fileInput = $("file-input");
const browseBtn = $("browse-btn");

const fileCard = $("file-card");
const fileName = $("file-name");
const fileSize = $("file-size");
const removeBtn = $("remove-btn");

const analyzeBtn = $("analyze-btn");
const uploadError = $("upload-error");
const uploadErrorText = uploadError?.querySelector("p");

const newAnalysisBtn = $("new-analysis-btn");
const errorNewBtn = $("error-new-btn");
const retryBtn = $("retry-btn");

const transcriptToggle = $("transcript-toggle");
const transcriptContent = $("transcript-content");
const transcriptText = $("transcript-text");

const processingSteps = [
    $("step-transcribing"),
    $("step-analyzing"),
    $("step-report")
];

const screens = [
    uploadScreen,
    loadingScreen,
    resultsScreen,
    errorScreen
];

/* ================= SCREEN MANAGEMENT ================= */

function showScreen(screen) {
    screens.forEach(item => {
        if (!item) return;
        item.classList.add("hidden");
        item.classList.remove("active");
    });

    if (screen) {
        screen.classList.remove("hidden");
        screen.classList.add("active");
    }

    window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ================= TIMER & CLEANUP MANAGEMENT ================= */

function clearTimers() {
    state.timers.forEach(clearTimeout);
    state.timers = [];
}

/* ================= ERROR HANDLING ================= */

function showUploadError(message) {
    if (uploadErrorText) {
        uploadErrorText.textContent = message;
    }
    uploadError?.classList.remove("hidden");
}

function clearUploadError() {
    uploadError?.classList.add("hidden");
    if (uploadErrorText) {
        uploadErrorText.textContent = "";
    }
}

function showAnalysisError(message) {
    const el = $("error-message");
    if (el) {
        el.textContent = message || "We couldn't analyze this meeting.";
    }
    showScreen(errorScreen);
}

/* ================= FILE VALIDATION & HELPERS ================= */

function isAllowedFile(file) {
    if (!file?.name) return false;
    const lastDot = file.name.lastIndexOf(".");
    return lastDot !== -1 && ALLOWED_EXTENSIONS.has(file.name.slice(lastDot).toLowerCase());
}

function formatFileSize(bytes) {
    if (typeof bytes !== "number" || Number.isNaN(bytes)) return "0 B";
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function handleFile(file) {
    clearUploadError();
    if (!file) return;

    if (!isAllowedFile(file)) {
        showUploadError("Unsupported file type. Please upload MP3, WAV, or M4A.");
        return;
    }

    if (file.size > MAX_FILE_SIZE) {
        showUploadError("File is too large. Maximum allowed size is 100 MB.");
        return;
    }

    state.file = file;
    if (fileName) fileName.textContent = file.name;
    if (fileSize) fileSize.textContent = formatFileSize(file.size);

    fileCard?.classList.remove("hidden");
    if (analyzeBtn) analyzeBtn.disabled = false;
    if (dropZone) dropZone.style.display = "none";
}

function resetUpload() {
    state.file = null;

    if (state.controller) {
        state.controller.abort();
        state.controller = null;
    }

    clearTimers();

    if (fileInput) fileInput.value = "";
    fileCard?.classList.add("hidden");
    if (analyzeBtn) analyzeBtn.disabled = true;
    if (dropZone) dropZone.style.display = "flex";

    clearUploadError();
}

/* ================= PROCESSING STEP ANIMATION ================= */

function setProcessingStep(step) {
    processingSteps.forEach((element, index) => {
        if (!element) return;
        const indicator = element.querySelector(".step-indicator");
        element.classList.remove("active", "completed");

        if (index < step) {
            element.classList.add("completed");
            if (indicator) indicator.textContent = "✓";
        } else if (index === step) {
            element.classList.add("active");
            if (indicator) indicator.textContent = String(index + 2);
        } else {
            if (indicator) indicator.textContent = String(index + 2);
        }
    });
}

/* ================= API / ANALYSIS WORKFLOW ================= */

async function parseApiError(response) {
    const fallback = "The server could not analyze the meeting.";
    try {
        const data = await response.json();
        return data?.detail || data?.error || fallback;
    } catch {
        return fallback;
    }
}

async function analyzeMeeting() {
    if (!state.file || state.analyzing) return;

    state.analyzing = true;
    if (analyzeBtn) analyzeBtn.disabled = true;

    clearTimers();
    showScreen(loadingScreen);
    setProcessingStep(0);

    const formData = new FormData();
    formData.append("audio", state.file);

    state.controller = new AbortController();

    try {
        const fetchPromise = fetch("/api/analyze", {
            method: "POST",
            body: formData,
            signal: state.controller.signal
        });

        // Stage animation triggers
        state.timers.push(
            setTimeout(() => setProcessingStep(1), 900),
            setTimeout(() => setProcessingStep(2), 2200)
        );

        const response = await fetchPromise;

        if (!response.ok) {
            throw new Error(await parseApiError(response));
        }

        const data = await response.json();
        setProcessingStep(3);
        state.analysis = data;

        state.timers.push(
            setTimeout(() => {
                renderResults(data);
                showScreen(resultsScreen);
            }, 400)
        );
    } catch (error) {
        if (error.name === "AbortError") return;
        console.error("MeetMind analysis error:", error);
        showAnalysisError(error.message);
    } finally {
        state.analyzing = false;
        if (analyzeBtn) analyzeBtn.disabled = !state.file;
        state.controller = null;
    }
}

/* ================= RESULT RENDERING UTILITIES ================= */

function appendText(parent, tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    el.textContent = text ?? "";
    parent.appendChild(el);
    return el;
}

function getText(value) {
    if (value == null) return "";
    if (typeof value === "string" || typeof value === "number") return String(value);
    if (typeof value === "object") {
        return value.text || value.topic || value.question || value.title || value.name || JSON.stringify(value);
    }
    return String(value);
}

function normalizePriority(value) {
    const p = String(value || "MEDIUM").toUpperCase();
    return VALID_PRIORITIES.has(p) ? p : "MEDIUM";
}

function formatLabel(value) {
    return String(value || "")
        .replace(/_/g, " ")
        .replace(/\b\w/g, c => c.toUpperCase());
}

function formatDuration(seconds) {
    if (seconds == null || Number.isNaN(Number(seconds))) return "—";
    const total = Math.max(0, Math.round(Number(seconds)));
    const minutes = Math.floor(total / 60);
    const remaining = total % 60;
    if (minutes === 0) return `${remaining}s`;
    return `${minutes}m ${String(remaining).padStart(2, "0")}s`;
}

/* ================= DATA-DRIVEN SECTION RENDERER ================= */

function renderSectionList({ container, emptyEl, countEl, items, createItemNode }) {
    if (!container) return;
    const list = Array.isArray(items) ? items : [];

    if (countEl) countEl.textContent = String(list.length);
    emptyEl?.classList.toggle("hidden", list.length > 0);

    if (list.length === 0) {
        container.replaceChildren();
        return;
    }

    const fragment = document.createDocumentFragment();
    for (let i = 0; i < list.length; i++) {
        const node = createItemNode(list[i], i);
        if (node) fragment.appendChild(node);
    }
    container.replaceChildren(fragment);
}

/* ================= SECTION-SPECIFIC RENDERERS ================= */

function renderHeadline(headline) {
    const section = $("headline-section");
    const el = $("result-headline");
    if (!headline) {
        section?.classList.add("hidden");
        return;
    }
    if (el) el.textContent = headline;
    section?.classList.remove("hidden");
}

function renderSummary(summary) {
    const container = $("summary-content");
    if (!container) return;

    if (!summary) {
        container.replaceChildren();
        appendText(container, "p", "", "No summary was generated.");
        return;
    }

    const fragment = document.createDocumentFragment();
    String(summary)
        .split(/\n+/)
        .map(t => t.trim())
        .filter(Boolean)
        .forEach(paragraphText => {
            const p = document.createElement("p");
            p.textContent = paragraphText;
            fragment.appendChild(p);
        });

    container.replaceChildren(fragment);
}

function renderProcessing(timing, backends) {
    const totalEl = $("info-total");
    if (totalEl) {
        totalEl.textContent = timing?.total_seconds != null
            ? `${Number(timing.total_seconds).toFixed(1)}s`
            : "Completed";
    }

    const transcribeEl = $("info-transcription");
    if (transcribeEl) {
        transcribeEl.textContent = timing?.transcribe_seconds != null
            ? `${Number(timing.transcribe_seconds).toFixed(1)}s`
            : "Completed";
    }

    const analysisEl = $("info-analysis");
    if (analysisEl) {
        analysisEl.textContent = timing?.summarize_seconds != null
            ? `${Number(timing.summarize_seconds).toFixed(1)}s`
            : "Completed";
    }

    const backendsList = $("backends-list");
    if (backendsList && backends && typeof backends === "object") {
        const fragment = document.createDocumentFragment();
        Object.entries(backends).forEach(([key, value]) => {
            const row = document.createElement("div");
            row.className = "backend-row";
            appendText(row, "span", "", formatLabel(key));
            appendText(row, "strong", "", String(value));
            fragment.appendChild(row);
        });
        backendsList.replaceChildren(fragment);
    }
}

function renderResults(data = {}) {
    const filenameEl = $("result-filename");
    if (filenameEl) filenameEl.textContent = data.filename || state.file?.name || "Unknown";

    const durationEl = $("result-duration");
    if (durationEl) durationEl.textContent = formatDuration(data.audio_duration_seconds);

    const languageEl = $("result-language");
    if (languageEl) languageEl.textContent = data.language || "Unknown";

    renderHeadline(data.headline);
    renderSummary(data.summary);

    renderSectionList({
        container: $("key-points"),
        emptyEl: $("keypoints-empty"),
        countEl: $("keypoints-count"),
        items: data.key_points,
        createItemNode: item => {
            const row = document.createElement("div");
            row.className = "numbered-item";
            row.textContent = getText(item);
            return row;
        }
    });

    renderSectionList({
        container: $("decisions"),
        emptyEl: $("decisions-empty"),
        countEl: $("decisions-count"),
        items: data.decisions,
        createItemNode: item => {
            const card = document.createElement("div");
            card.className = "decision-card";
            appendText(card, "div", "decision-title", item?.decision || item?.title || item?.text || getText(item));
            if (item?.reason) {
                appendText(card, "div", "decision-detail", `Reason: ${item.reason}`);
            }
            if (item?.evidence) {
                appendText(card, "div", "decision-evidence", `Evidence: ${item.evidence}`);
            }
            return card;
        }
    });

    renderSectionList({
        container: $("action-items"),
        emptyEl: $("actions-empty"),
        countEl: $("actions-count"),
        items: data.action_items,
        createItemNode: item => {
            const card = document.createElement("div");
            card.className = "action-card";

            const top = document.createElement("div");
            top.className = "action-top";
            appendText(top, "div", "action-task", item?.task || item?.action || item?.title || getText(item));

            const priority = normalizePriority(item?.priority);
            appendText(top, "span", `priority priority-${priority.toLowerCase()}`, priority);
            card.appendChild(top);

            const meta = document.createElement("div");
            meta.className = "action-meta";
            appendText(meta, "span", "", `Owner: ${item?.owner || "Owner not specified"}`);
            appendText(meta, "span", "", `Deadline: ${item?.deadline || "No deadline"}`);
            card.appendChild(meta);

            if (item?.evidence) {
                appendText(card, "div", "action-evidence", `Evidence: ${item.evidence}`);
            }
            return card;
        }
    });

    renderSectionList({
        container: $("topics"),
        emptyEl: $("topics-empty"),
        items: data.topics,
        createItemNode: item => {
            const chip = document.createElement("span");
            chip.className = "topic-chip";
            chip.textContent = getText(item);
            return chip;
        }
    });

    renderSectionList({
        container: $("questions"),
        emptyEl: $("questions-empty"),
        countEl: $("questions-count"),
        items: data.open_questions,
        createItemNode: item => {
            const q = document.createElement("div");
            q.className = "question-item";
            q.textContent = getText(item);
            return q;
        }
    });

    if (transcriptText) {
        transcriptText.textContent = data.transcript || "No transcript available.";
    }

    renderProcessing(data.timing, data.backends);
}

/* ================= WORKFLOW & NAVIGATION ================= */

function startNewAnalysis() {
    state.analysis = null;
    state.analyzing = false;
    resetUpload();
    showScreen(uploadScreen);
}

/* ================= EVENT LISTENERS ================= */

browseBtn?.addEventListener("click", () => fileInput?.click());

fileInput?.addEventListener("change", event => {
    handleFile(event.target.files?.[0]);
});

if (dropZone) {
    ["dragenter", "dragover"].forEach(eventName => {
        dropZone.addEventListener(eventName, event => {
            event.preventDefault();
            dropZone.classList.add("dragging");
        });
    });

    ["dragleave", "drop"].forEach(eventName => {
        dropZone.addEventListener(eventName, event => {
            event.preventDefault();
            dropZone.classList.remove("dragging");
        });
    });

    dropZone.addEventListener("drop", event => {
        handleFile(event.dataTransfer?.files?.[0]);
    });
}

removeBtn?.addEventListener("click", resetUpload);
analyzeBtn?.addEventListener("click", analyzeMeeting);

transcriptToggle?.addEventListener("click", () => {
    if (!transcriptContent) return;
    const isHidden = transcriptContent.classList.contains("hidden");
    transcriptContent.classList.toggle("hidden");
    transcriptToggle.classList.toggle("open", isHidden);
});

newAnalysisBtn?.addEventListener("click", startNewAnalysis);
errorNewBtn?.addEventListener("click", startNewAnalysis);

retryBtn?.addEventListener("click", () => {
    if (state.file) {
        analyzeMeeting();
    } else {
        startNewAnalysis();
    }
});