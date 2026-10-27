// Settings. The page renders whatever get_settings() returns and writes each change straight back.
// Wrapped in a function so its names don't collide with pywebview's own globals (a top-level `const keys`
// once made every evaluate_js call return None). Only window.settingsUI is shared.
(() => {
const $ = (id) => document.getElementById(id);
const api = () => window.pywebview.api;

const MODELS = [
  { name: "9b", title: "Qwen3.5 9B", blurb: "Best replies. Needs about 6 GB of graphics memory.", sizeGb: 5.7, recommended: true },
  { name: "4b", title: "Qwen3.5 4B", blurb: "Faster, for smaller graphics cards. Needs about 3.5 GB.", sizeGb: 2.7 },
];

const TOGGLES = { memoryEnabled: "memory_enabled", launchAtStartup: "launch_at_startup", paused: "paused" };
const TOGGLE_ERRORS = { memory_enabled: "memoryError", launch_at_startup: "generalError", paused: "generalError" };

const CONTACT_ROWS = 6;
const FORGET_WINDOW_MS = 4000;
const SAVE_FAILED = "Couldn't save that. Try again.";

let settings = null;
let contacts = [];
// Shortcut field: "idle", "capturing" (waiting for a key combo) or "saving" (set_hotkey in flight).
let hotkeyMode = "idle";
let forgetTimer = 0; // set while "Forget everything" waits for its second click
let pollTimer = 0;
let loading = false;

// --- small helpers ---

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

function showNote(id, msg) {
  const node = $(id);
  node.textContent = msg || "";
  node.hidden = !msg;
}

const gb = (mb) => (mb >= 1000 ? (mb / 1000).toFixed(1) + " GB" : Math.round(mb) + " MB");
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

async function save(partial, errorId) {
  showNote(errorId, "");
  try {
    const r = await api().save_settings(partial);
    if (r && r.ok) {
      Object.assign(settings, partial);
      return true;
    }
    showNote(errorId, (r && r.error) || SAVE_FAILED);
  } catch (err) {
    showNote(errorId, SAVE_FAILED);
  }
  render(); // put the controls back to what is actually saved
  return false;
}

// --- shortcut ---

const MODIFIERS = [["ctrlKey", "Ctrl"], ["altKey", "Alt"], ["shiftKey", "Shift"], ["metaKey", "Win"]];
const MODIFIER_KEYS = new Set(["Control", "Alt", "AltGraph", "Shift", "Meta", "OS"]);
const NAMED_KEYS = {
  Space: "Space", ArrowUp: "Up", ArrowDown: "Down", ArrowLeft: "Left", ArrowRight: "Right",
  Home: "Home", End: "End", PageUp: "PageUp", PageDown: "PageDown", Insert: "Insert", Delete: "Delete",
};

// e.code, not e.key: e.key changes with Shift and keyboard layout ("!" instead of "1").
function keyName(code) {
  if (/^Key[A-Z]$/.test(code)) return code.slice(3);
  if (/^Digit[0-9]$/.test(code)) return code.slice(5);
  if (/^F([1-9]|1[0-9]|2[0-4])$/.test(code)) return code;
  return NAMED_KEYS[code] || null;
}

function chips(combo) {
  const parts = combo.split("+");
  const nodes = [];
  parts.forEach((part, i) => {
    if (i) nodes.push(el("span", null, "+"));
    nodes.push(el("kbd", null, part));
  });
  return nodes;
}

function renderHotkey(preview) {
  const box = $("hotkey");
  const button = $("changeHotkey");
  box.classList.toggle("capturing", hotkeyMode === "capturing" && !preview);
  if (hotkeyMode === "capturing" && !preview) box.replaceChildren("Press the new shortcut…");
  else box.replaceChildren(...chips(preview || settings.hotkey));
  button.textContent = hotkeyMode === "capturing" ? "Cancel" : "Change";
  button.disabled = hotkeyMode === "saving";
}

function startCapture() {
  hotkeyMode = "capturing";
  showNote("hotkeyError", "");
  renderHotkey();
}

function stopCapture() {
  hotkeyMode = "idle";
  showNote("hotkeyError", "");
  renderHotkey();
}

async function applyHotkey(combo) {
  hotkeyMode = "saving";
  renderHotkey(combo);
  let r;
  try {
    r = await api().set_hotkey(combo);
  } catch (err) {
    r = { ok: false };
  }
  hotkeyMode = "idle";
  if (r && r.ok) settings.hotkey = combo;
  else showNote("hotkeyError", (r && r.error) || "Couldn't use that shortcut. Try another.");
  renderHotkey();
  $("changeHotkey").focus();
}

function onCaptureKey(e) {
  if (e.key === "Tab" && !e.ctrlKey && !e.altKey && !e.metaKey) return; // let focus move on; blur cancels
  e.preventDefault();
  e.stopPropagation();
  if (e.repeat) return;
  if (e.key === "Escape") { stopCapture(); return; }
  const mods = MODIFIERS.filter(([flag]) => e[flag]).map(([, name]) => name);
  if (MODIFIER_KEYS.has(e.key)) {
    renderHotkey(mods.join("+") + "+…");
    return;
  }
  const key = keyName(e.code);
  if (!key) {
    renderHotkey();
    showNote("hotkeyError", "That key can't be used. Try a letter, a number, Space or an F key.");
    return;
  }
  if (!e.ctrlKey && !e.altKey && !e.metaKey) {
    renderHotkey();
    showNote("hotkeyError", "Include Ctrl, Alt or Win, so the shortcut doesn't fire while you type.");
    return;
  }
  showNote("hotkeyError", "");
  applyHotkey([...mods, key].join("+"));
}

$("changeHotkey").addEventListener("click", () => (hotkeyMode === "capturing" ? stopCapture() : startCapture()));
$("changeHotkey").addEventListener("blur", () => { if (hotkeyMode === "capturing") stopCapture(); });

// --- models ---

const cards = new Map(); // model name -> { radio, status, progress, fill, progressText, key }

function buildModels() {
  for (const m of MODELS) {
    const card = el("div", "card");
    const main = el("label", "card-main");
    const radio = el("input");
    radio.type = "radio";
    radio.name = "model";
    radio.value = m.name;
    radio.addEventListener("change", () => {
      if (radio.checked) save({ model: m.name }, "modelError");
    });
    const text = el("span", "card-text");
    const title = el("span", "card-title", m.title);
    if (m.recommended) title.append(el("span", "tag", "Recommended"));
    text.append(title, el("span", "row-sub", m.blurb));
    main.append(radio, el("span", "radio"), text);

    const status = el("span", "status");
    const progress = el("div", "progress");
    const bar = el("div", "bar");
    const fill = el("div", "fill");
    const progressText = el("span", "progress-text");
    bar.append(fill);
    bar.setAttribute("role", "progressbar");
    bar.setAttribute("aria-label", `Downloading ${m.title}`);
    bar.setAttribute("aria-valuemin", "0");
    bar.setAttribute("aria-valuemax", "100");
    progress.append(bar, progressText);
    progress.hidden = true;

    card.append(main, status, progress);
    $("models").append(card);
    cards.set(m.name, { radio, status, progress, bar, fill, progressText, key: "" });
  }
}

async function download(name, button) {
  button.disabled = true;
  button.textContent = "Starting…";
  showNote("modelError", "");
  try {
    const r = await api().download_model(name);
    if (!r || !r.ok) showNote("modelError", (r && r.error) || "The download didn't start. Check your connection and try again.");
  } catch (err) {
    showNote("modelError", "The download didn't start. Check your connection and try again.");
  }
  await loadSettings();
}

function renderModels() {
  for (const m of MODELS) {
    const info = (settings.models && settings.models[m.name]) || { status: "missing" };
    const c = cards.get(m.name);
    const current = settings.model === m.name;
    c.radio.checked = current;
    // A model can only be picked once it is on this PC; the one in use stays selectable either way.
    c.radio.disabled = info.status !== "ready" && !current;

    if (info.status === "downloading") {
      const pct = Math.max(0, Math.min(100, Math.round(info.pct || 0)));
      c.fill.style.width = pct + "%";
      c.bar.setAttribute("aria-valuenow", String(pct));
      c.progressText.textContent = info.total_mb
        ? `${pct}%  ·  ${gb(info.done_mb || 0)} of ${gb(info.total_mb)}`
        : `${pct}%`;
    }

    // Rebuild the status cell only when the state changes, so a focused button isn't replaced every poll.
    if (c.key === info.status) continue;
    c.key = info.status;
    c.progress.hidden = info.status !== "downloading";
    if (info.status === "ready") {
      c.status.className = "status ok";
      c.status.replaceChildren("Ready");
    } else if (info.status === "downloading") {
      c.status.className = "status";
      c.status.replaceChildren("Downloading");
    } else {
      const size = info.size_gb || m.sizeGb;
      const button = el("button", "btn", `Download (${size} GB)`);
      button.type = "button";
      button.addEventListener("click", () => download(m.name, button));
      c.status.className = "status";
      c.status.replaceChildren(button);
    }
  }
}

function syncPolling() {
  const downloading = MODELS.some((m) => settings.models && settings.models[m.name] && settings.models[m.name].status === "downloading");
  if (downloading && !pollTimer) pollTimer = setInterval(loadSettings, 1000);
  if (!downloading && pollTimer) { clearInterval(pollTimer); pollTimer = 0; }
}

// --- voice memory ---

function renderContacts() {
  const list = $("contacts");
  const rows = contacts.slice(0, CONTACT_ROWS).map((c) => {
    const li = el("li");
    const who = el("span", "who");
    who.append(el("span", "app", `${c.app} · `), c.contact);
    li.append(who, el("span", "count", plural(c.messages, "message")));
    return li;
  });
  if (!contacts.length) rows.push(el("li", "empty", "Nothing saved yet."));
  else if (contacts.length > CONTACT_ROWS) rows.push(el("li", "more", `and ${contacts.length - CONTACT_ROWS} more`));
  list.replaceChildren(...rows);
  if (!forgetTimer) $("forget").disabled = !contacts.length;
}

function disarmForget() {
  clearTimeout(forgetTimer);
  forgetTimer = 0;
  const button = $("forget");
  button.classList.remove("armed");
  button.textContent = "Forget everything";
  button.disabled = !contacts.length;
}

$("forget").addEventListener("click", async () => {
  const button = $("forget");
  if (!forgetTimer) {
    button.classList.add("armed");
    button.textContent = "Click again to delete all saved messages";
    forgetTimer = setTimeout(disarmForget, FORGET_WINDOW_MS);
    return;
  }
  clearTimeout(forgetTimer);
  button.disabled = true;
  button.textContent = "Deleting…";
  showNote("memoryError", "");
  try {
    const r = await api().forget_everything();
    if (r && r.ok) $("forgetNote").textContent = typeof r.deleted === "number" ? `Deleted ${plural(r.deleted, "message")}.` : "Deleted.";
    else showNote("memoryError", (r && r.error) || "Couldn't delete everything. Try again.");
  } catch (err) {
    showNote("memoryError", "Couldn't delete everything. Try again.");
  }
  forgetTimer = 0;
  disarmForget();
  await refresh();
});

$("openFolder").addEventListener("click", async () => {
  showNote("memoryError", "");
  try {
    const r = await api().open_memory_folder();
    if (r && r.ok === false) showNote("memoryError", r.error || "Couldn't open the folder.");
  } catch (err) {
    showNote("memoryError", "Couldn't open the folder.");
  }
});

// --- toggles and names ---

for (const [id, field] of Object.entries(TOGGLES)) {
  const box = $(id);
  box.addEventListener("change", () => save({ [field]: box.checked }, TOGGLE_ERRORS[field]));
  box.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); box.click(); }
  });
}

const parseNames = (text) => [...new Set(text.split(",").map((s) => s.trim()).filter(Boolean))];

$("myNames").addEventListener("change", async () => {
  const names = parseNames($("myNames").value);
  if (names.join("\n") === (settings.my_names || []).join("\n")) return;
  const ok = await save({ my_names: names }, "namesNote");
  $("namesNote").classList.toggle("error", !ok);
  if (ok) {
    showNote("namesNote", names.length ? "Saved." : "Cleared. Names will be detected automatically.");
    setTimeout(() => showNote("namesNote", ""), 2500);
  }
});
$("myNames").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); $("myNames").blur(); }
});

// --- whole page ---

function render() {
  if (!settings) return;
  const v = String(settings.version || "").replace(/^v/i, "");
  $("version").textContent = v ? "v" + v : "";
  if (hotkeyMode === "idle") renderHotkey();
  renderModels();
  for (const [id, field] of Object.entries(TOGGLES)) $(id).checked = !!settings[field];
  $("memoryFolder").textContent = settings.memory_folder || "";
  $("memoryFolder").title = settings.memory_folder || "";
  const names = $("myNames");
  if (document.activeElement !== names) names.value = (settings.my_names || []).join(", ");
  renderContacts();
}

async function loadSettings() {
  if (loading) return;
  loading = true;
  try {
    settings = await api().get_settings();
    render();
    syncPolling();
  } catch (err) {
    showNote("modelError", "Lost touch with Roverlay. Close this window and open it again.");
  } finally {
    loading = false;
  }
}

async function refresh() {
  try {
    const [s, summary] = await Promise.all([api().get_settings(), api().memory_summary()]);
    settings = s;
    contacts = Array.isArray(summary) ? summary : [];
    render();
    syncPolling();
  } catch (err) {
    showNote("generalError", "Couldn't load settings. Close this window and open it again.");
  }
  $("content").classList.add("ready");
  requestAnimationFrame(() => requestAnimationFrame(() => $("content").classList.add("settled")));
}

function close() {
  if (hotkeyMode === "capturing") stopCapture();
  api().close();
}

$("done").addEventListener("click", close);

// Capture phase, so the shortcut field sees every key first and nothing in the page swallows Esc.
document.addEventListener("keydown", (e) => {
  if (hotkeyMode === "capturing") { onCaptureKey(e); return; }
  if (e.key === "Escape") { e.preventDefault(); close(); }
}, true);

window.settingsUI = { refresh };

buildModels();
let started = false;
function start() {
  if (started) return;
  started = true;
  refresh();
}
window.addEventListener("pywebviewready", start);
if (window.pywebview && window.pywebview.api && window.pywebview.api.get_settings) start();
})();
