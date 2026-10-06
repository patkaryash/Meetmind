/* MeetMind frontend — vanilla JS, no build step.
 * Workflow: upload audio → POST /api/analyze → render structured report.
 */
(() => {
  "use strict";

  // Mirrors app/config.py defaults (frontend cannot read env).
  const ALLOWED_EXTENSIONS = ["mp3", "wav", "m4a"];
  const MAX_UPLOAD_MB = 100;

  const STAGES = [
    { key: "upload", label: "Uploading" },
    { key: "transcribe", label: "Transcribing meeting" },
    { key: "analyze", label: "Analyzing transcript" },
    { key: "report", label: "Preparing meeting report" },
  ];

  const $ = (id) => document.getElementById(id);

  const dropzone = $("dropzone");
  const fileInput = $("file-input");
  const browseBtn = $("browse-btn");
  const fileChip = $("file-chip");
  const fileNameEl = $("file-name");
  const fileSizeEl = $("file-size");
  const removeBtn = $("remove-btn");
  const analyzeBtn = $("analyze-btn");
  const resetBtn = $("reset-btn");
  const statusEl = $("status");
  const statusTextEl = $("status-text");
  const statusStepsEl = $("status-steps");
  const statusElapsedEl = $("status-elapsed");
  const errorEl = $("error");
  const resultsEl = $("results");
  const headlineEl = $("report-headline");
  const metaStrip = $("meta-strip");
  const summaryTextEl = $("summary-text");
  const keyPointsListEl = $("keypoints-list");
  const decisionsListEl = $("decisions-list");
  const actionsListEl = $("actions-list");
  const topicsListEl = $("topics-list");
  const questionsListEl = $("questions-list");
  const keyPointsCountEl = $("keypoints-count");
  const decisionsCountEl = $("decisions-count");
  const actionsCountEl = $("actions-count");
  const questionsCountEl = $("questions-count");
  const transcriptTextEl = $("transcript-text");
  const transcriptCard = document.querySelector(".transcript-card");

  let selectedFile = null;
  let elapsedTimer = null;
  let stageTimer = null;

  // ---------- helpers ---------------------------------------------------- //

  function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function formatDuration(seconds) {
    const s = Math.max(0, Math.round(seconds || 0));
    const m = Math.floor(s / 60);
    return `${m}:${String(s % 60).padStart(2, "0")} min`;
  }

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = false;
  }

  function clearError() {
    errorEl.textContent = "";
    errorEl.hidden = true;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  // ---------- file selection --------------------------------------------- //

  function acceptFile(file) {
    clearError();
    if (!file) return;

    const ext = (file.name.split(".").pop() || "").toLowerCase();
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      showError(
        `Unsupported file type ".${ext}". Please upload an MP3, WAV or M4A recording.`
      );
      return;
    }
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      showError(
        `File is ${formatBytes(file.size)} — the limit is ${MAX_UPLOAD_MB} MB.`
      );
      return;
    }

    selectedFile = file;
    fileNameEl.textContent = file.name;
    fileSizeEl.textContent = formatBytes(file.size);
    fileChip.hidden = false;
    dropzone.classList.remove("dragging");
    analyzeBtn.disabled = false;
    resultsEl.hidden = true;
    statusEl.hidden = true;
  }

  function clearSelection() {
    selectedFile = null;
    fileInput.value = "";
    fileChip.hidden = true;
    dropzone.classList.remove("dragging");
    analyzeBtn.disabled = true;
    statusEl.hidden = true;
  }

  // ---------- loading ----------------------------------------------------- //

  function setStage(index) {
    const items = statusStepsEl.querySelectorAll("li");
    items.forEach((li, i) => {
      li.classList.toggle("done", i < index);
      li.classList.toggle("active", i === index);
    });
    if (STAGES[index]) statusTextEl.textContent = `${STAGES[index].label}…`;
  }

  function startLoading() {
    statusEl.hidden = false;
    resultsEl.hidden = true;
    analyzeBtn.disabled = true;
    let stage = 0;
    setStage(stage);
    const started = Date.now();
    statusElapsedEl.textContent = "0s";
    elapsedTimer = setInterval(() => {
      statusElapsedEl.textContent = `${Math.round((Date.now() - started) / 1000)}s`;
    }, 1000);
    // Backend is one POST (upload → transcribe → analyze), so advance the
    // visible stage on a timer to communicate progress honestly.
    stageTimer = setInterval(() => {
      if (stage < STAGES.length - 1) {
        stage += 1;
        setStage(stage);
      }
    }, 6000);
  }

  function stopLoading() {
    if (elapsedTimer) {
      clearInterval(elapsedTimer);
      elapsedTimer = null;
    }
    if (stageTimer) {
      clearInterval(stageTimer);
      stageTimer = null;
    }
    statusEl.hidden = true;
    analyzeBtn.disabled = !selectedFile;
  }

  // ---------- analyze ------------------------------------------------------ //

  async function analyze() {
    if (!selectedFile) return;
    clearError();
    startLoading();

    try {
      const form = new FormData();
      form.append("audio", selectedFile, selectedFile.name);

      const response = await fetch("/api/analyze", {
        method: "POST",
        body: form,
      });

      if (!response.ok) {
        let detail = `Analysis failed (HTTP ${response.status}).`;
        try {
          const data = await response.json();
          if (data && data.detail) detail = data.detail;
        } catch (_) {
          /* non-JSON error body — keep the generic message */
        }
        throw new Error(detail);
      }

      const data = await response.json();
      renderResults(data);
    } catch (err) {
      stopLoading();
      showError(
        err && err.message
          ? err.message
          : "Something went wrong while analyzing the meeting. Please try again."
      );
    }
  }

  // ---------- rendering ---------------------------------------------------- //

  function addMetaChip(label, value) {
    const chip = el("span", "meta-chip");
    chip.append(`${label}: `, Object.assign(el("strong"), { textContent: value }));
    metaStrip.appendChild(chip);
  }

  function renderBullets(listEl, items, emptyText) {
    listEl.innerHTML = "";
    const entries = Array.isArray(items) ? items.filter(Boolean) : [];
    if (entries.length === 0) {
      listEl.appendChild(el("li", "empty", emptyText));
      return 0;
    }
    for (const item of entries) {
      listEl.appendChild(el("li", null, typeof item === "string" ? item : JSON.stringify(item)));
    }
    return entries.length;
  }

  function emptyState(message) {
    return el("p", "empty", message);
  }

  function evidenceBlock(quote) {
    if (!quote) return null;
    const bq = el("blockquote", "evidence");
    bq.textContent = `\u201C${quote}\u201D`;
    return bq;
  }

  function renderDecisions(container, items) {
    container.innerHTML = "";
    const entries = Array.isArray(items) ? items : [];
    if (entries.length === 0) {
      container.appendChild(emptyState("No explicit decisions were detected in this meeting."));
      return 0;
    }
    entries.forEach((item, i) => {
      const d = typeof item === "string" ? { decision: item, reason: "", evidence: item } : item;
      const card = el("div", "item-card decision-card");
      card.appendChild(el("p", "item-title", `${i + 1}. ${d.decision || "—"}`));
      if (d.reason) {
        const reason = el("p", "item-sub");
        reason.appendChild(el("span", "field-label", "Reason: "));
        reason.append(document.createTextNode(d.reason));
        card.appendChild(reason);
      }
      const ev = evidenceBlock(d.evidence);
      if (ev) card.appendChild(ev);
      container.appendChild(card);
    });
    return entries.length;
  }

  function priorityBadge(priority) {
    const p = (priority || "medium").toLowerCase();
    const badge = el("span", `priority priority-${p}`, p.charAt(0).toUpperCase() + p.slice(1));
    return badge;
  }

  function renderActions(container, items) {
    container.innerHTML = "";
    const entries = Array.isArray(items) ? items : [];
    if (entries.length === 0) {
      container.appendChild(emptyState("No action items were detected in this meeting."));
      return 0;
    }
    entries.forEach((item) => {
      const a = typeof item === "string" ? { task: item, evidence: item } : item;
      const card = el("div", "item-card action-card");
      const head = el("div", "action-head");
      head.appendChild(el("p", "item-title", a.task || "—"));
      head.appendChild(priorityBadge(a.priority));
      card.appendChild(head);
      const meta = el("div", "action-meta");
      meta.appendChild(el("span", "meta-pill", `Owner: ${a.owner || "—"}`));
      meta.appendChild(el("span", "meta-pill", `Deadline: ${a.deadline || "—"}`));
      card.appendChild(meta);
      const ev = evidenceBlock(a.evidence);
      if (ev) card.appendChild(ev);
      container.appendChild(card);
    });
    return entries.length;
  }

  function renderTopics(container, topics) {
    container.innerHTML = "";
    const entries = Array.isArray(topics) ? topics.filter(Boolean) : [];
    if (entries.length === 0) {
      container.appendChild(emptyState("No topics were extracted."));
      return;
    }
    for (const t of entries) {
      container.appendChild(el("span", "chip", String(t)));
    }
  }

  function renderResults(data) {
    stopLoading();

    headlineEl.textContent = data.headline || "Meeting report";

    metaStrip.innerHTML = "";
    addMetaChip("File", data.filename || "—");
    addMetaChip("Language", (data.language || "?").toUpperCase());
    addMetaChip("Audio length", formatDuration(data.audio_duration_seconds));
    if (data.timing && data.timing.total_seconds != null) {
      addMetaChip("Processed in", `${data.timing.total_seconds}s`);
    }
    if (data.backends && data.backends.speech_to_text) {
      addMetaChip("STT", data.backends.speech_to_text);
      addMetaChip("Analysis", data.backends.summarization || "—");
    }

    summaryTextEl.textContent =
      data.summary || "No summary could be generated for this recording.";

    const kpCount = renderBullets(
      keyPointsListEl, data.key_points, "No key points were detected in this meeting."
    );
    const dCount = renderDecisions(decisionsListEl, data.decisions);
    const aCount = renderActions(actionsListEl, data.action_items);
    renderTopics(topicsListEl, data.topics);
    const qCount = renderBullets(
      questionsListEl, data.open_questions, "No open questions — everything looks resolved."
    );
    keyPointsCountEl.textContent = kpCount;
    decisionsCountEl.textContent = dCount;
    actionsCountEl.textContent = aCount;
    questionsCountEl.textContent = qCount;

    transcriptTextEl.textContent = data.transcript || "";
    transcriptCard.open = false;

    resultsEl.hidden = false;
    resultsEl.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function reset() {
    clearSelection();
    stopLoading();
    clearError();
    resultsEl.hidden = true;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // ---------- events -------------------------------------------------------- //

  browseBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    fileInput.click();
  });

  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });

  fileInput.addEventListener("change", () => acceptFile(fileInput.files[0]));

  ["dragenter", "dragover"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add("dragging");
    })
  );

  ["dragleave", "dragend"].forEach((evt) =>
    dropzone.addEventListener(evt, () => dropzone.classList.remove("dragging"))
  );

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    acceptFile(file);
  });

  removeBtn.addEventListener("click", clearSelection);
  analyzeBtn.addEventListener("click", analyze);
  resetBtn.addEventListener("click", reset);
})();
