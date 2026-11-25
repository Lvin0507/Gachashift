"""Find a launcher's start button in a picture of its window, so it can be clicked without
calibrating by hand (and still be found after the window or the screen changes).

Every launcher Gachashift clicks (HoYoPlay, Kuro's launcher, the Blue Archive JP launcher)
has a big, evenly coloured, wide button in its lower right, while the rest of the window is
game art. So the search keeps strongly coloured pixels in that corner, joins neighbours of the
same colour into shapes, and takes the largest shape that is solid and button-shaped."""

import ctypes
import math
from collections import deque

# Only the lower right of the window is searched (fractions of its width and height)
AREA_X, AREA_Y = 0.45, 0.5
MIN_SATURATION, MIN_VALUE = 0.35, 120
SAME_HUE, SAME_VALUE = 10, 30      # degrees and 0-255: how close to the shape's first pixel
MIN_SHARE, MAX_SHARE = 0.002, 0.08  # of the whole picture
MAX_SPREAD = 15                    # buttons are one flat colour: hue and value barely change
MIN_FILL = 0.6                     # of its bounding box: art is ragged, buttons are solid
MIN_ASPECT, MAX_ASPECT = 1.5, 8.0  # width / height


def _hsv(rgb):
    r, g, b = rgb
    high, low = max(r, g, b), min(r, g, b)
    saturation = (high - low) / high if high else 0
    if high == low:
        hue = 0.0
    elif high == r:
        hue = (60 * (g - b) / (high - low)) % 360
    elif high == g:
        hue = 60 * (b - r) / (high - low) + 120
    else:
        hue = 60 * (r - g) / (high - low) + 240
    return hue, saturation, high


def _close(a, b):
    hue = abs(a[0] - b[0])
    return min(hue, 360 - hue) <= SAME_HUE and abs(a[2] - b[2]) <= SAME_VALUE


def _flat(colours):
    """True when nearly every pixel of a shape has the same hue and brightness."""
    def spread(values):
        values = sorted(values)
        return values[int(len(values) * 0.9)] - values[int(len(values) * 0.1)]
    hues = [c[0] for c in colours]
    centre = hues[len(hues) // 2]
    # hue is circular: measure each one's distance from a hue in the shape
    offsets = [((h - centre + 180) % 360) - 180 for h in hues]
    return spread(offsets) <= MAX_SPREAD and spread([c[2] for c in colours]) <= MAX_SPREAD * 2


def find_button(pixels, width, height):
    """(x, y) fractions of the start button's centre in a picture given as a row-major list of
    (r, g, b), or None when nothing button-like is there."""
    x0, y0 = int(width * AREA_X), int(height * AREA_Y)
    colour = {}
    for y in range(y0, height):
        for x in range(x0, width):
            hsv = _hsv(pixels[y * width + x])
            if hsv[1] >= MIN_SATURATION and hsv[2] >= MIN_VALUE:
                colour[(x, y)] = hsv
    def interior(spot):
        """A pixel inside a flat patch: its neighbours all have its colour. Shapes start only
        from these, so a shape takes its colour from the middle of a button, not a stray
        pixel of art next to it."""
        x, y = spot
        return all(n in colour and _close(colour[spot], colour[n])
                   for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))

    seen, best = set(), None
    for start in colour:
        if start in seen or not interior(start):
            continue
        seen.add(start)
        shape, queue = [start], deque([start])
        while queue:
            x, y = queue.popleft()
            for spot in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if spot in colour and spot not in seen and _close(colour[start], colour[spot]):
                    seen.add(spot)
                    shape.append(spot)
                    queue.append(spot)
        xs, ys = [p[0] for p in shape], [p[1] for p in shape]
        w, h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        # a shape cut off by the edge of the searched area is part of something bigger
        inside = min(xs) > x0 and min(ys) > y0 and max(xs) < width - 1 and max(ys) < height - 1
        if (inside and MIN_SHARE * width * height <= len(shape) <= MAX_SHARE * width * height
                and h >= 3 and len(shape) / (w * h) >= MIN_FILL
                and MIN_ASPECT <= w / h <= MAX_ASPECT and _flat([colour[p] for p in shape])):
            if best is None or len(shape) > best[0]:
                best = (len(shape), (min(xs) + max(xs) + 1) / 2, (min(ys) + max(ys) + 1) / 2)
    if best is None:
        return None
    return round(best[1] / width, 3), round(best[2] / height, 3)


def far_apart(a, b, distance=0.03):
    return a is not None and b is not None and math.dist(a, b) > distance


# --- taking the picture -------------------------------------------------------------------

class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16),
                ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32),
                ("biXPelsPerMeter", ctypes.c_int32), ("biYPelsPerMeter", ctypes.c_int32),
                ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]


def grab_client(hwnd, max_width=192):
    """(pixels, width, height) of a window's client area as it is on screen, scaled down to at
    most max_width pixels across. The window must be in front (it is read off the screen)."""
    from ctypes import wintypes
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    w, h = rect.right, rect.bottom
    if w <= 0 or h <= 0:
        return None
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    user32.GetDC.restype = wintypes.HDC
    screen = user32.GetDC(None)
    memory = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateCompatibleBitmap(screen, w, h)
    old = gdi32.SelectObject(memory, bitmap)
    try:
        gdi32.BitBlt(memory, 0, 0, w, h, screen, origin.x, origin.y, 0x00CC0020 | 0x40000000)
        header = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buffer = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(memory, bitmap, 0, h, buffer, ctypes.byref(header), 0):
            return None
    finally:
        gdi32.SelectObject(memory, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(None, screen)
    data = buffer.raw
    step = max(1, math.ceil(w / max_width))
    sw, sh = w // step, h // step
    pixels = []
    for y in range(sh):
        row = y * step * w
        for x in range(sw):
            i = (row + x * step) * 4
            pixels.append((data[i + 2], data[i + 1], data[i]))  # BGRA -> RGB
    return pixels, sw, sh


def find_in_window(hwnd):
    """The start button of a launcher window that is in front, or None."""
    try:
        picture = grab_client(hwnd)
    except Exception as e:
        print(f"could not look at the launcher window: {type(e).__name__}: {e}")
        return None
    return find_button(*picture) if picture else None
