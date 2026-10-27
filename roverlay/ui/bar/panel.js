// The reply bar: type what you want and press Enter; the bar steps aside and the draft writes itself
// into the chat's message box. Pressing the hotkey again on the same chat redoes that draft.
// Wrapped in a function so its names don't collide with pywebview's own globals (a top-level
// `const keys` made every evaluate_js call return None). Only window.ui is shared.
(() => {
const $ = (id) => document.getElementById(id);
const ask = $("ask"), draft = $("draft"), body = $("body"), ctxChip = $("context"), status = $("status"), keys = $("keys");
let visible = false, hadFocus = false, rewrite = false, canUndo = false, busy = false;

const api = () => window.pywebview.api;
const UNDO = "<span><kbd>Ctrl</kbd><kbd>Z</kbd>undo last rewrite</span>";
const KEYS = {
  ask: "<span><kbd>Enter</kbd>write it in the chat</span><span><kbd>Esc</kbd>close</span>",
  rewrite: "<span><kbd>Enter</kbd>rewrite · empty tidies up</span><span><kbd>Esc</kbd>close</span>",
  fallback: "<span><kbd>Ctrl</kbd><kbd>Enter</kbd>copy</span><span><kbd>Esc</kbd>close</span>",
};
const keysFor = () => (rewrite ? KEYS.rewrite : KEYS.ask).replace("<span><kbd>Esc", (canUndo ? UNDO : "") + "<span><kbd>Esc");

// The window is the panel plus a transparent margin for its shadow on every side.
const ROOM = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--shadow-room")) || 28;

function fit() {
  draft.style.height = "auto";
  draft.style.height = Math.min(draft.scrollHeight, 220) + "px";
  requestAnimationFrame(() => api().resize(Math.ceil($("panel").offsetHeight + 2 * ROOM)));
}

function appear() {
  const panel = $("panel");
  panel.classList.remove("appear");
  void panel.offsetWidth; // restart the animation
  panel.classList.add("appear");
}

window.ui = {
  open() {
    visible = true;
    hadFocus = false;
    rewrite = false;
    canUndo = false;
    busy = false;
    ask.value = "";
    draft.value = "";
    body.hidden = true;
    ctxChip.textContent = "Reading chat…";
    ctxChip.classList.remove("warn");
    status.textContent = "";
    ask.placeholder = "What do you want to say?";
    keys.innerHTML = KEYS.ask;
    document.body.classList.remove("busy");
    appear();
    ask.focus();
    fit();
  },
  focus() { window.focus(); (body.hidden ? ask : draft).focus(); },
  context(c) {
    const known = c.method !== "uia-generic" && c.method !== "none";
    const named = known && c.contact && c.contact !== "them";
    rewrite = c.mode === "rewrite";
    canUndo = !!c.canUndo;
    // The chip says where the reply goes: "WhatsApp · Dave", or just the app or page when there's no name.
    ctxChip.textContent = named ? `${c.app} · ${c.contact}` : c.app;
    ctxChip.title = c.count ? `${c.count} messages read` : "nothing read";
    ctxChip.classList.toggle("warn", !c.count);
    // Short enough to fit beside the chip at chat-column widths (560 px).
    ask.placeholder = rewrite ? "Change it: firmer, shorter…" : named ? `Your reply to ${c.contact}…` : "What do you want to say?";
    keys.innerHTML = keysFor();
    // The footer line speaks only when it has something to say.
    let line = "";
    if (rewrite) line = `Rewriting: “${c.preview}${c.preview.length >= 70 ? "…" : ""}”`;
    else if (!c.count) line = "Couldn't read this window. You can still type; the draft just won't see the chat.";
    else if (!known) line = "No names found here, so the draft sees the text but not who said what.";
    if (!c.modelReady) line = (line ? line + "  ·  " : "") + "Loading the model, about 10 seconds the first time…";
    status.textContent = line;
    fit();
  },
  waiting(msg) { status.textContent = msg; },
  fallback(text, msg) {
    visible = true;
    hadFocus = false;
    busy = false;
    document.body.classList.remove("busy");
    body.hidden = !text;  // an error with nothing to copy is just the message
    draft.value = text;
    status.textContent = msg;
    keys.innerHTML = text ? KEYS.fallback : KEYS.fallback.split("</span>").slice(1).join("</span>");
    appear();
    fit();
    draft.focus();
    draft.select();
  },
  error(msg) { busy = false; document.body.classList.remove("busy"); status.textContent = msg; fit(); },
};

function nudge(msg) {
  status.textContent = msg;
  const panel = $("panel");
  panel.classList.remove("nudge");
  void panel.offsetWidth;
  panel.classList.add("nudge");
}

function submit() {
  const text = ask.value.trim();
  if (busy) return;
  if (!text && !rewrite) { nudge("Type what you want to say, then press Enter."); return; }
  // in a rewrite, Enter on its own means "tidy it up"
  busy = true;
  document.body.classList.add("busy");
  status.textContent = text.toLowerCase() === "undo" ? "Putting your original back…" : rewrite ? "Rewriting…" : "Writing…";
  visible = false; // the bar is about to step aside on purpose; don't treat that as a click-away
  api().draft(text);
}

// Esc closes the bar wherever focus is inside it, not only in the text field. Capture phase, so nothing
// in the page can swallow it first.
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  e.preventDefault();
  e.stopPropagation();
  visible = false;
  api().log("esc");
  api().hide("esc");
}, true);

ask.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); submit(); }
  if (e.key.toLowerCase() === "z" && e.ctrlKey && !ask.value && canUndo && !busy) {
    e.preventDefault();
    busy = true;
    visible = false;
    status.textContent = "Putting your original back…";
    api().undo();
  }
});

draft.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.ctrlKey) { e.preventDefault(); api().copy(draft.value.trim()); }
});
draft.addEventListener("input", fit);

// Like Spotlight: clicking elsewhere puts the bar away.
window.addEventListener("focus", () => { hadFocus = true; });
window.addEventListener("blur", () => { if (visible && hadFocus) { visible = false; api().hide("clicked away"); } });
window.addEventListener("pywebviewready", () => { keys.innerHTML = KEYS.ask; fit(); });
})();
