"""The kit file: what an agent hands in and the game reads.

A kit is a JSON object (below); export() writes it as one `.kit.zip`:
  kit.json            the kit as written (its layers, colours, notes), with the format and version
  jersey.png          the finished jersey sheet, 2048 x 2048 (what the game paints the rider with)
  bib.png             the finished bib sheet, 2048 x 1024
  assets/<name>.png   the pictures its layers use (logos, painted sheets)
  previews/*.png      the kit on the game's male and female riders (for whoever reviews submissions)

The kit object:
  {"format": "virada-kit", "version": 1,
   "name": "...", "author": "...", "description": "...",
   "jersey": {"layers": [...]} or {"sheet": "<asset name>"},  plus optional "zip": [r,g,b], "dots": {"cuff": [r,g,b]}
   "bib":    {"layers": [...]} or {"sheet": "<asset name>"},  plus optional "dots": {"gripper": [r,g,b]}
   "socks": [r,g,b],
   "provenance": {"made_with": "...", "references": ["..."], "invented": ["what no reference showed, e.g. the back"]}}
Colours are designer sRGB, three numbers 0..1. Layer reference: SPEC.md.
"""
import io, json, os, zipfile, datetime
import numpy as np
from PIL import Image
from . import sheets, preview

FORMAT, VERSION = 'virada-kit', 1
MAX_LAYERS, MAX_ASSETS, MAX_ASSET_PX, MAX_TEXT = 80, 16, 2048, 40
LAYER_FIELDS = {
    'fill': [], 'gradient': ['v', 'from', 'to'], 'band': ['v'], 'u_band': ['u'], 'edges': ['width'],
    'chevron': ['v', 'depth', 'width'], 'stripes': ['pitch', 'width'], 'dots': ['v', 'pitch'], 'shape': ['points'],
    'line': ['points', 'width'], 'text': ['text', 'panel', 'at'], 'image': ['asset', 'panel'],
}

def _rgb_ok(c):
    return isinstance(c, (list, tuple)) and len(c) == 3 and all(isinstance(x, (int, float)) and 0 <= x <= 1 for x in c)

def validate(kit, assets):
    """Problems with a kit, as plain sentences ([] = fine). assets: {name: PIL image}."""
    p = []
    if not isinstance(kit, dict): return ['the kit must be a JSON object']
    if not str(kit.get('name', '')).strip(): p.append('"name" is missing')
    if len(str(kit.get('name', ''))) > 40: p.append('"name" is longer than 40 characters')
    for part, sheet in (('jersey', 'jersey'), ('bib', 'bib')):
        d = kit.get(part)
        if not isinstance(d, dict): p.append(f'"{part}" is missing'); continue
        if 'sheet' in d:
            a = assets.get(d['sheet'])
            if a is None: p.append(f'{part}: sheet asset "{d["sheet"]}" was not added')
            elif list(a.size) != sheets.LAYOUT[sheet]['size']:
                p.append(f'{part}: the sheet is {a.size[0]} x {a.size[1]} px; it must be {sheets.LAYOUT[sheet]["size"][0]} x {sheets.LAYOUT[sheet]["size"][1]}')
        layers = d.get('layers', [])
        if 'sheet' not in d and not layers: p.append(f'{part}: give "layers" or a "sheet"')
        if len(layers) > MAX_LAYERS: p.append(f'{part}: more than {MAX_LAYERS} layers')
        panels = set(sheets.LAYOUT[sheet]['panels'])
        for i, L in enumerate(layers):
            where = f'{part} layer {i} ({L.get("type", "?")})'
            t = L.get('type')
            if t not in LAYER_FIELDS: p.append(f'{where}: unknown type; use one of {", ".join(LAYER_FIELDS)}'); continue
            for k in LAYER_FIELDS[t]:
                if k not in L: p.append(f'{where}: "{k}" is missing')
            if t == 'gradient':
                for k in ('from', 'to'):
                    if k in L and not _rgb_ok(L[k]): p.append(f'{where}: "{k}" must be [r, g, b], each 0..1')
            elif t != 'image' and not _rgb_ok(L.get('colour')): p.append(f'{where}: "colour" must be [r, g, b], each 0..1')
            for q in L.get('panels', []):
                if q not in panels and not (q.endswith('*') and any(x.startswith(q[:-1]) for x in panels)):
                    p.append(f'{where}: no panel "{q}" on the {sheet} sheet ({", ".join(sorted(panels))})')
            if t in ('text', 'image') and L.get('panel') not in panels:
                p.append(f'{where}: "panel" must be one of {", ".join(sorted(panels))}')
            if t == 'text':
                if len(str(L.get('text', ''))) > MAX_TEXT: p.append(f'{where}: text longer than {MAX_TEXT} characters')
                if L.get('font', 'Montserrat') not in sheets.FONTS: p.append(f'{where}: font must be one of {", ".join(sheets.FONTS)}')
            if t == 'image' and L.get('asset') not in assets: p.append(f'{where}: asset "{L.get("asset")}" was not added')
            for k in ('points', 'clip'):
                if k in L and not (isinstance(L[k], list) and len(L[k]) >= (2 if t == 'line' and k == 'points' else 3)
                                   and all(isinstance(q, (list, tuple)) and len(q) == 2 for q in L[k])):
                    p.append(f'{where}: "{k}" must be a list of [u, v] points')
        if part == 'jersey' and 'zip' in d and not _rgb_ok(d['zip']): p.append('jersey: "zip" must be [r, g, b]')
    if 'socks' in kit and not _rgb_ok(kit['socks']): p.append('"socks" must be [r, g, b]')
    if len(assets) > MAX_ASSETS: p.append(f'more than {MAX_ASSETS} assets')
    return p

def warnings(kit, assets):
    """Things that will look worse than they should (not errors): pictures shown much bigger than they are."""
    w = []
    for part, sheet in (('jersey', 'jersey'), ('bib', 'bib')):
        for i, L in enumerate((kit.get(part) or {}).get('layers', [])):
            if L.get('type') != 'image' or L.get('asset') not in assets or L.get('panel') not in sheets.LAYOUT[sheet]['panels']: continue
            a = assets[L['asset']]; pw, ph = sheets.LAYOUT[sheet]['panels'][L['panel']]['rect'][2:]
            if L.get('fit') in ('cover', 'contain'): k = (max if L['fit'] == 'cover' else min)(pw / a.width, ph / a.height) * L.get('scale', 1)
            elif 'width' in L: k = L['width'] * pw / a.width
            else: k = L.get('height', 0.1) * ph / a.height
            if k > 1.5:
                w.append(f'{part} layer {i}: picture "{L["asset"]}" is {a.width} x {a.height} px but shown {k:.1f}x bigger, so it '
                         f'will look soft: add it again at about {int(a.width * k)} px wide (a sharper cut-out, or redraw it big)')
    return w

def render_sheets(kit, assets):
    """The two finished sheets, (H, W, 3) floats."""
    out = {}
    for part in ('jersey', 'bib'):
        d = dict(kit[part])
        if 'sheet' in d: d['sheet'] = assets[d['sheet']]
        out[part] = sheets.render(d, part, assets)
    return out['jersey'], out['bib']

def previews(kit, assets, bodies=('male', 'female'), views=('front', 'front34_left', 'back'), js=None, bs=None):
    if js is None: js, bs = render_sheets(kit, assets)
    dots = {**kit['jersey'].get('dots', {}), **kit['bib'].get('dots', {})}
    out = {}
    for b in bodies:
        for v in views:
            out[f'{b}_{v}'] = preview.render_view(js, bs, b, v, kit['jersey'].get('zip', [0.13, 0.15, 0.22]), dots,
                                                  sock=kit.get('socks', [0.96, 0.95, 0.92]))
    return out

def export(kit, assets, path):
    """Write the .kit.zip; returns its path. Raises ValueError with the problems if the kit isn't valid."""
    probs = validate(kit, assets)
    if probs: raise ValueError('; '.join(probs))
    kit = dict(kit); kit['format'], kit['version'] = FORMAT, VERSION
    kit['exported'] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    js, bs = render_sheets(kit, assets)
    if not path.endswith('.kit.zip'): path += '.kit.zip'
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    used = {L['asset'] for part in ('jersey', 'bib') for L in kit[part].get('layers', []) if L.get('type') == 'image'}
    used |= {kit[part]['sheet'] for part in ('jersey', 'bib') if 'sheet' in kit[part]}
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('kit.json', json.dumps(kit, indent=1))
        z.writestr('jersey.png', sheets.to_png_bytes(js)); z.writestr('bib.png', sheets.to_png_bytes(bs))
        for n in sorted(used):
            b = io.BytesIO(); assets[n].save(b, 'PNG'); z.writestr(f'assets/{n}.png', b.getvalue())
        for k, im in previews(kit, assets, js=js, bs=bs).items():
            z.writestr(f'previews/{k}.png', sheets.to_png_bytes(im))
    return path

def load(path):
    """A .kit.zip back: (kit, assets, jersey sheet, bib sheet)."""
    with zipfile.ZipFile(path) as z:
        kit = json.loads(z.read('kit.json'))
        assets = {os.path.splitext(os.path.basename(n))[0]: Image.open(io.BytesIO(z.read(n))).copy()
                  for n in z.namelist() if n.startswith('assets/') and n.endswith('.png')}
        js = np.asarray(Image.open(io.BytesIO(z.read('jersey.png'))).convert('RGB'), np.float32) / 255
        bs = np.asarray(Image.open(io.BytesIO(z.read('bib.png'))).convert('RGB'), np.float32) / 255
    return kit, assets, js, bs
