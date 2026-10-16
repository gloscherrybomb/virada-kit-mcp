"""The kit format's design sheets: the layout and the layer renderer.

A kit is two flat pictures, the same for every body: the JERSEY sheet (2048 x 2048: front, back, two sleeves, collar)
and the BIB sheet (2048 x 1024: two legs), laid out in panels like a sublimation print template. A design is either
such a picture (painted by any tool, or by an image model) or a list of layers this module draws on the sheet.

Panels (u across, v up the body unless said; both 0..1 of the panel):
  front     seen from the front: u from the rider's right side seam to the left one; v from the lowest hem to the
            shoulders
  back      seen from behind: u from the rider's left side seam to the right one (so FRONT|BACK side by side runs on
            round the left side); v hem to shoulders
  sleeve_r  the right sleeve seen from the right, hanging: the top of the arm down the middle, the underseam at both
            edges; v from the armhole (TOP of the panel, v = 0) to the hem (bottom, v = 1)
  sleeve_l  the left sleeve, the same seen from the left
  collar    the band round the neck seen from the front: the front of the neck in the middle, the back at both ends;
            v from the seam (0) to the top edge (1)
  leg_r     the right bib leg seen from the right: the outside of the leg down the middle, the inside seam at both
            edges; v from the gripper hem (0) to the waist (1)
  leg_l     the left leg, the same seen from the left
"""
import json, math, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
LAYOUT = {
    'jersey': {'size': [2048, 2048], 'panels': {
        'front':    {'rect': [0, 0, 1024, 1024], 'v_up': True},
        'back':     {'rect': [1024, 0, 1024, 1024], 'v_up': True},
        'sleeve_r': {'rect': [0, 1024, 1024, 512], 'v_up': False},
        'sleeve_l': {'rect': [1024, 1024, 1024, 512], 'v_up': False},
        'collar':   {'rect': [0, 1536, 2048, 128], 'v_up': True}}},
    'bib': {'size': [2048, 1024], 'panels': {
        'leg_r': {'rect': [0, 0, 1024, 1024], 'v_up': True},
        'leg_l': {'rect': [1024, 0, 1024, 1024], 'v_up': True}}},
}
PANEL_SHEET = {p: s for s, L in LAYOUT.items() for p in L['panels']}
FONTS = {'Montserrat': 'Montserrat.ttf', 'Oswald': 'Oswald.ttf'}      # OFL, in data/fonts
LAYER_TYPES = ('fill', 'gradient', 'band', 'u_band', 'edges', 'chevron', 'stripes', 'dots', 'shape', 'line', 'text', 'image')

def to_sheet(panel, u, v):
    """Panel (u, v) to the sheet's (x, y), 0..1 from its top-left corner."""
    L = LAYOUT[PANEL_SHEET[panel]]; W, H = L['size']; x0, y0, w, h = L['panels'][panel]['rect']
    vv = (1 - v) if L['panels'][panel]['v_up'] else v
    return (x0 + np.clip(u, 0, 1) * w) / W, (y0 + np.clip(vv, 0, 1) * h) / H

def panel_grid(sheet, panel):
    """(u, v) at every pixel of a panel, and its rect."""
    L = LAYOUT[sheet]; x0, y0, w, h = L['panels'][panel]['rect']
    u = (np.arange(w) + 0.5) / w; r = (np.arange(h) + 0.5) / h
    v = (1 - r) if L['panels'][panel]['v_up'] else r
    U, V = np.meshgrid(u, v)
    return U, V, (x0, y0, w, h)

def _aa(d, px):
    return np.clip(0.5 + d / px, 0, 1)

def _poly_sd(pts, X, Y):
    """Signed distance to a polygon (> 0 inside), points and grid in the same units."""
    pts = np.asarray(pts, float); n = len(pts)
    inside = np.zeros(X.shape, bool); dmin = np.full(X.shape, np.inf)
    for i in range(n):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % n]
        inside ^= ((y1 > Y) != (y2 > Y)) & (X < (x2 - x1) * (Y - y1) / ((y2 - y1) if y2 != y1 else 1e-12) + x1)
        ex, ey = x2 - x1, y2 - y1; L2 = ex * ex + ey * ey or 1e-12
        t = np.clip(((X - x1) * ex + (Y - y1) * ey) / L2, 0, 1)
        dmin = np.minimum(dmin, np.hypot(X - (x1 + t * ex), Y - (y1 + t * ey)))
    return np.where(inside, dmin, -dmin)

def _polyline_d(pts, X, Y):
    pts = np.asarray(pts, float); dmin = np.full(X.shape, np.inf)
    for (x1, y1), (x2, y2) in zip(pts[:-1], pts[1:]):
        ex, ey = x2 - x1, y2 - y1; L2 = ex * ex + ey * ey or 1e-12
        t = np.clip(((X - x1) * ex + (Y - y1) * ey) / L2, 0, 1)
        dmin = np.minimum(dmin, np.hypot(X - (x1 + t * ex), Y - (y1 + t * ey)))
    return dmin

def _layer_sd(L, U, V, w, h):
    """The layer's signed distance (> 0 inside) in panel heights (v units), and one pixel in those units. Shapes and
    lines take points as [u, v]; distances across (u) are scaled to the panel's height so shapes keep their proportions."""
    t = L['type']; asp = w / h; px = 1.0 / h
    if t in ('fill', 'gradient'): return np.full_like(U, 1e3), px
    if t == 'band':
        a, b = L['v']; return np.minimum(V - a, b - V), px
    if t == 'u_band':
        a, b = L['u']; return np.minimum(U - a, b - U) * asp, px
    if t == 'edges':
        e = L['width']; return np.maximum(e - U, U - (1 - e)) * asp, px
    if t == 'chevron':
        c = L['v'] + L['depth'] * (1 - np.abs(2 * U - 1)); return L['width'] / 2 - np.abs(V - c), px
    if t == 'stripes':
        a = math.radians(L.get('angle', 0))
        s = (U * asp) * math.sin(a) + V * math.cos(a) + L.get('offset', 0.0)
        p = L['pitch']; return L['width'] / 2 - np.abs(((s + p / 2) % p) - p / 2), px
    if t == 'dots':
        p = L['pitch']; x = U * asp / p; y = V / p
        dx = x - np.round(x); dy = y - np.round(y)
        f = np.clip((L['v'][1] - V) / (L['v'][1] - L['v'][0]), 0, 1)
        return (0.5 * f * L.get('max', 0.9) - np.sqrt(dx * dx + dy * dy)) * p, px
    if t == 'shape':
        pts = [(u * asp, v) for u, v in L['points']]; return _poly_sd(pts, U * asp, V), px
    if t == 'line':
        pts = [(u * asp, v) for u, v in L['points']]; return L['width'] / 2 - _polyline_d(pts, U * asp, V), px
    raise ValueError('unknown layer type ' + t)

def _font(name, weight, size):
    f = ImageFont.truetype(os.path.join(DATA, 'fonts', FONTS.get(name, 'Montserrat.ttf')), max(4, int(size)))
    try: f.set_variation_by_axes([float(weight)])
    except Exception: pass
    return f

def _stamp(layer, rgba, sheet, panel, img):
    """Composite an RGBA picture onto a panel: centred at layer 'at' [u, v], 'width' (fraction of the panel's width)
    or 'height' (of its height), turned 'rotation' degrees anticlockwise."""
    L = LAYOUT[sheet]; x0, y0, w, h = L['panels'][panel]['rect']
    fit = layer.get('fit')                                         # 'cover' fills the panel, 'contain' fits inside it
    if fit in ('cover', 'contain'):
        s = (max if fit == 'cover' else min)(w / rgba.width, h / rgba.height) * layer.get('scale', 1.0)
        layer = {**layer, 'at': layer.get('at', [0.5, 0.5])}
    elif 'width' in layer: s = layer['width'] * w / rgba.width
    else: s = layer.get('height', 0.1) * h / rgba.height
    rgba = rgba.resize((max(1, int(rgba.width * s)), max(1, int(rgba.height * s))), Image.LANCZOS)
    if layer.get('rotation'): rgba = rgba.rotate(layer['rotation'], resample=Image.BICUBIC, expand=True)
    u, v = layer['at']; cx = u * w; cy = ((1 - v) if L['panels'][panel]['v_up'] else v) * h
    canvas = Image.new('RGBA', (w, h), (0, 0, 0, 0)); canvas.alpha_composite(rgba, (int(round(cx - rgba.width / 2)), int(round(cy - rgba.height / 2))))
    a = np.asarray(canvas, np.float32) / 255.0
    k = a[..., 3:4] * layer.get('opacity', 1.0)
    img[:] = img * (1 - k) + a[..., :3] * k

def _text_rgba(layer, sheet, panel):
    L = LAYOUT[sheet]; x0, y0, w, h = L['panels'][panel]['rect']
    size = layer.get('height', 0.06) * h * 1.35                    # 'height' ~ the capitals' height, of the panel
    f = _font(layer.get('font', 'Montserrat'), layer.get('weight', 600), size)
    txt = layer['text']; sp = layer.get('letter_spacing', 0.0) * size
    widths = [f.getlength(c) for c in txt]; tw = int(sum(widths) + sp * max(0, len(txt) - 1)) + 8
    asc, desc = f.getmetrics(); im = Image.new('RGBA', (tw, asc + desc + 8), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    col = tuple(int(c * 255 + 0.5) for c in layer.get('colour', [1, 1, 1])) + (255,)
    x = 4
    for c, cw in zip(txt, widths): d.text((x, 4), c, font=f, fill=col); x += cw + sp
    return im

def _matches(panel, ps):
    return not ps or any(panel == q or (q.endswith('*') and panel.startswith(q[:-1])) for q in ps)

def render(design, sheet, assets=None):
    """A design's sheet: (H, W, 3) float, designer sRGB. design: {"layers": [...]} or {"sheet": <PIL image or path>}.
    assets: {name: PIL RGBA image} for 'image' layers."""
    L = LAYOUT[sheet]; W, H = L['size']
    if 'sheet' in design:
        im = design['sheet'] if isinstance(design['sheet'], Image.Image) else Image.open(design['sheet'])
        im = im.convert('RGB')
        if list(im.size) != L['size']: raise ValueError(f'the {sheet} sheet must be {W} x {H} px, not {im.size[0]} x {im.size[1]}')
        out = np.asarray(im, np.float32) / 255.0                   # a painted sheet; any layers go on top of it
        if not design.get('layers'): return out
        out = out.copy()
    else:
        out = np.zeros((H, W, 3), np.float32) + np.array(design.get('background', [0.5, 0.5, 0.5]), np.float32)
    for panel in L['panels']:
        U, V, (x0, y0, w, h) = panel_grid(sheet, panel)
        img = out[y0:y0 + h, x0:x0 + w]
        for layer in design.get('layers', []):
            if layer['type'] in ('text', 'image'):
                if layer.get('panel') != panel: continue
                rgba = _text_rgba(layer, sheet, panel) if layer['type'] == 'text' else (assets or {})[layer['asset']].convert('RGBA')
                if layer['type'] == 'image' and layer.get('tint'):
                    t = np.asarray(rgba, np.float32); t[..., :3] = np.array(layer['tint'], np.float32) * 255; rgba = Image.fromarray(t.astype(np.uint8), 'RGBA')
                _stamp(layer, rgba, sheet, panel, img); continue
            if not _matches(panel, layer.get('panels')): continue
            sd, px = _layer_sd(layer, U, V, w, h); c = _aa(sd, px)
            if 'clip' in layer:                                     # only inside a polygon of this panel
                asp = w / h; c = c * _aa(_poly_sd([(u * asp, v) for u, v in layer['clip']], U * asp, V), px)
            c = (c * layer.get('opacity', 1.0))[..., None]
            if layer['type'] == 'gradient':
                a, b = layer['v']; f = np.clip((V - a) / (b - a), 0, 1)[..., None]
                col = np.array(layer['from'], np.float32) * (1 - f) + np.array(layer['to'], np.float32) * f
            else:
                col = np.array(layer['colour'], np.float32)
            img[:] = img * (1 - c) + col * c
            if 'edge' in layer:
                e = layer['edge']; ln = _aa(e['width'] / 2 - np.abs(sd), px)[..., None]
                img[:] = img * (1 - ln) + img * e.get('dark', 0.42) * ln
    return out

def save_png(path, img):
    Image.fromarray((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)).save(path)

def to_png_bytes(img):
    import io
    b = io.BytesIO(); Image.fromarray((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)).save(b, 'PNG'); return b.getvalue()

def clean_template(sheet):
    """A plain template for painting a sheet by hand or with an image model: white panels with thin outlines, each
    panel's name and which way is up, the zip's line, the pockets, the cuff and gripper bands (dashed)."""
    L = LAYOUT[sheet]; W, H = L['size']
    im = Image.new('RGB', (W, H), (128, 128, 128)); d = ImageDraw.Draw(im)
    f = _font('Montserrat', 600, 40); fs = _font('Montserrat', 400, 26); g = (150, 150, 150)
    def dash(x0, y0, x1, y1):
        n = int(max(abs(x1 - x0), abs(y1 - y0)) // 24)
        for i in range(0, n, 2):
            a, b = i / n, (i + 1) / n
            d.line([(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a), (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b)], fill=g, width=3)
    notes = {'front': 'FRONT  (rider\'s right | left)', 'back': 'BACK  (rider\'s left | right)', 'sleeve_r': 'RIGHT SLEEVE  (back | top | front)',
             'sleeve_l': 'LEFT SLEEVE  (front | top | back)', 'collar': 'COLLAR  (back | front | back)', 'leg_r': 'RIGHT LEG  (back | outside | front)',
             'leg_l': 'LEFT LEG  (front | outside | back)'}
    for p, P in L['panels'].items():
        x0, y0, w, h = P['rect']; d.rectangle([x0, y0, x0 + w - 1, y0 + h - 1], fill=(255, 255, 255), outline=(90, 90, 90), width=3)
        up = 'shoulders' if p in ('front', 'back') else 'armhole' if p.startswith('sleeve') else 'top edge' if p == 'collar' else 'waist'
        d.text((x0 + 16, y0 + 10 if p != 'collar' else y0 + 4), notes[p], fill=(120, 120, 120), font=f if p != 'collar' else fs)
        if p != 'collar': d.text((x0 + 16, y0 + 58), f'top of panel = {up}', fill=(150, 150, 150), font=fs)
        if p == 'front': dash(x0 + w // 2, y0, x0 + w // 2, y0 + h)                                   # the zip
        if p == 'back': d.rectangle([x0 + int(w * 0.22), y0 + int(h * 0.64), x0 + int(w * 0.78), y0 + int(h * 0.92)], outline=g, width=3)  # pockets
        if p.startswith('sleeve'): dash(x0, y0 + int(h * 0.82), x0 + w, y0 + int(h * 0.82))             # the cuff
        if p.startswith('leg'): dash(x0, y0 + int(h * 0.9), x0 + w, y0 + int(h * 0.9))                  # the gripper
        if p in ('front', 'back'): dash(x0, y0 + int(h * 0.08), x0 + w, y0 + int(h * 0.08))              # over the shoulders above this
    return im
