"""Screenshot for Claude: the window you are in, a window by title, or the whole screen.

    python look.py                       foreground window
    python look.py --window "FMOD"       first visible window whose title contains "FMOD"
    python look.py --screen              all monitors
    python look.py --region 0.5,0,1,0.5  zoom: crop to fractions x0,y0,x1,y1 of the capture
    python look.py --list                list visible window titles

Prints the JPEG path (long edge <= --max px) for the Read tool. Windows captured by title use
PrintWindow, so they come out right even when another window covers them.
"""
import argparse, ctypes, glob, os, sys, time
from ctypes import wintypes
from PIL import Image, ImageGrab

user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
ctypes.windll.shcore.SetProcessDpiAwareness(2)  # real pixel coordinates on scaled displays
sys.stdout.reconfigure(encoding="utf-8")         # window titles can hold any script (e.g. Azerbaijani)
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")
KEEP = 30


def title(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def visible_windows():
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd) and title(hwnd).strip():
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found


def rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def print_window(hwnd):
    """Capture a window's own pixels (PW_RENDERFULLCONTENT also handles GPU-drawn windows)."""
    l, t, r, b = rect(hwnd)
    w, h = r - l, b - t
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    ok = user32.PrintWindow(hwnd, mem, 2)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    bi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp); gdi32.DeleteDC(mem); user32.ReleaseDC(hwnd, hdc)
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    return img if ok and img.getbbox() else None


def capture(args):
    if args.screen:
        return ImageGrab.grab(all_screens=True), "all screens"
    if args.window:
        hits = [h for h in visible_windows() if args.window.lower() in title(h).lower()]
        if not hits:
            sys.exit(f"no visible window title contains '{args.window}' (try --list)")
        hwnd = hits[0]
        img = print_window(hwnd)
        if img is not None:
            return img, title(hwnd)
    else:
        hwnd = user32.GetForegroundWindow()
    return ImageGrab.grab(bbox=rect(hwnd), all_screens=True), title(hwnd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window"); ap.add_argument("--screen", action="store_true")
    ap.add_argument("--region", help="x0,y0,x1,y1 as fractions of the capture")
    ap.add_argument("--max", type=int, default=900, help="longest edge in px")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        for h in visible_windows():
            l, t, r, b = rect(h)
            print(f"{r - l}x{b - t}  {title(h)}")
        return

    img, name = capture(args)
    if args.region:
        x0, y0, x1, y1 = (float(v) for v in args.region.split(","))
        W, H = img.size
        img = img.crop((int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)))
    full = img.size
    img.thumbnail((args.max, args.max))

    os.makedirs(SHOTS, exist_ok=True)
    path = os.path.join(SHOTS, time.strftime("shot_%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}.jpg")
    img.convert("RGB").save(path, "JPEG", quality=60)  # small: big images are blocked from Read
    for old in sorted(glob.glob(os.path.join(SHOTS, "shot_*.*")))[:-KEEP]:
        os.remove(old)
    print(f"{path}  ({name}; captured {full[0]}x{full[1]}, saved {img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
