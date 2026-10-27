"""Voice memory, without any UI: labels, overlap without duplicates, the cap, tone examples, forget.
Runs in a temporary folder, never the real Documents\\Roverlay. Usage: python tests/test_memory.py
"""
import tempfile
from pathlib import Path

import roverlay.memory as memory
from roverlay.drafter import Drafter
from roverlay.reader import Chat, Message

failures = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail and not ok else ''}")
    if not ok:
        failures.append(name)


def chat(*rows, method="uia-whatsapp"):
    msgs = [Message("me", "Me", t) if who == "me" else Message("them", who, t) for who, t in rows]
    return Chat("WhatsApp", "Dave the tiler", msgs, 0, method)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        memory.MEMORY_DIR = Path(tmp) / "voice"

        first = chat(("Dave the tiler", "Quote attached, $4,000 all up"), ("me", "thanks dave, will have a look tonight"))
        check("records a new chat", memory.record(first) == 2)
        text = memory.path_for("WhatsApp", "Dave the tiler").read_text(encoding="utf-8")
        check("labels the other person by name", "**Dave the tiler:** Quote attached" in text)
        check("labels the user as Me", "**Me:** thanks dave" in text)

        check("same screen again adds nothing", memory.record(first) == 0)

        later = chat(("me", "thanks dave, will have a look tonight"), ("Dave the tiler", "I've got a gap in 2 weeks"),
                     ("me", "can you do 3.2?"))
        check("overlapping screen adds only the new lines", memory.record(later) == 2)

        unsure = Chat("WhatsApp", "Dave the tiler", [Message("unknown", "unsure", "who wrote this")], 0, "uia-whatsapp")
        memory.record(unsure)
        check("an unattributed line is labelled unsure",
              "**unsure:** who wrote this" in memory.path_for("WhatsApp", "Dave the tiler").read_text(encoding="utf-8"))

        generic = chat(("them", "some page text"), method="uia-generic")
        check("windows without names aren't stored", memory.record(generic) == 0)

        now = chat(("me", "can you do 3.2?"))
        past = memory.my_past_messages(now)
        check("tone examples are Me's earlier lines not on screen", past == ["thanks dave, will have a look tonight"],
              str(past))
        now.examples = past
        prompt = Drafter._chat_block(now)
        check("the prompt carries the examples before the chat",
              prompt.index("Earlier messages Me sent") < prompt.index("Conversation in WhatsApp"))

        many = chat(*[("me", f"message {i}") for i in range(250)])
        memory.record(many)
        lines = [l for l in memory.path_for("WhatsApp", "Dave the tiler").read_text(encoding="utf-8").splitlines()
                 if l.startswith("- ")]
        check("keeps only the newest 200 lines", len(lines) == 200 and lines[-1].endswith("message 249"), str(len(lines)))

        weird = Chat("Slack", 'design: "Q4" / plans?', [Message("me", "Me", "hi")], 0, "uia-slack")
        memory.record(weird)
        check("contact names become safe file names", memory.path_for("Slack", weird.contact).exists())

        check("summary lists each contact", {r["contact"] for r in memory.summary()} >= {"Dave the tiler"})
        check("forget everything deletes the files", memory.forget_everything() == 2 and memory.summary() == [])

    print(f"\n{'all passed' if not failures else str(len(failures)) + ' failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
