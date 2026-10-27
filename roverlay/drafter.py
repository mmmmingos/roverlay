"""Draft the next message with a local model kept loaded in llama-server.

- The model stays loaded (it takes 4 to 6 s to load), on one slot so the prompt cache is shared.
- prefill() feeds the chat to the model while the user is still typing the instruction, so only the
  instruction's tokens are left to process when they press Enter.
- A draft that restates the instruction ("ask if he's keen ...") instead of being the message is redone once.
"""
import json
import re
import socket
import subprocess
import threading
import time
import urllib.request

import win32api
import win32con
import win32job

from .config import llama_ready, llama_server, model_path

# Restating the instruction instead of writing the message looks like "ask if he's keen..." or "Tell him the quote
# is...". Kept narrow: ordinary replies such as "I'll let him know", "Tell me more" or "Ask away" must not match,
# because a match means nothing gets typed.
ECHO = re.compile(r"^(ask|tell) (him|her|them|if|whether)\b|\bask (him|her) (if|whether|to)\b|\bask if (he|she)\b"
                  r"|\btell (him|her) (that|to|i)\b", re.I)
START_TIMEOUT = 120  # seconds for llama-server to load the model before we call it failed

SYSTEM = (
    "You write the next chat message for the user, called Me, in the conversation below, following Me's instruction. "
    "Write as Me, in first person, speaking directly to the other person. Never restate the instruction or talk about "
    "the other person in the third person. Match how Me writes to this specific person in this chat: message length, "
    "casing, punctuation, slang, and formality. Use emoji only if Me uses them with this person. Don't add facts that "
    "aren't in the chat, the instruction, or what Me already wrote. Lines starting \"Me:\" are the user's own; other "
    "names are the other people; \"unsure:\" lines could be from either side, so don't rely on who wrote them. "
    "Output only the message text."
)
TIDY = "tidy it up: fix typos, grammar and awkward wording, but keep my meaning, my tone and about the same length"


def free_port():
    """A port nothing is listening on. A fixed port let another program (or an old copy) answer as our model."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Drafter:
    def __init__(self, model="9b"):
        self.model = model
        self.proc = None
        self.port = None
        self.ready = threading.Event()
        self.failed = None  # why the model couldn't start, for the bar to show

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def healthy(self):
        if not self.port:
            return False
        try:
            with urllib.request.urlopen(f"{self.url}/health", timeout=1) as r:
                return r.status == 200
        except Exception:
            return False

    def available(self):
        return model_path(self.model).exists() and llama_ready()

    def start(self):
        """Load the chosen model in the background, in our own llama-server on a free port. Does nothing until the
        model and llama.cpp are downloaded."""
        self.failed = None
        if not self.available():
            print(f"model {self.model} not downloaded yet; open Settings to download it")
            return False
        self.port = free_port()
        self.proc = subprocess.Popen(
            [str(llama_server()), "-m", str(model_path(self.model)), "-ngl", "99", "-c", "8192", "-np", "1",
             "--reasoning", "off", "--host", "127.0.0.1", "--port", str(self.port), "--no-webui"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        self._tie_to_this_process(self.proc)
        threading.Thread(target=self._wait, args=(self.proc,), daemon=True).start()
        return True

    def switch(self, model):
        """Unload the current model and load another."""
        self.stop()
        self.ready.clear()
        self.model = model
        return self.start()

    def ensure_running(self):
        """After a crash (say, out of graphics memory on a long chat), load the model again."""
        if self.proc is None or self.proc.poll() is not None:
            self.ready.clear()
            return self.start()
        return True

    def _tie_to_this_process(self, proc):
        """Put the server in a job that Windows closes when this process exits, however it exits,
        so a crash or a closed console never leaves the model holding 5.6 GB of graphics memory."""
        self.job = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation)
        info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation, info)
        handle = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, proc.pid)
        win32job.AssignProcessToJobObject(self.job, handle)

    def _wait(self, proc):
        """Ready once the server answers; failed if it exits first or takes too long. Without the exit check, a
        server that couldn't start (old NVIDIA driver, a broken download) left the bar on "Loading" forever."""
        t0 = time.time()
        while not self.healthy():
            if proc.poll() is not None:
                self.failed = ("The model couldn't start. Check your NVIDIA driver is up to date, or download "
                               "the model again from Settings.")
                print(f"llama-server exited during start (code {proc.returncode})")
                return
            if time.time() - t0 > START_TIMEOUT:
                self.failed = "The model took too long to load. Restart Roverlay from the tray icon."
                print("llama-server didn't become ready in time")
                return
            time.sleep(0.25)
        self.ready.set()

    def wait_ready(self, timeout=START_TIMEOUT):
        """True when ready; False when it failed or timed out (self.failed says why)."""
        t0 = time.time()
        while not self.ready.is_set():
            if self.failed or time.time() - t0 > timeout:
                return False
            time.sleep(0.1)
        return True

    def stop(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except Exception:
                pass
            self.proc = None

    @staticmethod
    def _chat_block(chat):
        lines = []
        if chat.examples:  # from voice memory: how Me has written to this person before, beyond what's on screen
            lines.append(f"Earlier messages Me sent to {chat.contact}, for tone only:")
            lines += [f"Me: {t}" for t in chat.examples]
            lines.append("")
        lines.append(f"Conversation in {chat.app} with {chat.contact}, oldest first:")
        for m in chat.messages:
            lines.append(f"{'Me' if m.who == 'me' else m.name}: {m.text}")
        return "\n".join(lines)

    def _messages(self, chat, instruction=None, existing=None, written_from=None):
        """New message: the chat, then Me's instruction. Rewrite: the chat, the text already in the message box
        (Me's own or an earlier draft), then how to change it. Both start with the same chat block, so the
        prefill cached while the user types serves either."""
        user = self._chat_block(chat) + "\n\n"
        if instruction is None:  # prefill: everything both prompts share
            return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
        if existing is None:
            user += f"Me's instruction: {instruction}\nWrite Me's next message."
        else:
            user += f"Me has already written this in the message box:\n<<<\n{existing}\n>>>\n"
            if written_from:
                user += f"(It was drafted from Me's earlier instruction: {written_from})\n"
            user += (f"Me's instruction for changing it: {instruction}\n"
                     "Rewrite the message following that instruction. Keep everything Me didn't ask to change, "
                     "including Me's facts, meaning and way of writing. Output the whole rewritten message.")
        return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]

    def prefill(self, chat):
        """Process the chat now, while the user types; the draft request reuses it from the cache."""
        def go():
            if not self.wait_ready():
                return
            body = {"messages": self._messages(chat), "max_tokens": 1, "cache_prompt": True}
            try:
                self._post(body, stream=False)
            except Exception:
                pass
        threading.Thread(target=go, daemon=True).start()

    def _post(self, body, stream):
        req = urllib.request.Request(f"{self.url}/v1/chat/completions", data=json.dumps({**body, "stream": stream}).encode(),
                                     headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=120)

    def draft(self, chat, instruction, on_token, existing=None, written_from=None):
        """Stream a draft (or, with existing, a rewrite of the box's text) to on_token;
        returns (text, first_token_ms, total_ms, retried).

        The first HOLD characters are held back and checked for an echoed instruction before any are
        released, because released tokens get typed straight into the chat and can't be taken back."""
        HOLD = 40
        # In a rewrite, the user's own text may legitimately say "tell him ..."; don't flag what they wrote.
        check = (lambda t: bool(ECHO.search(t))) if not (existing and ECHO.search(existing)) else (lambda t: False)
        if not self.wait_ready():
            raise RuntimeError(self.failed or "the model isn't ready")
        t0 = time.perf_counter()
        first_ms = None
        for attempt in range(2):
            body = {"messages": self._messages(chat, instruction, existing, written_from), "temperature": 0.7,
                    "max_tokens": 300, "cache_prompt": True}
            parts, released, echoed = [], False, False
            with self._post(body, stream=True) as r:
                for raw in r:
                    line = raw.decode("utf-8").strip()
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    for c in json.loads(line[6:]).get("choices", []):
                        piece = (c.get("delta") or {}).get("content")
                        if not piece:
                            continue
                        parts.append(piece)
                        if released:
                            on_token(piece)
                        elif len("".join(parts)) >= HOLD:
                            if check("".join(parts).strip()):
                                echoed = True
                                break
                            released = True
                            first_ms = first_ms or round((time.perf_counter() - t0) * 1000)
                            on_token("".join(parts))
                    if echoed:
                        break
            text = "".join(parts).strip().strip('"')
            if echoed or (not released and check(text)):
                continue  # nothing was typed yet; try once more (twice failing types nothing at all)
            if not released:  # a short draft that never reached HOLD characters
                first_ms = round((time.perf_counter() - t0) * 1000)
                on_token("".join(parts))
            break
        return text, first_ms, round((time.perf_counter() - t0) * 1000), attempt > 0
