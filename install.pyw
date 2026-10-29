"""Install Voice for Claude Code: double-click this file (Windows, Python 3.10+). No console window.

Installs the Python packages (and NVIDIA's CUDA libraries for fast GPU speech recognition if you have an
NVIDIA card), adds the [voice] rule to your Claude Code instructions (~/.claude/CLAUDE.md), and makes
Desktop / Start menu shortcuts to voice_app.pyw. Safe to run again: it updates instead of duplicating.
"""
import os, re, shutil, subprocess, sys, threading
import tkinter as tk
from tkinter import ttk

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "voice_app.pyw")
RULE_FILE = os.path.join(HERE, "VOICE_RULE.md")
CLAUDE_MD = os.path.join(os.path.expanduser("~"), ".claude", "CLAUDE.md")
START, END = "<!-- voice-for-claude-code:start -->", "<!-- voice-for-claude-code:end -->"
NAME = "Voice for Claude Code"
NO_WINDOW = 0x08000000
GPU_PACKAGES = ["nvidia-cublas-cu12", "nvidia-cudnn-cu12>=9,<10"]


def pythonw():
    p = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return p if os.path.exists(p) else sys.executable


def python_exe():
    p = os.path.join(os.path.dirname(sys.executable), "python.exe")
    return p if os.path.exists(p) else sys.executable


def has_nvidia():
    try:
        return subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, creationflags=NO_WINDOW,
                              timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def add_rule():
    """Put the [voice] rule between markers in ~/.claude/CLAUDE.md (replaces an older copy of the block)."""
    rule = open(RULE_FILE, encoding="utf-8").read().replace("{LOOK}", os.path.join(HERE, "look.py")).strip()
    os.makedirs(os.path.dirname(CLAUDE_MD), exist_ok=True)
    text = open(CLAUDE_MD, encoding="utf-8").read() if os.path.exists(CLAUDE_MD) else ""
    block = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if block.search(text):
        text = block.sub(lambda m: rule, text)
    else:
        text = text.rstrip() + ("\n\n" if text.strip() else "") + rule + "\n"
    with open(CLAUDE_MD, "w", encoding="utf-8") as f:
        f.write(text)


def make_shortcut(folder):
    """A .lnk to voice_app.pyw via Windows' own WScript.Shell (PowerShell, hidden)."""
    lnk = os.path.join(folder, NAME + ".lnk")
    ps = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:VFCC_LNK); "
          "$s.TargetPath = $env:VFCC_TARGET; $s.Arguments = '\"' + $env:VFCC_APP + '\"'; "
          "$s.WorkingDirectory = $env:VFCC_DIR; $s.IconLocation = \"$env:SystemRoot\\System32\\SndVol.exe,0\"; "
          "$s.Description = 'Talk to Claude Code (hold F8)'; $s.Save()")
    env = dict(os.environ, VFCC_LNK=lnk, VFCC_TARGET=pythonw(), VFCC_APP=APP, VFCC_DIR=HERE)
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env=env,
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-300:])
    return lnk


def special_folder(name):
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                        f"[Environment]::GetFolderPath('{name}')"], capture_output=True, text=True,
                       creationflags=NO_WINDOW)
    return r.stdout.strip()


class Installer:
    def __init__(self, root):
        self.root = root
        root.title("Install " + NAME)
        root.geometry("640x520")
        root.minsize(520, 420)
        frm = ttk.Frame(root, padding=14)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=NAME, font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(frm, text="Talk to the Claude Code terminal you are using: hold a key, speak, hear the answer.",
                  font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 10))
        gpu = has_nvidia()
        self.opt = {k: tk.BooleanVar(value=v) for k, v in
                    (("gpu", gpu), ("rule", True), ("desktop", True), ("startmenu", True))}
        for key, text in (("gpu", "Use my NVIDIA GPU for speech recognition (large download, about 1 GB)"
                           + ("" if gpu else "  - no NVIDIA GPU found")),
                          ("rule", "Add the [voice] rule to my Claude Code instructions (~/.claude/CLAUDE.md)"),
                          ("desktop", "Desktop shortcut"), ("startmenu", "Start menu shortcut")):
            ttk.Checkbutton(frm, text=text, variable=self.opt[key]).pack(anchor="w", pady=1)
        self.log = tk.Text(frm, height=14, wrap="word", font=("Consolas", 9), relief="flat", background="#f4f4f4")
        self.log.pack(fill="both", expand=True, pady=10)
        row = ttk.Frame(frm); row.pack(fill="x")
        self.go = ttk.Button(row, text="Install", command=self.start)
        self.go.pack(side="right")
        self.open_btn = ttk.Button(row, text="Open " + NAME, command=self.launch, state="disabled")
        self.open_btn.pack(side="right", padx=8)
        self.checks()

    def say(self, text):
        self.root.after(0, lambda: (self.log.insert("end", text + "\n"), self.log.see("end")))

    def checks(self):
        v = sys.version_info
        self.say(f"Python {v.major}.{v.minor}.{v.micro}: " + ("OK" if v >= (3, 10) else "too old, install Python 3.10 or newer"))
        self.say("Claude Code: " + ("found" if shutil.which("claude") else
                                    "NOT found on PATH. Install Claude Code first (https://claude.com/claude-code)."))
        self.say("Windows only. Press Install when ready.")

    def start(self):
        self.go.configure(state="disabled")
        threading.Thread(target=self.run, daemon=True).start()

    def pip(self, args):
        cmd = [python_exe(), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade"] + args
        self.say("> pip install " + " ".join(args))
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                             errors="replace", creationflags=NO_WINDOW)
        for line in p.stdout:
            if line.startswith(("Successfully", "ERROR", "Collecting", "Requirement already")):
                self.say("  " + line.rstrip()[:110])
        if p.wait() != 0:
            raise RuntimeError("pip failed (see above)")

    def run(self):
        try:
            self.pip(["-r", os.path.join(HERE, "requirements.txt")])
            if self.opt["gpu"].get():
                self.pip(GPU_PACKAGES)
            if self.opt["rule"].get():
                add_rule()
                self.say(f"[voice] rule written to {CLAUDE_MD}")
            for key, folder in (("desktop", "Desktop"), ("startmenu", "Programs")):
                if self.opt[key].get():
                    self.say("Shortcut: " + make_shortcut(special_folder(folder)))
            self.say("\nDone. Open the app, then open Claude Code in any project. Hold F8 and talk.\n"
                     "The first start downloads the speech model, so it takes a few minutes once.")
            self.root.after(0, lambda: self.open_btn.configure(state="normal"))
        except Exception as e:
            self.say(f"\nInstall stopped: {e}")
            self.root.after(0, lambda: self.go.configure(state="normal"))

    def launch(self):
        subprocess.Popen([pythonw(), APP], cwd=HERE, creationflags=NO_WINDOW)
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    Installer(root)
    root.mainloop()
