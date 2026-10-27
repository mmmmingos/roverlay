"""Read the conversation in a window with UI Automation: who said what, and who it's with.

One small parser per app, learned from the overnight probes (docs/research/prototype-results.md).
Anything else falls back to a plain dump of the window's text, with no senders.
"""
import re
import time
from dataclasses import dataclass, field

import psutil
import uiautomation as auto
import win32gui
import win32process

TIME = re.compile(r"^\d{1,2}:\d{2}\s?(am|pm|AM|PM)?$")
NOISE = {"Delivered", "Read", "Sent", "Forward media", "Open picture", "Open message options", "Clip", "You",
         "Yesterday", "Today", "Click here to get older messages from your phone.", "web.whatsapp.com",
         "You deleted this message", "Image"}
WALK_BUDGET_S = 3.0
MAX_MESSAGES = 40


@dataclass
class Message:
    who: str  # "me" or "them"
    name: str
    text: str


@dataclass
class Chat:
    app: str
    contact: str
    messages: list = field(default_factory=list)
    hwnd: int = 0
    method: str = "none"
    read_ms: int = 0
    compose_text: str = None  # what's in the message box now, if the app exposes it
    examples: list = field(default_factory=list)  # the user's earlier messages to this contact, from voice memory


@dataclass
class El:
    type: str
    name: str
    rect: tuple
    depth: int
    value: str = None


def identify(hwnd):
    title = win32gui.GetWindowText(hwnd)
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    try:
        proc = psutil.Process(pid).name().lower()
    except Exception:
        proc = ""
    if proc == "slack.exe":
        return "Slack"
    if proc == "discord.exe":
        return "Discord"
    for key, app in (("WhatsApp", "WhatsApp"), ("Instagram", "Instagram"), ("Messenger", "Messenger"),
                     ("Facebook", "Messenger")):
        if key in title:
            return app
    # Anything else: name it after what's on screen ("Mock chat test"), not the browser ("Google Chrome").
    page = title.rsplit(" - ", 1)[0].strip() if " - " in title else title.strip()
    return (page[:28] + "…") if len(page) > 28 else (page or "this window")


def walk(hwnd):
    root = auto.ControlFromHandle(hwnd)
    els, t0 = [], time.perf_counter()
    for ctrl, depth in auto.WalkControl(root, includeTop=True, maxDepth=60):
        if time.perf_counter() - t0 > WALK_BUDGET_S:
            break
        try:
            r = ctrl.BoundingRectangle
            kind = ctrl.ControlTypeName
            value = None
            if kind in ("EditControl", "DocumentControl"):
                try:
                    value = ctrl.GetValuePattern().Value
                except Exception:
                    value = None
            els.append(El(kind, (ctrl.Name or "").strip(), (r.left, r.top, r.right, r.bottom), depth, value))
        except Exception:
            continue
    return els


def is_noise(text):
    return not text or text in NOISE or TIME.match(text) is not None


def whatsapp(els, rect, me_names):
    l, t, r, b = rect
    x0 = l + (r - l) * 0.34
    mid = (x0 + r) / 2
    contact, current, msgs = "them", None, []
    for e in els:
        if e.type == "EditControl" and e.name.startswith("Type a message to "):
            contact = e.name[len("Type a message to "):]
        if e.rect[0] < x0:
            continue
        if e.type == "GroupControl" and e.name.endswith(":") and len(e.name) < 60:
            current = "me" if e.name == "You:" else e.name[:-1]
            continue
        if e.type != "TextControl" or is_noise(e.name):
            continue
        # My bubbles sit on the right; a long one starts left of centre but ends near the right edge.
        if e.rect[0] > mid or e.rect[2] > r - 200:
            msgs.append(Message("me", "Me", e.name))
        else:
            name = current if current not in (None, "me") else contact
            msgs.append(Message("them", name, e.name))
    return contact, msgs


def side_based(els, rect, me_names):
    """Instagram and Messenger: bubbles, mine on the right."""
    l, t, r, b = rect
    x0 = l + (r - l) * 0.25
    mid = (x0 + r) / 2
    contact, msgs = "them", []
    for e in els:
        if e.type == "HyperlinkControl" and e.name.startswith("Open the profile page of "):
            contact = e.name[len("Open the profile page of "):]
        if e.type != "TextControl" or e.rect[0] < x0 or e.depth < 30 or is_noise(e.name):
            continue
        if e.name.startswith("You replied") or e.name.endswith(".com") or e.rect[1] < t + 150:
            continue
        mine = e.rect[0] > mid
        msgs.append(Message("me" if mine else "them", "Me" if mine else contact, e.name))
    return contact, msgs


def slack(els, rect, me_names):
    contact, author, msgs = "the channel", None, []
    for e in els:
        if e.type == "GroupControl" and e.name.startswith("Channel "):
            contact = e.name[len("Channel "):].replace(" (private)", "")
        if e.type != "ListItemControl":
            continue
        cont = re.match(r"^\d{1,2}:\d{2}(.*)$", e.name, re.S)
        if cont:
            text = cont.group(1)
        elif "\n" in e.name:
            head, text = e.name.split("\n", 1)
            author = re.split(r"\s{2,}", head)[0]
        else:
            continue
        text = " ".join(text.split())
        if author and text:
            mine = author in me_names
            msgs.append(Message("me" if mine else "them", "Me" if mine else author, text))
    return contact, msgs


def discord(els, rect, me_names):
    contact, msgs = "the channel", []
    for e in els:
        if e.type == "EditControl" and e.name.startswith("Message "):
            contact = e.name[len("Message "):]
        m = re.match(r"^(.+?) : , (.*) , \d{1,2}:\d{2} (AM|PM)$", e.name) if e.type == "GroupControl" else None
        if m:
            text = m.group(2).replace("Image", "").strip(" ,")
            if text:
                mine = m.group(1) in me_names
                msgs.append(Message("me" if mine else "them", "Me" if mine else m.group(1), text))
    return contact, msgs


def labelled(els, me_names):
    """Any chat site that labels each run of messages with its sender, the way WhatsApp Web does: a group named
    "Dave:" before Dave's messages and "You:" before yours. Returns (contact, messages), or None when the page
    has no such labels."""
    heads = [e for e in els if e.type == "GroupControl" and e.name.endswith(":") and 1 < len(e.name) < 60]
    if not heads:
        return None
    current, msgs, others = None, [], {}
    head_ids = {id(h) for h in heads}
    for e in els:
        if id(e) in head_ids:
            current = e.name[:-1].strip()
            continue
        if current is None or e.type != "TextControl" or is_noise(e.name) or len(e.name) < 2:
            continue
        mine = current in ("You", "Me") or current in me_names
        if not mine:
            others[current] = others.get(current, 0) + 1
        msgs.append(Message("me" if mine else "them", "Me" if mine else current, " ".join(e.name.split())))
    if not msgs:
        return None
    contact = max(others, key=others.get) if others else "them"
    return contact, msgs


def generic(els, rect, me_names):
    seen, msgs = set(), []
    for e in els:
        if e.type in ("TextControl", "ListItemControl") and len(e.name) > 2 and e.name not in seen and not is_noise(e.name):
            seen.add(e.name)
            msgs.append(Message("unknown", "unsure", " ".join(e.name.split())))
    return "them", msgs


def compose_text(els):
    """The message box is the lowest editable field that isn't the browser's address bar."""
    boxes = [e for e in els if e.type == "EditControl" and "Address and search" not in e.name
             and not e.name.lower().startswith("search")]
    return max(boxes, key=lambda e: e.rect[3]).value if boxes else None


PARSERS = {"WhatsApp": whatsapp, "Instagram": side_based, "Messenger": side_based, "Slack": slack, "Discord": discord}


def own_names(app, els):
    """Names the app itself shows for the signed-in user, so their messages are labelled Me without any setup.
    Discord: the two text lines under "Manage profile and status" in the user panel (display name, username).
    Slack exposes no such element (checked 2026-10-28); there the optional names in Settings do the job."""
    if app != "Discord":
        return set()
    for i, e in enumerate(els):
        if e.name == "Manage profile and status":
            texts = [x.name for x in els[i + 1:i + 6] if x.type == "TextControl" and x.name]
            return {t.lstrip(".") for t in texts[:2]}
    return set()


def read(hwnd, me_names):
    t0 = time.perf_counter()
    app = identify(hwnd)
    with auto.UIAutomationInitializerInThread():
        els = walk(hwnd)
    rect = win32gui.GetWindowRect(hwnd)
    me_names = set(me_names) | own_names(app, els)
    parser = PARSERS.get(app, generic)
    contact, msgs = parser(els, rect, me_names)
    method = f"uia-{app.lower()}" if app in PARSERS else "uia-generic"
    if app not in PARSERS:  # an app we don't know: use sender labels if the page has them
        found = labelled(els, me_names)
        if found:
            (contact, msgs), method = found, "uia-labelled"
    if app in PARSERS and not msgs:  # tree not built yet, or the layout changed: fall back to raw text
        contact, msgs = generic(els, rect, me_names)
        method = "uia-generic"
    return Chat(app, contact, msgs[-MAX_MESSAGES:], hwnd, method, round((time.perf_counter() - t0) * 1000),
                compose_text(els))


def warm_up():
    """Electron apps (Slack, Discord) build their accessibility tree only after a first request, seconds later."""
    hwnds = []
    win32gui.EnumWindows(lambda h, _: hwnds.append(h) if win32gui.IsWindowVisible(h) else None, None)
    with auto.UIAutomationInitializerInThread():
        for h in hwnds:
            if identify(h) in PARSERS:
                try:
                    for _ in auto.WalkControl(auto.ControlFromHandle(h), maxDepth=8):
                        pass
                except Exception:
                    pass
