"""The parts with no UI: the echo check, the labelled reader, a model server that dies at start, and downloads
that end early. No keystrokes, no windows, no real model. Usage: python tests/test_engine.py
"""
import http.server
import sys
import tempfile
import threading
from pathlib import Path

import roverlay.drafter as drafter
import roverlay.models as models
from roverlay.reader import El, labelled

failures = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail and not ok else ''}")
    if not ok:
        failures.append(name)


def echo():
    for t in ("ask him if he's keen on the price", "Tell her that I can't make it", "ok ask him whether 3k works",
              "tell them I said hi"):
        check(f"echo caught: {t!r}", bool(drafter.ECHO.search(t)))
    for t in ("I'll let him know tonight", "Tell me more about the job", "Ask away", "can you ask your mate?"):
        check(f"not an echo: {t!r}", not drafter.ECHO.search(t))


def reader():
    def g(name, depth=1):
        return El("GroupControl", name, (0, 0, 0, 0), depth)

    def t(name, depth=2):
        return El("TextControl", name, (0, 0, 0, 0), depth)
    # Chrome exposes each message twice: the paragraph, then the text inside it. After the chat comes page text
    # outside any group, like the message box's label and browser buttons.
    els = [g("Dave the tiler:"), t("Quote attached"), t("Quote attached"), t("$4,000 all up"), t("$4,000 all up"),
           g("You:"), t("bit steep mate"), t("bit steep mate"), t("Message Dave", 1), t("Create split view", 0)]
    contact, msgs = labelled(els, [])
    check("labelled: finds the contact", contact == "Dave the tiler", contact)
    check("labelled: each message once, nothing from outside the groups", len(msgs) == 3, str(len(msgs)))
    check("labelled: You is Me", msgs[-1].who == "me" and msgs[-1].name == "Me")
    beside = [g("Dave:", 3), t("hi there", 3), g("You:", 3), t("hey dave", 3)]  # labels next to, not around
    check("labelled: labels beside the messages still work", len(labelled(beside, [])[1]) == 2)
    check("labelled: no labels, no result", labelled([t("hello there")], []) is None)


def dead_server():
    """A llama-server that exits at start must fail fast with a message, not leave the bar loading forever."""
    d = drafter.Drafter("4b")
    drafter.llama_server = lambda: Path(sys.executable)  # python -m <gguf path> exits at once: no such module
    d.available = lambda: True
    d.start()
    ok = d.wait_ready(timeout=20)
    check("dead server: wait_ready is False", not ok)
    check("dead server: says why", bool(d.failed), str(d.failed))
    d.stop()


class Files(http.server.BaseHTTPRequestHandler):
    BODY = bytes(range(256)) * 400  # 102,400 bytes

    def log_message(self, *a):
        pass

    def _head(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.BODY)))
        self.end_headers()

    def do_HEAD(self):
        self._head()

    def do_GET(self):
        self._head()
        # /short claims the full length but hangs up halfway, like a dropped connection.
        self.wfile.write(self.BODY[: len(self.BODY) // 2] if self.path == "/short" else self.BODY)


def downloads():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Files)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "model.gguf"
        models._fetch(f"{base}/full", dest, lambda *a: None)
        check("download: complete file lands", dest.read_bytes() == Files.BODY)

        short = Path(tmp) / "short.gguf"
        try:
            models._fetch(f"{base}/short", short, lambda *a: None)
            raised = False
        except Exception:
            raised = True
        check("download: a cut-off file is not marked done", raised and not short.exists())

        part = Path(tmp) / "again.gguf.part"
        part.write_bytes(Files.BODY)
        models._fetch(f"{base}/full", Path(tmp) / "again.gguf", lambda *a: None)
        check("download: a finished .part is just renamed", (Path(tmp) / "again.gguf").exists() and not part.exists())
    server.shutdown()


def main():
    echo()
    reader()
    downloads()
    dead_server()
    print("\nall passed" if not failures else f"\n{len(failures)} failed: {failures}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
