"""Voice for Claude Code - talk to the Claude Code terminal you are using. Double-click to start; no console.

Hold F8 anywhere to talk: your words are typed into your Claude Code terminal (the one you used last,
any project) and its replies are read aloud. Shift+F8 also attaches a screenshot of the window you are
in. F9 stops the voice. Settings (microphone, voice, speed, key, speech model) are in the Settings window
and saved to config.json next to this file.
"""
import ctypes, json, os, queue, sys, threading
import tkinter as tk
from tkinter import ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.stdout = sys.stderr = open(os.path.join(HERE, "app.log"), "a", buffering=1, encoding="utf-8")
sys.path.insert(0, HERE)
import voice_core as vc

CONFIG = os.path.join(HERE, "config.json")
DEFAULTS = {"mic": None, "voice": None, "rate": 1, "ptt": "F8", "lang": None,
            "whisper": "large-v3-turbo", "device": "cuda", "compute": "float16"}
MODELS = ["large-v3-turbo", "small", "base"]  # turbo: best, needs an NVIDIA GPU to be quick
COLORS = {"bg": "#1e1f22", "panel": "#2b2d31", "ink": "#e6e6e6", "dim": "#8a8f98",
          "you": "#7cb7ff", "tool": "#9aa0a6", "err": "#ff7b72", "accent": "#d97757", "ok": "#57ab5a"}


def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG):
        with open(CONFIG, encoding="utf-8") as f:
            cfg.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1)
    return cfg


class App:
    def __init__(self, root, cfg):
        self.root, self.cfg = root, cfg
        self.ui = queue.Queue()          # (kind, payload) from worker threads -> UI thread
        self.stt = None
        self.held = self.transcribing = self.waiting = False
        self.shot = None
        self.reply_open = False          # a reply line is being written in the log
        self.ticks = 0
        self.build_ui()
        self.speaker = vc.Speaker(cfg["voice"], cfg["rate"])  # COM object: UI thread only
        self.split = vc.SentenceSplitter(self.speaker.q)
        self.rec = vc.Recorder(cfg["mic"])
        self.term = vc.ClaudeTerminal(lambda k, t: self.ui.put((k, t)))
        self.term.refresh()
        threading.Thread(target=self.load, daemon=True).start()
        self.tick()

    # ---------- window ----------
    def build_ui(self):
        r, c = self.root, COLORS
        r.title("Voice for Claude Code")
        r.configure(bg=c["bg"])
        r.geometry("520x640")
        r.minsize(380, 360)
        top = tk.Frame(r, bg=c["bg"]); top.pack(fill="x", padx=12, pady=(12, 2))
        self.dot = tk.Canvas(top, width=14, height=14, bg=c["bg"], highlightthickness=0)
        self.dot.pack(side="left"); self.dot_id = self.dot.create_oval(2, 2, 12, 12, fill=c["dim"], outline="")
        self.status = tk.Label(top, text="Loading speech model...", bg=c["bg"], fg=c["ink"], font=("Segoe UI", 11))
        self.status.pack(side="left", padx=8)
        self.on_top = tk.BooleanVar(value=True)
        tk.Checkbutton(top, text="On top", variable=self.on_top, command=self.apply_on_top, bg=c["bg"], fg=c["dim"],
                       selectcolor=c["panel"], activebackground=c["bg"], font=("Segoe UI", 9)).pack(side="right")
        self.speak_on = tk.BooleanVar(value=True)
        tk.Checkbutton(top, text="Voice", variable=self.speak_on, bg=c["bg"], fg=c["dim"], selectcolor=c["panel"],
                       activebackground=c["bg"], font=("Segoe UI", 9)).pack(side="right")
        self.target_lbl = tk.Label(r, text="", bg=c["bg"], fg=c["dim"], font=("Segoe UI", 9), anchor="w")
        self.target_lbl.pack(fill="x", padx=34, pady=(0, 6))

        # bottom rows are packed before the log, so they never get squeezed out
        btns = tk.Frame(r, bg=c["bg"]); btns.pack(side="bottom", fill="x", padx=12, pady=(0, 12))
        for label, cmd in (("Stop voice (F9)", self.speaker_stop), ("Switch terminal", self.switch_terminal),
                           ("Settings", self.open_settings)):
            ttk.Button(btns, text=label, command=cmd).pack(side="left", padx=(0, 6))
        bottom = tk.Frame(r, bg=c["bg"]); bottom.pack(side="bottom", fill="x", padx=12, pady=10)
        self.entry = tk.Entry(bottom, bg=c["panel"], fg=c["ink"], insertbackground=c["ink"], relief="flat",
                              font=("Segoe UI", 10))
        self.entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.entry.bind("<Return>", lambda e: self.send_typed())

        self.log = tk.Text(r, wrap="word", bg=c["panel"], fg=c["ink"], insertbackground=c["ink"], relief="flat",
                           font=("Segoe UI", 10), padx=10, pady=8, state="disabled")
        self.log.pack(fill="both", expand=True, padx=12)
        for tag, kw in (("you", dict(foreground=c["you"], font=("Segoe UI", 10, "bold"))),
                        ("claude", dict(foreground=c["ink"])),
                        ("tool", dict(foreground=c["tool"], font=("Consolas", 9))),
                        ("info", dict(foreground=c["dim"], font=("Segoe UI", 9, "italic"))),
                        ("error", dict(foreground=c["err"], font=("Consolas", 9)))):
            self.log.tag_configure(tag, **kw)
        r.protocol("WM_DELETE_WINDOW", self.close)
        self.apply_on_top()
        self.say("info", f"Hold {self.cfg['ptt']} anywhere to talk to your Claude Code terminal; Shift+"
                         f"{self.cfg['ptt']} also sends a screenshot of the window you are in. F9 stops the voice.")

    def apply_on_top(self):
        self.root.attributes("-topmost", self.on_top.get())

    def say(self, tag, text, newline=True):
        self.log.configure(state="normal")
        self.log.insert("end", text + ("\n" if newline else ""), tag)
        self.log.configure(state="disabled")
        self.log.see("end")

    def set_state(self, text, color):
        self.status.configure(text=text)
        self.dot.itemconfigure(self.dot_id, fill=color)

    # ---------- startup ----------
    def load(self):
        try:
            model, note = vc.load_stt(self.cfg)
            self.stt = model
            if note:
                self.ui.put(("info", note))
        except Exception as e:
            self.ui.put(("error", f"speech model failed: {e}"))

    # ---------- actions ----------
    def send(self, text, shown):
        try:
            self.term.send(f"{vc.VOICE_TAG} {text}")
        except Exception as e:
            self.say("error", f"could not reach Claude Code: {e}")
            return
        self.say("you", "You: " + shown)
        self.reply_open, self.waiting = False, True

    def send_typed(self):
        text = self.entry.get().strip()
        self.entry.delete(0, "end")
        if text:
            self.send(text, text)

    def speaker_stop(self):
        self.speaker.stop()

    def switch_terminal(self):
        all_ = vc.terminals()
        if len(all_) < 2:
            self.say("info", "Only one Claude Code terminal is running.")
            return
        cur = self.term.target["pid"] if self.term.target else None
        pids = [t["pid"] for t in all_]
        self.term.pinned = pids[(pids.index(cur) + 1) % len(pids)] if cur in pids else pids[0]
        self.term.refresh()

    def open_settings(self):
        c = COLORS
        w = tk.Toplevel(self.root)
        w.title("Settings")
        w.configure(bg=c["bg"], padx=16, pady=14)
        w.transient(self.root)
        w.attributes("-topmost", True)
        mics = ["Windows default"] + [n for _, n in vc.microphones()]
        fields = (("Microphone", mics, self.cfg["mic"] or "Windows default"),
                  ("Voice", self.speaker.voices(), self.speaker.v.Voice.GetDescription()),
                  ("Push-to-talk key", vc.PTT_KEYS, self.cfg["ptt"]),
                  ("Speech model", MODELS, self.cfg["whisper"]))
        boxes = {}
        for row, (label, values, cur) in enumerate(fields):
            tk.Label(w, text=label, bg=c["bg"], fg=c["ink"], font=("Segoe UI", 10)).grid(row=row, column=0, sticky="w", pady=4)
            b = ttk.Combobox(w, values=values, state="readonly", width=38)
            b.set(cur)
            b.grid(row=row, column=1, sticky="ew", padx=(10, 0), pady=4)
            boxes[label] = b
        tk.Label(w, text="Speed", bg=c["bg"], fg=c["ink"], font=("Segoe UI", 10)).grid(row=4, column=0, sticky="w", pady=4)
        speed = tk.Scale(w, from_=-5, to=10, orient="horizontal", bg=c["bg"], fg=c["ink"], highlightthickness=0,
                         troughcolor=c["panel"], length=260)
        speed.set(self.cfg["rate"])
        speed.grid(row=4, column=1, sticky="w", padx=(10, 0))
        tk.Label(w, text="F9 always stops the voice. A new speech model loads at the next start.", bg=c["bg"],
                 fg=c["dim"], font=("Segoe UI", 9)).grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 4))

        def save():
            mic = boxes["Microphone"].get()
            new = dict(self.cfg, mic=None if mic == "Windows default" else mic, voice=boxes["Voice"].get(),
                       ptt=boxes["Push-to-talk key"].get(), whisper=boxes["Speech model"].get(), rate=int(speed.get()))
            model_changed = new["whisper"] != self.cfg["whisper"]
            self.cfg.update(new)
            with open(CONFIG, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, indent=1)
            self.rec.mic = self.cfg["mic"]
            self.speaker.set_voice(self.cfg["voice"])
            self.speaker.v.Rate = self.cfg["rate"]
            self.say("info", f"Settings saved. Hold {self.cfg['ptt']} to talk."
                     + (" The new speech model loads next time you open the app." if model_changed else ""))
            w.destroy()

        ttk.Button(w, text="Save", command=save).grid(row=6, column=1, sticky="e", pady=(8, 0))

    def transcribe_bg(self, audio, shot):
        text = vc.transcribe(self.stt, audio, self.cfg["lang"]) if audio.size >= vc.SR_IN * vc.MIN_SECONDS else ""
        self.ui.put(("heard", (text, shot)))

    def close(self):
        self.root.withdraw()
        self.speaker.stop()
        self.root.destroy()

    # ---------- main loop (UI thread, every 20 ms) ----------
    def tick(self):
        key = lambda vk: ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000
        self.ticks += 1
        if self.ticks % 100 == 0:                       # every 2 s: follow the terminal you use
            self.term.refresh()
        if self.ticks % 10 == 0:                        # every 0.2 s: new reply text
            self.term.poll()

        if self.speak_on.get():
            self.speaker.pump()
        else:
            while not self.speaker.q.empty():
                self.speaker.q.get_nowait()
        if key(vc.VK["F9"]):
            self.speaker.stop()

        if self.stt is not None:
            ptt = vc.VK[self.cfg["ptt"]]
            if key(ptt) and not self.held:
                self.held = True
                self.speaker.stop()
                self.shot = None
                if key(vc.VK["SHIFT"]):
                    try:
                        self.shot = vc.foreground_shot()
                    except Exception as e:
                        self.say("error", f"screenshot failed: {e}")
                self.rec.start()
                self.set_state("Listening" + (" + screenshot" if self.shot else "") + "...", "#e5534b")
            elif self.held and not key(ptt):
                self.held, self.transcribing = False, True
                self.set_state("Transcribing...", COLORS["accent"])
                threading.Thread(target=self.transcribe_bg, args=(self.rec.stop(), self.shot), daemon=True).start()

        while not self.ui.empty():
            kind, data = self.ui.get_nowait()
            if kind == "text":
                if not self.reply_open:
                    self.say("claude", "Claude: ", newline=False)
                    self.reply_open = True
                self.say("claude", data.strip() + "\n", newline=False)
                self.split.feed(data + "\n")
                self.split.flush()
            elif kind == "tool":
                self.say("tool", "  > " + data)
            elif kind == "done":
                self.reply_open, self.waiting = False, False
            elif kind == "heard":
                spoken, shot = data
                self.transcribing = False
                if not spoken:
                    self.say("info", "(heard nothing)")
                elif shot:
                    self.send(f"{spoken} [screenshot of the window I'm in ({shot[0]}): {shot[1]}]",
                              spoken + "  [+ screenshot]")
                else:
                    self.send(spoken, spoken)
            elif kind == "target":
                if data:
                    proj = os.path.basename(data.get("cwd", "")) or data.get("cwd", "")
                    self.target_lbl.configure(text=f"Talking to: Claude Code in {proj}  (session {data['sessionId'][:8]})")
                else:
                    self.target_lbl.configure(text="No Claude Code terminal running - open one and I will find it")
            else:
                self.say(kind if kind in ("info", "error") else "info", data)

        if not self.held and not self.transcribing:
            if self.stt is None:
                self.set_state("Loading speech model...", COLORS["dim"])
            elif not self.term.target:
                self.set_state("Waiting for a Claude Code terminal", COLORS["dim"])
            elif self.speaker.speaking():
                self.set_state("Speaking (F9 stops)", COLORS["ok"])
            elif self.waiting:
                self.set_state("Claude is working...", COLORS["accent"])
            else:
                self.set_state(f"Ready - hold {self.cfg['ptt']} to talk", COLORS["ok"])
        self.root.after(20, self.tick)


def main():
    ctypes.windll.kernel32.CreateMutexW(None, False, "ClaudeVoiceSingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(None, "Voice for Claude Code is already running.", "Voice for Claude Code", 0x40)
        return
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    root = tk.Tk()
    App(root, load_config())
    root.after(300, lambda: (root.deiconify(), root.lift()))  # Windows may start it minimized when launched from the background
    root.mainloop()


if __name__ == "__main__":
    main()
