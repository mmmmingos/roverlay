# Search and discovery

How the Roverlay repo is set up so people find it through GitHub search, Google, and AI answer engines such as ChatGPT, Perplexity, and Google AI Overviews. The README is the page that gets indexed. This file holds the repo settings that live outside it.

## GitHub "About" description

Paste this into the repo's About box. It is 303 characters, under GitHub's 350 limit. Google uses it as the page description for `github.com/mmmmingos/roverlay`, so the key phrases sit in the first sentence.

```text
Local AI that drafts chat replies on Windows. Press Ctrl+Shift+Space in WhatsApp Web, Messenger, Instagram, Slack or Discord, type what you want to say, and the reply appears in the message box in your tone. Runs offline on your GPU with llama.cpp and Qwen. No account, no cloud. It never sends for you.
```

## Repo topics

These are the 20 topics, which is GitHub's maximum. GitHub search matches topics directly, and each topic page lists the repos that use it.

```text
local-llm
llama-cpp
offline-ai
local-ai
ai-assistant
writing-assistant
reply-generator
smart-reply
chat-assistant
whatsapp
discord
slack
messenger
windows
windows-app
privacy
qwen
ui-automation
pywebview
grammarly-alternative
```

## Keywords targeted

Each keyword appears in the README in a natural place: the opening paragraph, a heading, or an FAQ question. None of them is repeated for its own sake. The GEO study (Aggarwal et al., KDD 2024) found that keyword stuffing lowers visibility in AI answers.

Nobody has measured search volume for these keywords. Each reason below is a judgment call, not data.

| Keyword | Why |
| --- | --- |
| local AI chat replies | The plainest description of the product. It opens the README and the About text. |
| offline AI reply WhatsApp | Privacy-minded people search this, and the FAQ uses it as a question word for word. |
| AI reply assistant Windows | Naming the platform filters for people who can run Roverlay. |
| local LLM Windows app | Local-model hobbyists already run a model and may want an everyday use for it. |
| llama.cpp desktop app | Developers search by runtime. The README names llama.cpp in the "Why local" and "How it works" sections. |
| Qwen3.5 9B | Model-name searches find projects that use a model. The README names the model and the quantization. |
| private AI writing assistant | The privacy angle is the main reason to pick Roverlay over a cloud tool. |
| Grammarly alternative local | A comparison query with a well-known name in it. The FAQ answers it and says what Roverlay does not do. |
| Wispr Flow alternative | Same comparison logic. The FAQ says Roverlay has no voice dictation, so the answer stays honest. |
| AI reply in my own tone | Matches the voice memory feature. The FAQ asks "Can an AI write replies in my own tone?". |
| Slack AI reply, Discord AI reply | Per-app searches. The supported-apps list and the FAQ name each app. |
| Spotlight-style overlay Windows | People who want a launcher-style bar for AI search this. The "What it does" steps use the phrase. |
| hotkey AI writing tool | Describes the interaction. `Ctrl+Shift+Space` appears in the About text, the steps, and the keys table. |
| GPU for local AI assistant | A hardware question that comes up before people install a local model. An FAQ answers it with the VRAM numbers. |
| Windows UI Automation chat | Developers who want to read chat windows without APIs. The README explains the method in "Why local". |
