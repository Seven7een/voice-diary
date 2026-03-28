/**
 * Voice Diary — PWA Frontend (Phase 2)
 */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let apiKey = localStorage.getItem("vd_api_key") || "";
let currentDate = new Date();
let currentView = "today"; // "today" | "diary"
let mediaRecorder = null;
let audioChunks = [];
let recordingStart = null;
let timerInterval = null;
let diaryOffset = 0;
let diaryTotal = 0;
const DIARY_PAGE_SIZE = 20;

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------
const $ = (sel) => document.querySelector(sel);
const datePickerEl = $("#date-picker");
const timelineEl = $("#timeline");
const emptyMsgEl = $("#empty-msg");
const recordBtn = $("#record-btn");
const micIcon = $("#mic-icon");
const recordingPulse = $("#recording-pulse");
const recordingTimer = $("#recording-timer");
const timerDisplay = $("#timer-display");
const prevDayBtn = $("#prev-day");
const nextDayBtn = $("#next-day");
const apiKeyModal = $("#api-key-modal");
const apiKeyInput = $("#api-key-input");
const apiKeySaveBtn = $("#api-key-save");

// Phase 2 elements
const navTodayBtn = $("#nav-today");
const navDiaryBtn = $("#nav-diary");
const viewToday = $("#view-today");
const viewDiary = $("#view-diary");
const diarySection = $("#diary-section");
const compileBtn = $("#compile-btn");
const recompileBtn = $("#recompile-btn");
const compileStatus = $("#compile-status");
const diaryContentEl = $("#diary-content");
const diaryList = $("#diary-list");
const diaryEmptyMsg = $("#diary-empty-msg");
const diaryLoadMore = $("#diary-load-more");
const loadMoreBtn = $("#load-more-btn");
const recordFab = $("#record-fab");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function fmtDate(d) {
    return d.toISOString().split("T")[0];
}

function fmtTime(isoStr) {
    const d = new Date(isoStr);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function fmtDuration(secs) {
    if (!secs && secs !== 0) return "--:--";
    const m = Math.floor(secs / 60).toString().padStart(2, "0");
    const s = (secs % 60).toString().padStart(2, "0");
    return `${m}:${s}`;
}

function fmtBytes(bytes) {
    if (!bytes) return "";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function fmtEntryDate(dateStr) {
    const d = new Date(dateStr + "T12:00:00");
    return d.toLocaleDateString(undefined, {
        weekday: "long", month: "long", day: "numeric", year: "numeric",
    });
}

async function apiFetch(path, opts = {}) {
    const headers = { "X-API-Key": apiKey, ...(opts.headers || {}) };
    const res = await fetch(path, { ...opts, headers });
    if (res.status === 401) {
        showApiKeyModal();
        throw new Error("Unauthorized");
    }
    return res;
}

/**
 * Simple markdown renderer — handles headers, bold, italic, paragraphs, lists.
 * No external dependencies.
 */
function renderMarkdown(md) {
    if (!md) return "";
    let html = md
        // Escape HTML
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        // Headers
        .replace(/^### (.+)$/gm, '<h3 class="text-base font-semibold text-gray-200 mt-4 mb-1">$1</h3>')
        .replace(/^## (.+)$/gm, '<h2 class="text-lg font-semibold text-gray-100 mt-4 mb-2">$1</h2>')
        .replace(/^# (.+)$/gm, '<h1 class="text-xl font-bold text-gray-100 mt-4 mb-2">$1</h1>')
        // Bold and italic
        .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
        .replace(/\*\*(.+?)\*\*/g, '<strong class="text-gray-200">$1</strong>')
        .replace(/\*(.+?)\*/g, '<em class="text-gray-300">$1</em>')
        // Unordered lists
        .replace(/^[-*] (.+)$/gm, '<li class="ml-4 text-gray-300">$1</li>')
        // Horizontal rule
        .replace(/^---$/gm, '<hr class="border-gray-700 my-3">')
        // Line breaks → paragraphs
        .replace(/\n\n/g, '</p><p class="text-gray-300 mb-3 leading-relaxed">')
        .replace(/\n/g, '<br>');
    // Wrap list items
    html = html.replace(/(<li[^>]*>.*?<\/li>)/gs, '<ul class="list-disc mb-3">$1</ul>');
    // Clean up duplicate ul wrappers
    html = html.replace(/<\/ul>\s*<ul[^>]*>/g, '');
    return `<p class="text-gray-300 mb-3 leading-relaxed">${html}</p>`;
}

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
function switchView(view) {
    currentView = view;
    document.querySelectorAll(".nav-tab").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.view === view);
    });
    viewToday.classList.toggle("hidden", view !== "today");
    viewDiary.classList.toggle("hidden", view !== "diary");
    recordFab.classList.toggle("hidden", view !== "today");

    if (view === "diary") {
        diaryOffset = 0;
        loadDiaryList();
    }
}

navTodayBtn.addEventListener("click", () => switchView("today"));
navDiaryBtn.addEventListener("click", () => switchView("diary"));

// ---------------------------------------------------------------------------
// API Key
// ---------------------------------------------------------------------------
function showApiKeyModal() {
    apiKeyModal.classList.remove("hidden");
    apiKeyInput.value = apiKey;
    apiKeyInput.focus();
}

apiKeySaveBtn.addEventListener("click", () => {
    apiKey = apiKeyInput.value.trim();
    if (!apiKey) return;
    localStorage.setItem("vd_api_key", apiKey);
    apiKeyModal.classList.add("hidden");
    loadRecordings();
});

apiKeyInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") apiKeySaveBtn.click();
});

// ---------------------------------------------------------------------------
// Date navigation
// ---------------------------------------------------------------------------
function setDate(d) {
    currentDate = d;
    datePickerEl.value = fmtDate(d);
    loadRecordings();
}

prevDayBtn.addEventListener("click", () => {
    const d = new Date(currentDate);
    d.setDate(d.getDate() - 1);
    setDate(d);
});

nextDayBtn.addEventListener("click", () => {
    const d = new Date(currentDate);
    d.setDate(d.getDate() + 1);
    setDate(d);
});

datePickerEl.addEventListener("change", () => {
    setDate(new Date(datePickerEl.value + "T12:00:00"));
});

// ---------------------------------------------------------------------------
// Load recordings + diary entry for a date
// ---------------------------------------------------------------------------
async function loadRecordings() {
    try {
        const [recRes, entryRes] = await Promise.all([
            apiFetch(`/api/v1/recordings?date=${fmtDate(currentDate)}`),
            apiFetch(`/api/v1/entries?date=${fmtDate(currentDate)}`),
        ]);

        if (!recRes.ok) throw new Error(recRes.statusText);
        const recordings = await recRes.json();
        renderTimeline(recordings);

        let entryData = null;
        if (entryRes.ok) {
            const entryJson = await entryRes.json();
            entryData = entryJson.entries && entryJson.entries.length > 0 ? entryJson.entries[0] : null;
        }
        renderDiarySection(recordings, entryData);
    } catch (err) {
        console.error("Failed to load recordings:", err);
    }
}

function renderTimeline(recordings) {
    timelineEl.querySelectorAll(".recording-card").forEach((el) => el.remove());

    if (recordings.length === 0) {
        emptyMsgEl.classList.remove("hidden");
        return;
    }
    emptyMsgEl.classList.add("hidden");

    recordings.forEach((rec) => {
        const card = document.createElement("div");
        card.className = "recording-card";
        card.innerHTML = `
            <div class="flex items-center justify-between mb-2">
                <div class="flex items-center gap-2">
                    <span class="text-sm font-medium text-indigo-400">${fmtTime(rec.recorded_at)}</span>
                    ${rec.compiled
                        ? '<span class="compiled-badge text-[10px] bg-emerald-900/50 text-emerald-400 border border-emerald-800 rounded-full px-1.5 py-0.5">compiled</span>'
                        : ""
                    }
                </div>
                <div class="flex items-center gap-2 text-xs text-gray-500">
                    <span>${fmtDuration(rec.duration_seconds)}</span>
                    <span>${fmtBytes(rec.file_size_bytes)}</span>
                </div>
            </div>
            <audio controls preload="none" src="/api/v1/recordings/${rec.id}/audio?key=${encodeURIComponent(apiKey)}"></audio>
            <div class="flex items-center justify-between mt-2">
                <div class="flex gap-1 flex-wrap">
                    ${rec.mood ? `<span class="text-xs bg-gray-800 text-gray-300 rounded-full px-2 py-0.5">${rec.mood}</span>` : ""}
                    ${(rec.tags || []).map((t) => `<span class="text-xs bg-gray-800 text-gray-400 rounded-full px-2 py-0.5">#${t}</span>`).join("")}
                </div>
                <button onclick="deleteRecording('${rec.id}')" class="text-gray-600 hover:text-red-400 transition p-1" title="Delete">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                </button>
            </div>
        `;
        timelineEl.appendChild(card);
    });
}

// ---------------------------------------------------------------------------
// Diary section (below timeline)
// ---------------------------------------------------------------------------
function renderDiarySection(recordings, entry) {
    const hasRecordings = recordings.length > 0;
    const hasUncompiled = recordings.some((r) => !r.compiled);

    if (!hasRecordings && !entry) {
        diarySection.classList.add("hidden");
        return;
    }

    diarySection.classList.remove("hidden");

    if (entry) {
        // Show compiled entry + recompile button
        compileBtn.classList.add("hidden");
        recompileBtn.classList.remove("hidden");
        compileStatus.classList.add("hidden");
        diaryContentEl.innerHTML = renderMarkdown(entry.content);
        diaryContentEl.classList.remove("hidden");
    } else if (hasRecordings) {
        // Show compile button
        compileBtn.classList.toggle("hidden", !hasUncompiled);
        recompileBtn.classList.add("hidden");
        compileStatus.classList.add("hidden");
        diaryContentEl.innerHTML = '<p class="text-gray-500 text-sm italic">No diary entry yet — compile your recordings.</p>';
        diaryContentEl.classList.remove("hidden");
    }
}

// ---------------------------------------------------------------------------
// Compile action
// ---------------------------------------------------------------------------
compileBtn.addEventListener("click", async () => {
    compileBtn.classList.add("hidden");
    compileStatus.classList.remove("hidden");
    diaryContentEl.innerHTML = "";

    try {
        const res = await apiFetch("/api/v1/entries/compile", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ date: fmtDate(currentDate) }),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: "Unknown error" }));
            throw new Error(err.detail || "Compilation failed");
        }

        // Reload to show the new entry
        await loadRecordings();
    } catch (err) {
        console.error("Compile failed:", err);
        compileStatus.classList.add("hidden");
        compileBtn.classList.remove("hidden");
        diaryContentEl.innerHTML = `<p class="text-red-400 text-sm">Compilation failed: ${err.message}</p>`;
        diaryContentEl.classList.remove("hidden");
    }
});

// Recompile action (force=true — deletes existing entry, recompiles all recordings)
recompileBtn.addEventListener("click", async () => {
    if (!confirm("Recompile will delete the current diary entry and re-transcribe all recordings. Continue?")) return;

    recompileBtn.classList.add("hidden");
    compileStatus.classList.remove("hidden");
    diaryContentEl.innerHTML = "";

    try {
        const res = await apiFetch("/api/v1/entries/compile", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ date: fmtDate(currentDate), force: true }),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: "Unknown error" }));
            throw new Error(err.detail || "Recompilation failed");
        }

        await loadRecordings();
    } catch (err) {
        console.error("Recompile failed:", err);
        compileStatus.classList.add("hidden");
        recompileBtn.classList.remove("hidden");
        diaryContentEl.innerHTML = `<p class="text-red-400 text-sm">Recompilation failed: ${err.message}</p>`;
        diaryContentEl.classList.remove("hidden");
    }
});

// ---------------------------------------------------------------------------
// Diary list view
// ---------------------------------------------------------------------------
async function loadDiaryList(append = false) {
    try {
        const res = await apiFetch(`/api/v1/entries?limit=${DIARY_PAGE_SIZE}&offset=${diaryOffset}`);
        if (!res.ok) throw new Error(res.statusText);
        const data = await res.json();
        diaryTotal = data.total;

        if (!append) {
            diaryList.querySelectorAll(".diary-list-card").forEach((el) => el.remove());
        }

        if (data.entries.length === 0 && !append) {
            diaryEmptyMsg.classList.remove("hidden");
            diaryLoadMore.classList.add("hidden");
            return;
        }
        diaryEmptyMsg.classList.add("hidden");

        data.entries.forEach((entry) => {
            const card = document.createElement("div");
            card.className = "diary-list-card bg-gray-900 border border-gray-800 rounded-xl p-4 cursor-pointer hover:border-gray-700 transition";
            card.innerHTML = `
                <div class="flex items-center justify-between mb-2">
                    <h3 class="text-sm font-semibold text-gray-200">${fmtEntryDate(entry.entry_date)}</h3>
                    <div class="flex items-center gap-2 text-xs text-gray-500">
                        <span>${entry.recording_count || 0} recording${entry.recording_count !== 1 ? "s" : ""}</span>
                        <span>·</span>
                        <span>${fmtDuration(entry.total_duration_seconds)}</span>
                    </div>
                </div>
                <p class="text-sm text-gray-400 line-clamp-3">${(entry.content || "").slice(0, 200).replace(/[#*_]/g, "")}…</p>
            `;
            card.addEventListener("click", () => {
                switchView("today");
                setDate(new Date(entry.entry_date + "T12:00:00"));
            });
            diaryList.appendChild(card);
        });

        // Show/hide load more
        const loaded = diaryOffset + data.entries.length;
        diaryLoadMore.classList.toggle("hidden", loaded >= diaryTotal);
    } catch (err) {
        console.error("Failed to load diary list:", err);
    }
}

if (loadMoreBtn) {
    loadMoreBtn.addEventListener("click", () => {
        diaryOffset += DIARY_PAGE_SIZE;
        loadDiaryList(true);
    });
}

// ---------------------------------------------------------------------------
// Delete recording
// ---------------------------------------------------------------------------
async function deleteRecording(id) {
    if (!confirm("Delete this recording?")) return;
    try {
        const res = await apiFetch(`/api/v1/recordings/${id}`, { method: "DELETE" });
        if (res.ok || res.status === 204) {
            loadRecordings();
        } else {
            alert("Failed to delete recording.");
        }
    } catch (err) {
        console.error("Delete failed:", err);
    }
}
window.deleteRecording = deleteRecording;

// ---------------------------------------------------------------------------
// Recording
// ---------------------------------------------------------------------------
recordBtn.addEventListener("click", async () => {
    if (mediaRecorder && mediaRecorder.state === "recording") {
        stopRecording();
    } else {
        await startRecording();
    }
});

async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

        let mimeType = "audio/ogg;codecs=opus";
        if (!MediaRecorder.isTypeSupported(mimeType)) {
            mimeType = "audio/webm;codecs=opus";
        }
        if (!MediaRecorder.isTypeSupported(mimeType)) {
            mimeType = "";
        }

        mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
        audioChunks = [];
        recordingStart = Date.now();

        mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0) audioChunks.push(e.data);
        };

        mediaRecorder.onstop = async () => {
            stream.getTracks().forEach((t) => t.stop());
            clearInterval(timerInterval);
            recordingTimer.classList.add("hidden");
            recordingPulse.classList.add("hidden");
            recordBtn.classList.remove("bg-gray-700");
            recordBtn.classList.add("bg-red-600");

            const durationSec = Math.round((Date.now() - recordingStart) / 1000);
            const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType || "audio/ogg" });
            await uploadRecording(blob, durationSec);
        };

        mediaRecorder.start(1000);

        recordBtn.classList.remove("bg-red-600");
        recordBtn.classList.add("bg-gray-700");
        recordingPulse.classList.remove("hidden");
        recordingTimer.classList.remove("hidden");
        timerDisplay.textContent = "00:00";
        timerInterval = setInterval(() => {
            const elapsed = Math.round((Date.now() - recordingStart) / 1000);
            timerDisplay.textContent = fmtDuration(elapsed);
        }, 500);

    } catch (err) {
        console.error("Microphone access failed:", err);
        alert("Microphone access denied. Please allow microphone permissions.");
    }
}

function stopRecording() {
    if (mediaRecorder && mediaRecorder.state === "recording") {
        mediaRecorder.stop();
    }
}

async function uploadRecording(blob, durationSec) {
    const now = new Date();
    const form = new FormData();
    form.append("file", blob, "recording.ogg");
    form.append("recorded_at", now.toISOString());
    form.append("duration_seconds", durationSec.toString());

    try {
        const res = await apiFetch("/api/v1/recordings", {
            method: "POST",
            body: form,
        });
        if (!res.ok) {
            const errBody = await res.text();
            console.error("Upload failed:", errBody);
            alert("Upload failed. Check console for details.");
            return;
        }
        setDate(new Date());
    } catch (err) {
        console.error("Upload error:", err);
        alert("Upload failed. Are you online?");
    }
}

// ---------------------------------------------------------------------------
// Service Worker
// ---------------------------------------------------------------------------
if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/static/sw.js").then(() => {
        console.log("Service Worker registered.");
    }).catch((err) => {
        console.warn("SW registration failed:", err);
    });
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
(function init() {
    if (!apiKey) {
        showApiKeyModal();
    }
    setDate(new Date());
})();
