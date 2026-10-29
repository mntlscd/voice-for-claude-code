"""Type text into a running Claude Code window from outside, without focusing it.

Attaches to the Claude process's console and writes key events into its input buffer, as if
the user had typed them there (works for Windows Terminal / conhost tabs; no focus, no clipboard).
"""
import ctypes
from ctypes import wintypes

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
KEY_EVENT, VK_RETURN = 0x0001, 0x0D


class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [("bKeyDown", wintypes.BOOL), ("wRepeatCount", wintypes.WORD),
                ("wVirtualKeyCode", wintypes.WORD), ("wVirtualScanCode", wintypes.WORD),
                ("UnicodeChar", wintypes.WCHAR), ("dwControlKeyState", wintypes.DWORD)]


class INPUT_RECORD(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("KeyEvent", KEY_EVENT_RECORD), ("_pad", ctypes.c_byte * 16)]
    _fields_ = [("EventType", wintypes.WORD), ("Event", _U)]


def _records(text, enter):
    recs = []
    for ch in text:
        for down in (True, False):
            r = INPUT_RECORD()
            r.EventType = KEY_EVENT
            r.Event.KeyEvent = KEY_EVENT_RECORD(down, 1, 0, 0, ch, 0)
            recs.append(r)
    if enter:
        for down in (True, False):
            r = INPUT_RECORD()
            r.EventType = KEY_EVENT
            r.Event.KeyEvent = KEY_EVENT_RECORD(down, 1, VK_RETURN, 0x1C, "\r", 0)
            recs.append(r)
    return recs


def type_into(pid, text, enter=True):
    """Write `text` (+ Enter) into the console that process `pid` is attached to."""
    k32.FreeConsole()
    if not k32.AttachConsole(pid):
        raise OSError(f"cannot attach to the console of pid {pid} (error {ctypes.get_last_error()})")
    try:
        GENERIC_RW, SHARE_RW, OPEN_EXISTING = 0xC0000000, 0x3, 3
        k32.CreateFileW.restype = wintypes.HANDLE
        h = k32.CreateFileW("CONIN$", GENERIC_RW, SHARE_RW, None, OPEN_EXISTING, 0, None)
        if h in (None, wintypes.HANDLE(-1).value):
            raise OSError(f"cannot open console input (error {ctypes.get_last_error()})")
        recs = _records(text, enter=False)
        arr = (INPUT_RECORD * len(recs))(*recs)
        n = wintypes.DWORD()
        k32.WriteConsoleInputW(h, arr, len(recs), ctypes.byref(n))
        if enter:  # a separate write, so the UI sees typing first and then the Enter key
            import time
            time.sleep(0.15)
            er = _records("", enter=True)
            k32.WriteConsoleInputW(h, (INPUT_RECORD * len(er))(*er), len(er), ctypes.byref(n))
        k32.CloseHandle(h)
        return n.value
    finally:
        k32.FreeConsole()
