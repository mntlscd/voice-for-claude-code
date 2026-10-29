"""
voice_core.py - engine of Voice for Claude Code: a voice for the Claude Code terminal you already use.

Your words:  mic -> faster-whisper (GPU) -> typed into your Claude Code terminal (inject.py), exactly
             as if you typed them there. No second Claude, no copy of the session.
Its words:   that terminal's live transcript (~/.claude/projects/*/<session>.jsonl) -> Windows speech.
Which terminal: the running interactive Claude Code session that was active most recently, so it
             follows you from project to project. The window (voice_app.pyw) drives this.
"""
import ctypes, glob, json, os, queue, re, site, time

import inject

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "shots")
CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
SR_IN = 16000    # faster-whisper expects 16 kHz mono
MIN_SECONDS = 0.3
VK = {"F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79, "F12": 0x7B, "SHIFT": 0x10}
PTT_KEYS = ["F7", "F8", "F10", "F12"]  # F9 is taken: it stops the voice
VOICE_TAG = "[voice]"  # marks spoken messages, so Claude answers short and speakable (rule: VOICE_RULE.md)


# ---------- speech to text ----------
def add_cuda_dlls():
    """The CUDA runtime comes from pip wheels (nvidia-cublas-cu12, nvidia-cudnn-cu12)."""
    for base in site.getsitepackages() + [site.getusersitepackages()]:
        for d in glob.glob(os.path.join(base, "nvidia", "*", "bin")):
            os.add_dll_directory(d)
            os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]


def load_stt(cfg):
    """Returns (model, note); note says when the GPU model failed and CPU is used instead."""
    add_cuda_dlls()
    from faster_whisper import WhisperModel
    import numpy as np
    try:
        m = WhisperModel(cfg["whisper"], device=cfg["device"], compute_type=cfg["compute"])
        m.transcribe(np.zeros(SR_IN, dtype=np.float32))  # fail now, not on the first sentence
        return m, None
    except Exception as e:
        return WhisperModel("small", device="cpu", compute_type="int8"), \
            f"{cfg['device']} speech model failed ({e}); using CPU 'small'"


def transcribe(model, audio, lang):
    segments, _info = model.transcribe(audio, language=lang, vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()


def microphones():
    """Input devices as (index, name), Windows' default first; MME entries only, so each mic shows once."""
    import sounddevice as sd
    mme = next((i for i, h in enumerate(sd.query_hostapis()) if h["name"] == "MME"), None)
    found = [(i, d["name"]) for i, d in enumerate(sd.query_devices())
             if d["max_input_channels"] > 0 and (mme is None or d["hostapi"] == mme) and "Mapper" not in d["name"]]
    return found


class Recorder:
    def __init__(self, mic=None):
        import sounddevice as sd
        self.sd, self.frames, self.stream = sd, [], None
        self.mic = mic  # device name from Settings; None = Windows default input

    def _device(self):
        if self.mic:
            for i, name in microphones():
                if name == self.mic:
                    return i
        return None

    def start(self):
        self.frames = []
        self.stream = self.sd.InputStream(samplerate=SR_IN, channels=1, dtype="float32", device=self._device(),
                                          callback=lambda d, n, t, s: self.frames.append(d.copy()))
        self.stream.start()

    def stop(self):
        import numpy as np
        self.stream.stop(); self.stream.close()
        return np.concatenate(self.frames)[:, 0] if self.frames else np.zeros(0, dtype=np.float32)


# ---------- screenshot of the window in front ----------
def foreground_shot():
    """Saves the window you are in as a small JPEG; returns (title, path) for Claude to Read."""
    import look  # same folder; also makes this process DPI aware
    from PIL import ImageGrab
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    img = ImageGrab.grab(bbox=look.rect(hwnd), all_screens=True)
    img.thumbnail((900, 900))
    os.makedirs(SHOTS, exist_ok=True)
    path = os.path.join(SHOTS, time.strftime("voice_%Y%m%d_%H%M%S.jpg"))
    img.convert("RGB").save(path, "JPEG", quality=70)
    return look.title(hwnd), path


# ---------- text to speech ----------
class Speaker:
    """Windows SAPI voice; sentences queue up and play while more text arrives."""
    ASYNC, PURGE = 1, 2

    def __init__(self, name, rate):
        import comtypes.client
        self.v = comtypes.client.CreateObject("SAPI.SpVoice")
        self.set_voice(name)
        self.v.Rate = rate
        self.q = queue.Queue()

    def voices(self):
        return [tok.GetDescription() for tok in self.v.GetVoices()]

    def set_voice(self, name):
        """name: (part of) an installed Windows voice; None or no match keeps the current one."""
        if name:
            for tok in self.v.GetVoices():
                if name.lower() in tok.GetDescription().lower():
                    self.v.Voice = tok
                    return

    def pump(self):  # UI thread only (COM object lives there)
        while not self.q.empty():
            self.v.Speak(self.q.get_nowait(), self.ASYNC)

    def speaking(self):
        return self.v.Status.RunningState == 2

    def stop(self):
        while not self.q.empty():
            self.q.get_nowait()
        self.v.Speak("", self.ASYNC | self.PURGE)


class SentenceSplitter:
    """Cuts text into speakable sentences; skips code blocks and table rows."""
    def __init__(self, out):
        self.out, self.buf, self.in_code = out, "", False

    def feed(self, text):
        self.buf += text
        while True:
            if self.in_code:
                i = self.buf.find("```")
                if i < 0:
                    return
                self.buf, self.in_code = self.buf[i + 3:], False
                self.say("code shown on screen")
                continue
            fence = self.buf.find("```")
            m = re.search(r"[.!?:](\s|$)|\n", self.buf)
            if fence >= 0 and (not m or fence < m.start()):
                self.say(self.buf[:fence]); self.buf, self.in_code = self.buf[fence + 3:], True
            elif m and m.end() < len(self.buf):
                self.say(self.buf[:m.end()]); self.buf = self.buf[m.end():]
            else:
                return

    def flush(self):
        if not self.in_code:
            self.say(self.buf)
        self.buf, self.in_code = "", False

    def say(self, t):
        if t.lstrip().startswith("|"):                  # markdown table row: shown, not read
            return
        t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)   # [text](url) -> text
        t = re.sub(r"`([^`]*)`", r"\1", t)
        t = re.sub(r"[*_#>|]+", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        if re.search(r"\w", t):
            self.out.put(t)


# ---------- the Claude Code terminal you use ----------
def _alive(pid):
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(h)
    return code.value == 259  # STILL_ACTIVE


def _transcript(session_id):
    hits = glob.glob(os.path.join(CLAUDE_DIR, "projects", "*", session_id + ".jsonl"))
    return hits[0] if hits else None


def terminals():
    """Running interactive Claude Code terminal sessions, most recently active first."""
    found = []
    for f in glob.glob(os.path.join(CLAUDE_DIR, "sessions", "*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if d.get("kind") == "interactive" and d.get("entrypoint") == "cli" and _alive(d.get("pid", 0)):
            path = _transcript(d["sessionId"])
            d["active"] = os.path.getmtime(path) if path else d.get("startedAt", 0) / 1000
            found.append(d)
    return sorted(found, key=lambda d: d["active"], reverse=True)


class ClaudeTerminal:
    """Types into a Claude Code terminal and follows its transcript."""
    def __init__(self, out):
        self.out = out          # out(kind, text): kind = target | text | tool | done
        self.target = None
        self.pinned = None      # pid chosen by hand; otherwise follow the most recently active one
        self.path = None
        self.pos = 0
        self.partial = b""

    def refresh(self):
        all_ = terminals()
        pick = next((t for t in all_ if t["pid"] == self.pinned), None) or (all_[0] if all_ else None)
        if pick and self.target and (pick["pid"], pick["sessionId"]) == (self.target["pid"], self.target["sessionId"]):
            return all_
        self.target, self.partial = pick, b""
        self.path = _transcript(pick["sessionId"]) if pick else None
        self.pos = os.path.getsize(self.path) if self.path else 0  # only what is said from now on
        self.out("target", pick)
        return all_

    def send(self, text):
        if not self.target:
            raise RuntimeError("no Claude Code terminal is running")
        inject.type_into(self.target["pid"], text)

    def poll(self):
        if self.target and not self.path:  # a new session's transcript appears with its first message
            self.path, self.pos = _transcript(self.target["sessionId"]), 0
        if not self.path:
            return
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return
        if size <= self.pos:
            return
        with open(self.path, "rb") as f:
            f.seek(self.pos)
            data = self.partial + f.read(size - self.pos)
        self.pos = size
        *lines, self.partial = data.split(b"\n")
        for line in lines:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") != "assistant" or d.get("isSidechain"):
                continue
            msg = d.get("message") or {}
            for block in msg.get("content") or []:
                if block.get("type") == "text" and block.get("text", "").strip():
                    self.out("text", block["text"])
                elif block.get("type") == "tool_use":
                    detail = json.dumps(block.get("input", {}), ensure_ascii=False)
                    self.out("tool", f"{block.get('name')}: {detail[:140]}")
            if msg.get("stop_reason") == "end_turn":
                self.out("done", "")
