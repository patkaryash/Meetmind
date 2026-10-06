/* MeetMind frontend — vanilla JS, no build step.
 * Workflow: upload audio → POST /api/analyze → render structured summary.
 */
(() => {
  "use strict";

  // Mirrors app/config.py defaults (frontend cannot read env).
  const ALLOWED_EXTENSIONS = ["mp3", "wav", "m4a"];
  const MAX_UPLOAD_MB = 100;

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
  const statusElapsedEl = $("status-elapsed");
  const errorEl = $("error");
  const resultsEl = $("results");
  const metaStrip = $("meta-strip");
  const summaryTextEl = $("summary-text");
  const keyPointsListEl = $("keypoints-list");
  const decisionsListEl = $("decisions-list");
  const actionsListEl = $("actions-list");
  const keyPointsCountEl = $("keypoints-count");
  const decisionsCountEl = $("decisions-count");
  const actionsCountEl = $("actions-count");
  const transcriptTextEl = $("transcript-text");
  const transcriptCard = document.querySelector(".transcript-card");

  let selectedFile = null;
  let elapsedTimer = null;

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

  function startLoading() {
    statusEl.hidden = false;
    resultsEl.hidden = true;
    analyzeBtn.disabled = true;
    statusTextEl.textContent = "Analyzing your meeting…";
    const started = Date.now();
    statusElapsedEl.textContent = "0s";
    elapsedTimer = setInterval(() => {
      statusElapsedEl.textContent = `${Math.round((Date.now() - started) / 1000)}s`;
    }, 1000);
  }

  function stopLoading() {
    if (elapsedTimer) {
      clearInterval(elapsedTimer);
      elapsedTimer = null;
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
    const chip = document.createElement("span");
    chip.className = "meta-chip";
    const strong = document.createElement("strong");
    strong.textContent = value;
    chip.append(`${label}: `, strong);
    metaStrip.appendChild(chip);
  }

  function renderList(listEl, items, emptyText) {
    listEl.innerHTML = "";
    const entries = Array.isArray(items) ? items : [];
    if (entries.length === 0) {
      const li = document.createElement("li");
      li.className = "empty";
      li.textContent = emptyText;
      listEl.appendChild(li);
      return 0;
    }
    for (const text of entries) {
      const li = document.createElement("li");
      li.textContent = text;
      listEl.appendChild(li);
    }
    return entries.length;
  }

  function renderResults(data) {
    stopLoading();

    metaStrip.innerHTML = "";
    addMetaChip("File", data.filename || "—");
    addMetaChip("Language", (data.language || "?").toUpperCase());
    addMetaChip("Audio length", formatDuration(data.audio_duration_seconds));
    if (data.timing && data.timing.total_seconds != null) {
      addMetaChip("Processed in", `${data.timing.total_seconds}s`);
    }
    if (data.backends && data.backends.speech_to_text) {
      addMetaChip("STT", data.backends.speech_to_text);
      addMetaChip("Summarizer", data.backends.summarization || "—");
    }

    summaryTextEl.textContent =
      data.summary || "No summary could be generated for this recording.";

    const kpCount = renderList(
      keyPointsListEl, data.key_points, "No key points were detected in this meeting."
    );
    const dCount = renderList(
      decisionsListEl, data.decisions, "No explicit decisions were detected in this meeting."
    );
    const aCount = renderList(
      actionsListEl, data.action_items, "No action items were detected in this meeting."
    );
    keyPointsCountEl.textContent = kpCount;
    decisionsCountEl.textContent = dCount;
    actionsCountEl.textContent = aCount;

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
