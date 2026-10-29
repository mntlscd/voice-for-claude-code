# Voice for Claude Code

Talk to [Claude Code](https://claude.com/claude-code) out loud while you work in other apps (Unity, Blender, a browser, anything), and hear its answers.

Hold **F8** anywhere, speak, let go. Your words are typed into the Claude Code terminal you used last, exactly as if you had typed them, and Claude's reply is read aloud. It's the same Claude, in the same conversation, in the same terminal: no second session, no copy, nothing to sync.

> Community tool. Not made by or affiliated with Anthropic.

## What it does

| | |
|---|---|
| **Hold F8** (any app) | Record while held; on release your speech is transcribed and sent to Claude Code |
| **Shift + F8** | Same, plus a screenshot of the window you are in, so Claude can see what you mean |
| **F9** | Stop the voice |
| **Type in the app window** | Sends typed text the same way |
| **Settings** | Microphone, voice, speed, push-to-talk key (F7 / F8 / F10 / F12), speech model |
| **Switch terminal** | If you have several Claude Code terminals open, choose which one you talk to |

It follows you: it always talks to the **most recently active** Claude Code terminal, in any project.

Claude can also take its own screenshots with `look.py` (any window by title, even if it is covered, the whole screen, or a zoomed region). The install adds a short note to your Claude Code instructions so Claude knows how.

## Requirements

- **Windows 10 or 11**: it uses Windows speech, Windows console input and Windows window capture. It does not work on macOS or Linux.
- **Python 3.10 or newer**, from [python.org](https://www.python.org/downloads/windows/) (tick "Add python.exe to PATH" in its installer).
- **Claude Code**, the terminal version, in a normal Windows terminal (Windows Terminal or the classic console).
- A microphone.
- Optional: an **NVIDIA GPU**. Speech recognition then takes well under a second per sentence. Without one it uses a smaller model on the CPU, which takes a few seconds per sentence.

## Install

1. Download this repo (**Code → Download ZIP**) and unzip it somewhere permanent, e.g. `C:\Tools\voice-for-claude-code`. Or `git clone https://github.com/mntlscd/voice-for-claude-code`.
2. Double-click **`install.pyw`** and press **Install**. It:
   - installs the Python packages (`requirements.txt`), plus NVIDIA's CUDA libraries if you have an NVIDIA GPU (about 1 GB, optional);
   - adds the `[voice]` rule to `~/.claude/CLAUDE.md` (see below), between markers so re-running updates it;
   - makes a Desktop and a Start menu shortcut called **Voice for Claude Code**.
3. Open **Voice for Claude Code**. The first start downloads the speech model (a few minutes, once).
4. Open Claude Code in any project, hold F8 and talk.

### Or let Claude Code install it for you

Paste this into Claude Code:

```
Install the voice tool from https://github.com/mntlscd/voice-for-claude-code for me on this Windows PC:
clone it to %USERPROFILE%\voice-for-claude-code, then run its installer steps without opening any console
window: pip install -r requirements.txt (add nvidia-cublas-cu12 and "nvidia-cudnn-cu12>=9,<10" if nvidia-smi
works), add the [voice] rule from VOICE_RULE.md to my ~/.claude/CLAUDE.md with {LOOK} replaced by the full path
of look.py, and create a Desktop shortcut "Voice for Claude Code" that runs voice_app.pyw with pythonw.exe.
Then start the app.
```

## How it works

```
your voice ── faster-whisper (local) ──► typed into your Claude Code terminal (as "[voice] ...")
                                                        │
Windows speech ◄── sentences ◄── the terminal's live transcript (~/.claude/projects/*/<session>.jsonl)
```

- **Speech to text:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper), on your PC. Your audio is not sent anywhere.
- **Typing into the terminal:** the app attaches to the Claude Code process's console and writes key presses into it (`inject.py`). The terminal does not need focus, so you can stay in your other app.
- **Which terminal:** Claude Code keeps a small file per running session in `~/.claude/sessions/`. The app picks the interactive one whose transcript changed most recently.
- **Reading replies aloud:** it follows that session's transcript and speaks each new text block with the built-in Windows voices (SAPI). Code blocks and table rows are skipped.
- **The `[voice]` rule** (`VOICE_RULE.md`, added to `~/.claude/CLAUDE.md`): tells Claude that messages starting with `[voice]` were spoken, so it answers short and speakable, and asks for a yes before anything destructive (speech recognition can mishear).

## Privacy

- Speech recognition and speech output run locally. What you say is sent to Claude only as the text that gets typed into Claude Code, like anything you type yourself.
- Screenshots (Shift+F8, or when Claude runs `look.py`) are saved in the `shots` folder and read by Claude, so they go wherever your Claude Code conversation goes. They show whatever is on screen at that moment.
- `config.json`, `app.log` and `shots/` are personal and ignored by git.

## Limits

- Windows only. Voices: only the Windows voices you have installed (often English-only; add more in Windows Settings → Time & language → Speech).
- Replies are read once complete text blocks reach the transcript, not word by word.
- Speech recognition can mishear. With voice, keep Claude Code's permission prompts on unless you trust that every command will be confirmed.
- Tested on one Windows 11 PC so far. Issues and pull requests are welcome.

## Uninstall

Delete the two shortcuts and the folder, and remove the block between `<!-- voice-for-claude-code:start -->` and `<!-- voice-for-claude-code:end -->` from `~/.claude/CLAUDE.md`. The packages can stay or go: `pip uninstall faster-whisper sounddevice comtypes`.

## License

[MIT](LICENSE)
