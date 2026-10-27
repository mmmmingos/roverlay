"""Draft the next message with a local model kept loaded in llama-server.

- The model stays loaded (it takes 4 to 6 s to load), on one slot so the prompt cache is shared.
- prefill() feeds the chat to the model while the user is still typing the instruction, so only the
  instruction's tokens are left to process when they press Enter.
- A draft that restates the instruction ("ask if he's keen ...") instead of being the message is redone once.
"""
import json
import re
import subprocess
import threading
import time
import urllib.request

import win32api
import win32con
import win32job

from .config import llama_server, model_path

PORT = 8092
URL = f"http://127.0.0.1:{PORT}"
# Restating the instruction looks like "ask if he's keen..." or "Tell him the quote...". A false hit only costs one redo.
ECHO = re.compile(r"^(ask|tell)\s|\b(ask (him|her) |ask if (he|she)\b|tell (him|her)\b|let (him|her) know)", re.I)

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


def healthy():
    try:
        with urllib.request.urlopen(f"{URL}/health", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


class Drafter:
    def __init__(self, model="9b"):
        self.model = model
        self.proc = None
        self.ready = threading.Event()

    def available(self):
        return model_path(self.model).exists() and llama_server().exists()

    def start(self):
        """Load the chosen model in the background. Does nothing until the model and llama.cpp are downloaded."""
        if not self.available():
            print(f"model {self.model} not downloaded yet; open Settings to download it")
            return False
        if not healthy():
            self.proc = subprocess.Popen(
                [str(llama_server()), "-m", str(model_path(self.model)), "-ngl", "99", "-c", "8192", "-np", "1",
                 "--reasoning", "off", "--port", str(PORT), "--no-webui"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            self._tie_to_this_process(self.proc)
        threading.Thread(target=self._wait, daemon=True).start()
        return True

    def switch(self, model):
        """Unload the current model and load another."""
        self.stop()
        self.ready.clear()
        self.model = model
        deadline = time.time() + 10
        while healthy() and time.time() < deadline:  # wait for the old server to let go of the port
            time.sleep(0.2)
        return self.start()

    def _tie_to_this_process(self, proc):
        """Put the server in a job that Windows closes when this process exits, however it exits,
        so a crash or a closed console never leaves the model holding 5.6 GB of graphics memory."""
        self.job = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation)
        info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation, info)
        handle = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, proc.pid)
        win32job.AssignProcessToJobObject(self.job, handle)

    def _wait(self):
        while not healthy():
            time.sleep(0.25)
        self.ready.set()

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
            self.ready.wait()
            body = {"messages": self._messages(chat), "max_tokens": 1, "cache_prompt": True}
            try:
                self._post(body, stream=False)
            except Exception:
                pass
        threading.Thread(target=go, daemon=True).start()

    def _post(self, body, stream):
        req = urllib.request.Request(f"{URL}/v1/chat/completions", data=json.dumps({**body, "stream": stream}).encode(),
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
        self.ready.wait()
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
