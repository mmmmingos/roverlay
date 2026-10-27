"""Voice memory: what Roverlay has seen in each chat, as one plain-text Markdown file per contact.

Documents\\Roverlay\\voice\\<app>\\<contact>.md. Each line says who wrote it: **Me** or the other person's name.
Chats where the app gives no reliable way to tell aren't saved. Files are meant to be opened, read, edited and deleted by
the user. Only the newest MAX_LINES are kept per contact. Drafting reads the user's own past lines back as tone
examples for that person.
"""
import re
import shutil
from datetime import date

from .config import MEMORY_DIR

MAX_LINES = 200
LINE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) · \*\*(.+?):\*\* (.*)$")
HEADER = ("Messages Roverlay has seen in this chat, oldest first. **Me** is you. "
          "Edit or delete anything; Roverlay only adds to the end.\n")


def _safe(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name[:80] or "unnamed"


def path_for(app, contact):
    return MEMORY_DIR / _safe(app) / f"{_safe(contact)}.md"


def _label(m):
    return "Me" if m.who == "me" else ("unsure" if m.who == "unknown" else m.name)


def _read(path):
    """[(date, who, text)] from a memory file, oldest first."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = LINE.match(line)
        if m:
            out.append((m.group(1), m.group(2), m.group(3)))
    return out


def _write(path, app, contact, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"- {d} · **{who}:** {text}" for d, who, text in rows[-MAX_LINES:])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(f"# {contact} · {app}\n\n{HEADER}\n{body}\n", encoding="utf-8")
    tmp.replace(path)


def worth_keeping(chat):
    """Only chats where we know who said what and who the chat is with."""
    return chat.method not in ("uia-generic", "none") and chat.contact not in ("", "them", "the channel") and bool(chat.messages)


def record(chat):
    """Add what's on screen to the contact's file, without repeating what's already there. Returns lines added."""
    if not worth_keeping(chat):
        return 0
    path = path_for(chat.app, chat.contact)
    old = _read(path)
    seen = [(who, text) for _, who, text in old]
    new = [(_label(m), " ".join(m.text.split())) for m in chat.messages if m.text.strip()]
    # The screen shows a window onto the chat: find where it overlaps the end of what we already have.
    overlap = 0
    for k in range(min(len(seen), len(new)), 0, -1):
        if seen[-k:] == new[:k]:
            overlap = k
            break
    fresh = new[overlap:]
    if not overlap:  # no clean overlap (scrolled up, or a gap): add only lines we've never stored
        stored = set(seen)
        fresh = [row for row in fresh if row not in stored]
    if not fresh:
        return 0
    today = date.today().isoformat()
    _write(path, chat.app, chat.contact, old + [(today, who, text) for who, text in fresh])
    return len(fresh)


def my_past_messages(chat, limit=30):
    """The user's own earlier messages in this chat that aren't on screen now: tone examples for the draft."""
    if not worth_keeping(chat):
        return []
    on_screen = {" ".join(m.text.split()) for m in chat.messages if m.who == "me"}
    mine = [text for _, who, text in _read(path_for(chat.app, chat.contact)) if who == "Me" and text not in on_screen]
    return mine[-limit:]


def summary():
    rows = []
    if MEMORY_DIR.exists():
        for f in MEMORY_DIR.glob("*/*.md"):
            rows.append({"app": f.parent.name, "contact": f.stem, "messages": len(_read(f))})
    return sorted(rows, key=lambda r: -r["messages"])


def forget_everything():
    """Delete every memory file. The user asks for this in Settings, with a second click to confirm."""
    count = len(list(MEMORY_DIR.glob("*/*.md"))) if MEMORY_DIR.exists() else 0
    if MEMORY_DIR.exists():
        shutil.rmtree(MEMORY_DIR)
    return count


def folder():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    return MEMORY_DIR
