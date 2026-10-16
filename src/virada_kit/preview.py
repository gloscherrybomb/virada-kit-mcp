"""Previews: a kit on the game's riders, without a 3D engine. Each view of each body was baked once (in the game's
asset pipeline) into per-pixel lookups: where the pixel falls on the jersey and bib sheets, the body's own cut there
(kit zones, zip, pockets, drawn seams and hems, silicone dots), the bare skin, the light and the ink outline. A
preview is those lookups filled from a design's sheets, in the game's comic look (flat light and designed shadow).
"""
import json, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from .sheets import DATA
from .shade import shadow_of

VIEWS_DIR = os.path.join(DATA, 'views')
BODIES = {'male': 'regular_male', 'female': 'regular_female'}
VIEWS = ('front', 'front34_left', 'left', 'back', 'right', 'front34_right')
import collections, threading
_cache = collections.OrderedDict(); _lock = threading.Lock()
CACHE_VIEWS = 4              # each view unpacked is ~20 MB: keep the few last used (a preview uses three), not all 12

def _view(body, view):
    key = (body, view)
    with _lock:
        if key in _cache: _cache.move_to_end(key); return _cache[key]
    P = dict(np.load(os.path.join(VIEWS_DIR, BODIES.get(body, body), view + '.npz')))
    with _lock:
        _cache[key] = P
        while len(_cache) > CACHE_VIEWS: _cache.popitem(last=False)
    return P

def available():
    return {b: sorted(f[:-4] for f in os.listdir(os.path.join(VIEWS_DIR, d)) if f.endswith('.npz'))
            for b, d in BODIES.items() if os.path.isdir(os.path.join(VIEWS_DIR, d))}

def _sample(sheet, m):
    """Colours of a sheet at 16-bit map values (0 = not on this sheet), bilinear."""
    on = m[..., 0] > 0
    sx = (m[..., 0][on].astype(np.float64) - 1) / 65534 * sheet.shape[1] - 0.5
    sy = (m[..., 1][on].astype(np.float64) - 1) / 65534 * sheet.shape[0] - 0.5
    x0 = np.clip(np.floor(sx).astype(int), 0, sheet.shape[1] - 2); y0 = np.clip(np.floor(sy).astype(int), 0, sheet.shape[0] - 2)
    fx = np.clip(sx - x0, 0, 1)[:, None]; fy = np.clip(sy - y0, 0, 1)[:, None]
    c = (sheet[y0, x0] * (1 - fx) * (1 - fy) + sheet[y0, x0 + 1] * fx * (1 - fy) + sheet[y0 + 1, x0] * (1 - fx) * fy
         + sheet[y0 + 1, x0 + 1] * fx * fy)
    out = np.zeros(m.shape[:2] + (3,), np.float32); out[on] = c
    return out, on

def render_view(jersey_sheet, bib_sheet, body='male', view='front34_left', zip_colour=(0.13, 0.15, 0.22), dots=None,
                sock=(0.96, 0.95, 0.92), hair=(0.33, 0.23, 0.16), background=(0.86, 0.88, 0.9)):
    """One view of a kit on a rider: (1024, 768, 3) float designer sRGB."""
    P = _view(body, view); f = lambda k: P[k].astype(np.float32) / 255.0
    on = P['alpha'] > 127; skin = f('skin')
    lit = skin.copy(); shadow = shadow_of(skin, 'skin')
    def lay(c, col):
        sel = c > 0; k = c[sel][:, None]; col = np.asarray(col, np.float32)
        cc = col if col.ndim == 1 else col[sel]; sh = shadow_of(cc, 'cloth')
        lit[sel] = lit[sel] * (1 - k) + cc * k; shadow[sel] = shadow[sel] * (1 - k) + sh * k
    zones, extra, lines, dts = f('zones'), f('extra'), f('lines'), f('dots')
    jc, jon = _sample(jersey_sheet, P['jmap']); bc, bon = _sample(bib_sheet, P['bmap'])
    lay(zones[..., 0] * jon, jc); lay(extra[..., 0], zip_colour); lay(zones[..., 1] * bon, bc)
    lay(zones[..., 2], sock); lay(extra[..., 1], hair)
    dots = dots or {}
    for ch, key, lift in ((0, 'cuff', 0.75), (1, 'gripper', 0.2)):
        sel = dts[..., ch] > 0; k = dts[..., ch][sel][:, None]
        col = np.asarray(dots[key], np.float32) if dots.get(key) else lit[sel] + (1 - lit[sel]) * lift
        sh = shadow_of(col, 'cloth'); lit[sel] = lit[sel] * (1 - k) + col * k; shadow[sel] = shadow[sel] * (1 - k) + sh * k
    ps = (extra[..., 2] * 0.35)[..., None]; lit *= 1 - ps; shadow *= 1 - ps * 0.6
    cloth = np.maximum.reduce([zones[..., 0], zones[..., 1], zones[..., 2], extra[..., 0], extra[..., 1]])
    lc = (lines[..., 0] * (cloth > 0.5))[..., None]; lit = lit * (1 - lc * 0.58); shadow = shadow * (1 - lc * 0.58)
    sl = (lines[..., 1] * 0.85)[..., None]; lit = lit * (1 - sl * 0.45); shadow = shadow * (1 - sl * 0.45)
    # the comic look's light: hard on cloth, soft on skin
    # the light comes from the camera's side, a little left and above, so the kit reads flat with shade at its turns
    meta = json.load(open(os.path.join(VIEWS_DIR, BODIES.get(body, body), 'views.json')))
    a = np.radians(meta['views'][view]); c = np.array([np.cos(a), np.sin(a), 0.0]); left = np.cross([0, 0, 1.0], c)
    Ld = c * 0.8 + left * 0.3 + np.array([0, 0, 0.55]); Ld /= np.linalg.norm(Ld)
    n = f('normal') * 2 - 1; L = np.clip(n @ Ld, 0, 1); th = 0.22
    hard = (L > th).astype(np.float32); soft = np.clip((L - th + 0.1) / 0.2, 0, 1)
    k = (hard * cloth + soft * (1 - cloth))[..., None]
    col = shadow * (1 - k) + lit * k
    ink = f('ink')[..., None]; col = col * (1 - ink) + np.array([0.14, 0.12, 0.2], np.float32) * ink
    out = np.zeros(col.shape, np.float32) + np.array(background, np.float32)
    out[on] = col[on]
    edge = (ink[..., 0] > 0.5) & ~on; out[edge] = [0.14, 0.12, 0.2]
    return out

def crop_to_kit(img, body, view, margin=0.06, jersey_only=False):
    """The view cropped to the kit (jersey and bibs; or the jersey alone), as product pictures frame it."""
    z = _view(body, view)['zones']
    m = (z[..., 0] > 127) if jersey_only else ((z[..., 0] > 127) | (z[..., 1] > 127))
    ys, xs = np.nonzero(m)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max(); my, mx = int((y1 - y0) * margin), int((x1 - x0) * margin)
    return img[max(0, y0 - my):y1 + my, max(0, x0 - mx):x1 + mx]

def grid_overlay(img, body, view, colour=(0.0, 0.75, 0.85)):
    """The FRONT and BACK panels' own coordinates drawn on the rider: a thin line every 0.1 of u and v, a thicker one at
    u = 0.5, so sizes and places can be read off a preview and set against a reference picture."""
    P = _view(body, view); m = P['jmap']; on = m[..., 0] > 0
    sx = (m[..., 0].astype(np.float64) - 1) / 65534; sy = (m[..., 1].astype(np.float64) - 1) / 65534
    torso = on & (sy < 0.5)                                         # FRONT and BACK fill the jersey sheet's top half
    u = np.where(sx < 0.5, sx * 2, sx * 2 - 1); v = 1 - sy * 2
    out = img.copy(); c = np.array(colour, np.float32)
    for q, width in ((u, 0.007), (v, 0.006)):
        d = np.abs(q * 10 - np.round(q * 10)) / 10
        ln = torso & (d < width / 2)
        out[ln] = out[ln] * 0.6 + c * 0.4
    mid = torso & (np.abs(u - 0.5) < 0.004); out[mid] = out[mid] * 0.3 + c * 0.7
    return out

def _font(size):
    return ImageFont.truetype(os.path.join(DATA, 'fonts', 'Montserrat.ttf'), size)

def sheet_of_views(images, labels, cols=3, scale=0.5):
    """Several views side by side with a label each: a PIL image."""
    ims = [Image.fromarray((np.clip(i, 0, 1) * 255 + 0.5).astype(np.uint8)) if not isinstance(i, Image.Image) else i.convert('RGB') for i in images]
    w = int(768 * scale); h = int(1024 * scale); rows = (len(ims) + cols - 1) // cols
    S = Image.new('RGB', (cols * w, rows * (h + 28)), (245, 245, 242)); d = ImageDraw.Draw(S); f = _font(18)
    for k, (im, lab) in enumerate(zip(ims, labels)):
        x, y = (k % cols) * w, (k // cols) * (h + 28)
        t = im.copy(); t.thumbnail((w, h)); S.paste(t, (x + (w - t.width) // 2, y + 28 + (h - t.height) // 2))
        d.text((x + 8, y + 4), lab, fill=(30, 30, 30), font=f)
    return S
