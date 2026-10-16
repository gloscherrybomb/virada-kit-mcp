"""The Virada kit MCP server: an AI agent turns a user's kit pictures into a kit file the game can use.

Run it locally (stdio): `uvx virada-kit` or `uv run virada-kit`; or over HTTP: `virada-kit --http [--port 8000]`.
Tools: get_kit_spec, get_template, add_asset, list_assets, render_sheets, preview_kit, compare_to_reference,
validate_kit, export_kit (hands the file back to the agent), import_kit. Resource: kit://<file name>. The kit format: SPEC.md (returned by get_kit_spec).
"""
import base64, io, json, os, sys, tempfile
import numpy as np
from PIL import Image as PILImage
from mcp.server.mcpserver import MCPServer, Image, Context, Icon
from mcp.types import EmbeddedResource, BlobResourceContents
from . import sheets, preview, kitfile, limits

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = open(os.path.join(HERE, 'SPEC.md')).read()
LOCAL_ = '--http' not in sys.argv
# exported kits land here: a folder the user can find (local), or a temporary one (a remote server)
WORK = os.environ.get('VIRADA_KIT_WORKDIR') or (os.path.expanduser('~/virada-kits') if LOCAL_ else tempfile.mkdtemp(prefix='virada-kit-'))
os.makedirs(WORK, exist_ok=True)
LOCAL = LOCAL_                # over HTTP the server never reads or writes paths it is given (only base64 in)
import collections, hashlib, logging, secrets, time
from mcp.types import ToolAnnotations
LOG = logging.getLogger('virada_kit')
# Every tool only makes pictures and files for the caller; none changes anything else (so apps can skip asking).
SAFE = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

class AssetStore:
    """The pictures kits use. Chat apps may open a new connection for every call (Gemini does), so pictures can't
    live with a connection: a remote server keeps them for two hours under an id add_asset hands back (the name plus a
    random part), stored as PNG (small), up to a total size. A local server keeps them under the names given."""
    TTL, MAX_BYTES = 7200, 300_000_000
    def __init__(self): self.d = collections.OrderedDict()           # id -> (png bytes, time)
    def put(self, name, im):
        key = name if LOCAL else f'{name}~{secrets.token_hex(3)}'
        b = io.BytesIO(); im.save(b, 'PNG'); self.d[key] = (b.getvalue(), time.time()); self.d.move_to_end(key)
        self._trim(); return key
    def _trim(self):
        now = time.time()
        for k in [k for k, (_, t) in self.d.items() if now - t > self.TTL and not LOCAL]: del self.d[k]
        while sum(len(b) for b, _ in self.d.values()) > self.MAX_BYTES and len(self.d) > 1: self.d.popitem(last=False)
    def get(self, key):
        v = self.d.get(key)
        return PILImage.open(io.BytesIO(v[0])).convert('RGBA') if v else None
    def for_kit(self, kit):
        """{name: picture} for the pictures this kit names (missing ones are left for validate to report)."""
        names = set()
        for part in ('jersey', 'bib'):
            d = kit.get(part) if isinstance(kit, dict) else None
            if not isinstance(d, dict): continue
            if isinstance(d.get('sheet'), str): names.add(d['sheet'])
            names |= {L.get('asset') for L in d.get('layers', []) if isinstance(L, dict) and L.get('type') == 'image'}
        return {n: im for n in names if n and (im := self.get(n)) is not None}
    def sizes(self):
        return {k: list(PILImage.open(io.BytesIO(b)).size) for k, (b, _) in self.d.items()}
STORE = AssetStore()
LIMITER = limits.Limiter()
def _client(ctx):
    c = limits.client_of(getattr(ctx, 'headers', None) if ctx is not None else None)
    return hashlib.sha256(c.encode()).hexdigest()[:8]               # logs keep a stand-in, not the address
def _gate(ctx, tool):
    """None, or the reason this call must wait (remote servers only). Logs the call (the tool, a stand-in for the
    caller), so how agents use the server can be read back with `docker logs`."""
    if LOCAL: return None
    LOG.info('call %s client=%s', tool, _client(ctx))
    why = LIMITER.take(limits.client_of(getattr(ctx, 'headers', None) if ctx is not None else None), tool)
    if why: LOG.info('limited %s client=%s', tool, _client(ctx))
    return why
def _problems(kit, assets, tool):
    p = kitfile.validate(kit, assets)
    if p and not LOCAL: LOG.info('invalid %s: %s', tool, ' | '.join(p)[:600])
    return p
def _hv(fn):
    """fn, run only when its turn comes: at most a few previews and exports at once on a remote server."""
    def run(*a, **k):
        if LOCAL: return fn(*a, **k)
        if not LIMITER.heavy.acquire(timeout=limits.HEAVY_WAIT):
            raise RuntimeError('busy: many kits are being worked on right now; try again in a minute')
        try: return fn(*a, **k)
        finally:
            LIMITER.heavy.release(); _give_back()
    return run

def _give_back():
    """Hand freed memory back to the system after a big job (glibc keeps it otherwise; Linux only)."""
    try:
        import ctypes, gc
        gc.collect(); ctypes.CDLL('libc.so.6').malloc_trim(0)
    except Exception:
        pass

INSTRUCTIONS = '''Makes cycling kits (a jersey and bib shorts) for the Virada game from the user's pictures of a kit. When the
user asks for a kit, or gives you kit pictures and mentions Virada, follow this without being told:
1. Call get_kit_spec and read all of it: the sheet layout, the panels' directions, the layers, the rules.
2. Study the user's pictures: list every colour, panel, stripe, logo, text and where each sits on the body (measure
   against the zip, the side seams, the hem, the shoulders). If they don't show the back, the far sleeve or the bibs,
   propose those (keep the design's language) and ask the user before you build them.
3. If a picture holds artwork (an illustration, a scene, a photo print) or a logo the layers can't draw well, don't
   redraw it from shapes: cut it out of the user's picture, add_asset it, and place it as an 'image' layer ("fit":
   "cover" fills a panel); draw the plain parts with layers.
4. Build the kit, then loop: preview_kit and compare_to_reference (with the user's picture, from the view nearest its
   angle; the straight front view is included), list what differs, fix it. Do at least three rounds, and keep going
   until the front, the back and both sleeves match; check the female rider too.
5. validate_kit, then export_kit; give the user the file (and its download link on a remote server), and say what
   you invented.
Never stop at a rough first draft: the kit must look like the user's pictures on the game's rider.'''
_PUB = os.environ.get('VIRADA_KIT_PUBLIC_URL', '').rstrip('/')
ICONS = [Icon(src=f'{_PUB}/icon-512.png', mimeType='image/png', sizes=['512x512']),
         Icon(src=f'{_PUB}/icon-192.png', mimeType='image/png', sizes=['192x192'])] if _PUB.startswith('https://') else None
mcp = MCPServer('virada-kit', title='Virada kit maker', version='0.1.0', icons=ICONS,
                website_url='https://github.com/gloscherrybomb/virada-kit-mcp',
                instructions=INSTRUCTIONS)

def _png(img, max_side=None):
    im = img if isinstance(img, PILImage.Image) else PILImage.fromarray((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8))
    im = im.convert('RGB')
    if max_side and max(im.size) > max_side: im.thumbnail((max_side, max_side))
    b = io.BytesIO(); im.save(b, 'PNG'); return Image(data=b.getvalue(), format='png')

def _open_image(path=None, base64_data=None):
    if path:
        if not LOCAL: raise ValueError('this server is remote and cannot read your files: send the picture as base64 data, '
                                       'or, if you cannot, build the kit from layers and leave pictures out')
        return PILImage.open(os.path.expanduser(path)).copy()
    if base64_data:
        if base64_data.startswith('data:'): base64_data = base64_data.split(',', 1)[1]
        return PILImage.open(io.BytesIO(base64.b64decode(base64_data))).copy()
    raise ValueError('give a path or base64 data')

def _kit(kit):
    if isinstance(kit, str): kit = json.loads(kit)
    return kit

@mcp.tool(annotations=SAFE)
def get_kit_spec(ctx: Context = None) -> str:
    """The kit format and how to make a kit: the sheets and their panels, the layer types, the workflow. Read first."""
    why = _gate(ctx, 'get_kit_spec')
    if why: return why
    return SPEC

@mcp.tool(annotations=SAFE)
def get_template(sheet: str = 'jersey', style: str = 'guide', save_to: str | None = None, ctx: Context = None) -> list:
    """A sheet's template ('jersey' 2048x2048 or 'bib' 2048x1024). style 'guide': the panels and where the game's male
    (blue) and female (pink) riders' kit edges, seams, zip and pockets fall, for placing layers. style 'clean': white
    panels with thin outlines, names and which way is up, the zip line, pockets, cuff and gripper bands: the canvas to
    paint a whole sheet on (route B, e.g. with an image model; paint everything, leave no outlines or words).
    save_to: also write the full-size PNG to this path (local servers)."""
    why = _gate(ctx, 'get_template')
    if why: return [why]
    im = sheets.clean_template(sheet) if style == 'clean' else PILImage.open(os.path.join(sheets.DATA, f'sheet_guide_{sheet}.png'))
    note = f'{sheet} sheet guide, full size {im.size[0]} x {im.size[1]} px (shown smaller).'
    if save_to and LOCAL:
        im.save(os.path.expanduser(save_to)); note += f' Saved full size to {save_to}.'
    return [note, _png(im, 1400)]

@mcp.tool(annotations=SAFE)
def add_asset(name: str, path: str | None = None, base64_png: str | None = None, ctx: Context = None) -> str:
    """Add a picture the kit uses: a logo for an 'image' layer (PNG with transparency is best) or a whole painted sheet
    for {"sheet": ...}. Give a local file path (local servers) or base64 PNG/JPEG data. Use the id it returns in the kit.
    Names: letters, digits, _ and -. In a chat app that can't send a picture's bytes, skip this: build with layers."""
    why = _gate(ctx, 'add_asset')
    if why: return why
    if not name or not all(c.isalnum() or c in '_-' for c in name): return 'name: letters, digits, _ and - only'
    im = _open_image(path, base64_png)
    if max(im.size) > kitfile.MAX_ASSET_PX and list(im.size) not in (sheets.LAYOUT['jersey']['size'], sheets.LAYOUT['bib']['size']):
        im.thumbnail((kitfile.MAX_ASSET_PX, kitfile.MAX_ASSET_PX))
    key = STORE.put(name, im.convert('RGBA'))
    return (f'added: use "{key}" for it in the kit ({im.size[0]} x {im.size[1]} px' +
            (', has transparency)' if im.mode in ('RGBA', 'LA', 'P') else ', no transparency: it will be a rectangle)') +
            ('' if LOCAL else '. Kept for two hours.'))

@mcp.tool(annotations=SAFE)
def list_assets(ctx: Context = None) -> str:
    """The pictures added so far."""
    why = _gate(ctx, 'list_assets')
    if why: return why
    if not LOCAL: return 'a remote server keeps pictures for two hours under the ids add_asset returned; it does not list them'
    z = STORE.sizes(); return json.dumps(z) if z else 'no assets yet'

@mcp.tool(annotations=SAFE)
def validate_kit(kit: dict | str, ctx: Context = None) -> str:
    """Check a kit object against the format. Returns 'valid' or the problems to fix."""
    why = _gate(ctx, 'validate_kit')
    if why: return why
    kit = _kit(kit); ASSETS = STORE.for_kit(kit)
    p = _problems(kit, ASSETS, 'validate_kit'); w = kitfile.warnings(kit, ASSETS)
    return ('valid' if not p else 'problems:\n- ' + '\n- '.join(p)) + ('\nwarnings:\n- ' + '\n- '.join(w) if w else '')

@mcp.tool(annotations=SAFE)
def render_sheets(kit: dict | str, ctx: Context = None) -> list:
    """The kit's two finished sheets as pictures (jersey, then bib), to check the flat layout."""
    why = _gate(ctx, 'render_sheets')
    if why: return [why]
    kit = _kit(kit); ASSETS = STORE.for_kit(kit)
    p = _problems(kit, ASSETS, 'render_sheets')
    if p: return ['problems:\n- ' + '\n- '.join(p)]
    js, bs = _hv(kitfile.render_sheets)(kit, ASSETS)
    return ['jersey sheet (2048 x 2048, shown smaller), then bib sheet (2048 x 1024)', _png(js, 1024), _png(bs, 1024)]

@mcp.tool(annotations=SAFE)
def preview_kit(kit: dict | str, body: str = 'male', views: list[str] | None = None, ctx: Context = None) -> list:
    """The kit on the game's rider, in the game's look; follow it with compare_to_reference and fix what differs.
    body: 'male' or 'female'. views (any of front, front34_left,
    left, back, right, front34_right; default front, front34_left, back). front34_left = the front turned to show the
    rider's left side, like most product photos."""
    why = _gate(ctx, 'preview_kit')
    if why: return [why]
    kit = _kit(kit); ASSETS = STORE.for_kit(kit)
    p = _problems(kit, ASSETS, 'preview_kit')
    if p: return ['problems:\n- ' + '\n- '.join(p)]
    views = views or ['front', 'front34_left', 'back']
    bad = [v for v in views if v not in preview.VIEWS]
    if bad: return [f'unknown views {bad}; use {list(preview.VIEWS)}']
    ims = _hv(kitfile.previews)(kit, ASSETS, bodies=(body,), views=tuple(views))
    return [f'{body}: ' + ', '.join(views), _png(preview.sheet_of_views(list(ims.values()), views, cols=min(3, len(views)), scale=0.6))]

@mcp.tool(annotations=SAFE)
def compare_to_reference(kit: dict | str, reference_path: str | None = None, reference_base64: str | None = None,
                         body: str = 'male', view: str = 'front34_left', jersey_only: bool = True, grid: bool = True,
                         ctx: Context = None) -> list:
    """The user's reference picture beside the kit on the game's rider from a similar angle, to spot what differs
    (colours, where panels and logos sit, sizes). Pick the view nearest the reference's angle. The rider is cropped to
    the jersey (jersey_only, default) or to the jersey and bibs, as product pictures are framed. If you can't send the
    picture's bytes (a chat app), leave the reference out: you get the rider's views alone to set beside the picture
    you can see. grid (default on) draws the FRONT and BACK panels' coordinates on the rider (a line every 0.1 of u and
    v, thicker at u = 0.5): read off where and how big each logo, stripe and panel edge is in the reference, and set the
    same numbers in the kit."""
    why = _gate(ctx, 'compare_to_reference')
    if why: return [why]
    kit = _kit(kit); ASSETS = STORE.for_kit(kit)
    p = _problems(kit, ASSETS, 'compare_to_reference')
    if p: return ['problems:\n- ' + '\n- '.join(p)]
    ref = _open_image(reference_path, reference_base64).convert('RGB') if (reference_path or reference_base64) else None
    vs = [view] + (['front'] if view != 'front' else [])          # and straight on: centring and size read true there
    ims = _hv(kitfile.previews)(kit, ASSETS, bodies=(body,), views=tuple(vs))
    crops = [preview.crop_to_kit(preview.grid_overlay(ims[f'{body}_{v}'], body, v) if grid else ims[f'{body}_{v}'], body, v,
                                 jersey_only=jersey_only) for v in vs]
    COMPARED[_fingerprint(kit)] = time.time()
    if len(COMPARED) > 5000: COMPARED.clear()
    pics, labs = ([ref] if ref else []) + crops, (['reference'] if ref else []) + [f'{body} {v}' for v in vs]
    return [('left: the reference; then ' if ref else '') + f'the kit on the {body} rider: {", ".join(vs)}. Judge centring '
            'and size on the straight front view: a three-quarter picture squeezes the side turned away.' +
            (' The cyan lines are the panel grid (every 0.1 of u and v; the thick one is u = 0.5): measure the reference '
             'against the same landmarks (the zip, the seams, the hem, the shoulders) and match sizes, not just places.' if grid else '') +
            ''.join('\nwarning: ' + x for x in kitfile.warnings(kit, ASSETS)),
            _png(preview.sheet_of_views(pics, labs, cols=len(pics), scale=0.6))]

COMPARED: dict = {}        # kit fingerprint -> time it was compared to a reference
def _fingerprint(kit):
    return hashlib.sha256(json.dumps({k: kit.get(k) for k in ('jersey', 'bib')}, sort_keys=True).encode()).hexdigest()[:16]

def _kit_blob(path):
    name = os.path.basename(path)
    return EmbeddedResource(resource=BlobResourceContents(uri=f'kit://{name}', mimeType='application/zip',
                                                          blob=base64.b64encode(open(path, 'rb').read()).decode()))

@mcp.tool(annotations=SAFE)
def export_kit(kit: dict | str, path: str | None = None, user_approved: bool = False, ctx: Context = None) -> list:
    """Write the kit file (.kit.zip: kit.json, the two finished sheets, its pictures, previews) and hand it back. Only
    after the compare loop shows the kit matching the user's pictures (see get_kit_spec's workflow); it refuses a kit
    that was never compared, or one with invented parts, until user_approved=true (the user has seen and agreed). The
    result carries the file itself (an embedded resource, application/zip, also readable later as kit://<file name>)
    for you to save or pass on, plus where the server wrote it (path: local servers; default its work folder) and a
    preview to check."""
    why = _gate(ctx, 'export_kit')
    if why: return [why]
    kit = _kit(kit); ASSETS = STORE.for_kit(kit)
    if not user_approved and _fingerprint(kit) not in COMPARED:
        return ['not exported yet: this exact kit has not been through compare_to_reference. Compare it with the user\'s '
                'picture (front and three-quarter), fix what differs, and export the version you compared. If the user '
                'has seen the previews and wants it as it is, call export_kit again with user_approved=true.']
    if not user_approved and (kit.get('provenance') or {}).get('invented'):
        return ['not exported yet: the kit has invented parts (' + '; '.join(map(str, kit['provenance']['invented'])) +
                '). Show the user previews of them and ask; when they approve, call export_kit with user_approved=true.']
    path = os.path.expanduser(path) if (path and LOCAL) else os.path.join(WORK, ''.join(c if c.isalnum() else '_' for c in kit.get('name', 'kit')).strip('_').lower() or 'kit')
    try: out = _hv(kitfile.export)(kit, ASSETS, path)
    except ValueError as e:
        if not LOCAL: LOG.info('invalid export_kit: %s', str(e)[:600])
        return [f'not exported, problems: {e}']
    if not LOCAL: LOG.info('exported %s client=%s', os.path.basename(out), _client(ctx))
    EXPORTED[os.path.basename(out)] = out
    link = ''
    if not LOCAL:                                  # a remote server: a private link to download the file for an hour
        import secrets, shutil
        tok = secrets.token_urlsafe(12); os.makedirs(os.path.join(WORK, 'dl', tok), exist_ok=True)
        shutil.copy(out, os.path.join(WORK, 'dl', tok, os.path.basename(out)))
        link = f' Download it here (one hour): {PUBLIC_URL}/kits/{tok}/{os.path.basename(out)}'
        _sweep_downloads()
    ims = _hv(kitfile.previews)(kit, ASSETS, bodies=('male', 'female'), views=('front34_left',))
    return [f'exported {os.path.basename(out)} ({os.path.getsize(out) // 1024} KB)' + (f', written to {out}' if LOCAL else '') +
            '. The file itself is attached (kit://' + os.path.basename(out) + ').' + link + ' Send it in to have it reviewed for the game.',
            _kit_blob(out), _png(preview.sheet_of_views(list(ims.values()), ['male', 'female'], cols=2, scale=0.5))]

EXPORTED: dict = {}         # file name -> path, for kit://

@mcp.prompt(name='make_kit', description='Make a Virada kit from your kit pictures')
def make_kit_prompt(pictures: str = 'the pictures I attached') -> str:
    return f'Make a Virada kit from {pictures}, using the virada-kit tools.\n\n' + INSTRUCTIONS

@mcp.resource('kit://{name}', name='kit file', description='A kit file this server exported (.kit.zip)', mime_type='application/zip')
def kit_file(name: str) -> bytes:
    p = EXPORTED.get(name) or os.path.join(WORK, name)
    if not os.path.exists(p) or not name.endswith('.kit.zip'): raise ValueError(f'no exported kit {name}')
    return open(p, 'rb').read()

@mcp.tool(annotations=SAFE)
def import_kit(path: str | None = None, base64_zip: str | None = None, ctx: Context = None) -> list:
    """Open a .kit.zip (made here or elsewhere) to keep working on it: returns its kit object (to edit and pass to the
    other tools) and adds its pictures as assets; also shows it on the riders."""
    why = _gate(ctx, 'import_kit')
    if why: return [why]
    if path:
        if not LOCAL: return ['this server is remote: send the file as base64, not a path']
        src = os.path.expanduser(path)
    elif base64_zip:
        src = os.path.join(WORK, 'imported.kit.zip'); open(src, 'wb').write(base64.b64decode(base64_zip.split(',', 1)[-1]))
    else: return ['give a path or base64_zip']
    kit, assets, js, bs = kitfile.load(src)
    for k in ('format', 'version', 'exported'): kit.pop(k, None)
    ren = {n: STORE.put(n, im.convert('RGBA')) for n, im in assets.items()}      # its pictures, under their new ids
    for part in ('jersey', 'bib'):
        d = kit.get(part, {})
        if d.get('sheet') in ren: d['sheet'] = ren[d['sheet']]
        for L in d.get('layers', []):
            if L.get('asset') in ren: L['asset'] = ren[L['asset']]
    ASSETS = STORE.for_kit(kit)
    ims = _hv(kitfile.previews)(kit, ASSETS, bodies=('male',), views=('front', 'front34_left', 'back'), js=js, bs=bs)
    return [json.dumps(kit), _png(preview.sheet_of_views(list(ims.values()), ['front', 'front34_left', 'back'], cols=3, scale=0.5))]

PUBLIC_URL = os.environ.get('VIRADA_KIT_PUBLIC_URL', 'http://127.0.0.1:8000').rstrip('/')

def _sweep_downloads(max_age=3600):
    """A remote server keeps nothing for long: download links and exported files go after an hour."""
    import time, shutil
    d = os.path.join(WORK, 'dl')
    for t in os.listdir(d) if os.path.isdir(d) else []:
        p = os.path.join(d, t)
        if time.time() - os.path.getmtime(p) > max_age: shutil.rmtree(p, ignore_errors=True)
    for f in os.listdir(WORK):
        p = os.path.join(WORK, f)
        if f.endswith('.kit.zip') and time.time() - os.path.getmtime(p) > max_age: os.remove(p)

@mcp.custom_route('/kits/{token}/{name}', methods=['GET'], include_in_schema=False)
async def download(request):
    from starlette.responses import FileResponse, PlainTextResponse
    tok, name = request.path_params['token'], request.path_params['name']
    p = os.path.join(WORK, 'dl', tok, name)
    if '/' in tok + name or '..' in tok + name or not name.endswith('.kit.zip') or not os.path.exists(p):
        return PlainTextResponse('not found', status_code=404)
    return FileResponse(p, media_type='application/zip', filename=name)

ICON_DIR = os.path.join(sheets.DATA, 'icon')
ICON_FILES = {'favicon.ico': 'image/x-icon', 'icon-192.png': 'image/png', 'icon-512.png': 'image/png', 'apple-touch-icon.png': 'image/png'}

@mcp.custom_route('/{icon_name}', methods=['GET'], include_in_schema=False)
async def icon_file(request):
    """The Virada icon (apps that show a server's favicon find it here, not the parent domain's)."""
    from starlette.responses import FileResponse, PlainTextResponse
    n = request.path_params['icon_name']
    if n == 'health': return PlainTextResponse('ok')              # (this route is matched before /health)
    if n not in ICON_FILES: return PlainTextResponse('not found', status_code=404)
    return FileResponse(os.path.join(ICON_DIR, n), media_type=ICON_FILES[n], headers={'Cache-Control': 'public, max-age=86400'})

@mcp.custom_route('/', methods=['GET'], include_in_schema=False)
async def home(request):
    from starlette.responses import HTMLResponse
    return HTMLResponse('''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Virada kit maker</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="/favicon.ico" sizes="any"><link rel="icon" type="image/png" sizes="192x192" href="/icon-192.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<style>body{font-family:system-ui,sans-serif;background:#1c1c20;color:#eee;max-width:640px;margin:48px auto;padding:0 16px;line-height:1.5}
img{width:96px;height:96px}code{background:#2a2a30;padding:2px 6px;border-radius:4px}a{color:#ff5a4e}</style></head>
<body><img src="/icon-192.png" alt=""><h1>Virada kit maker</h1>
<p>An MCP server: connect your AI agent, give it pictures of a cycling kit, and it makes a kit file for the Virada game.</p>
<p>Server address for chat apps: <code>''' + PUBLIC_URL + '''/mcp</code></p>
<p>How to connect and the kit format: <a href="https://github.com/gloscherrybomb/virada-kit-mcp">github.com/gloscherrybomb/virada-kit-mcp</a></p>
</body></html>''')

@mcp.custom_route('/health', methods=['GET'], include_in_schema=False)
async def health(request):
    from starlette.responses import PlainTextResponse
    return PlainTextResponse('ok')

def main():
    if '--http' in sys.argv:
        # a remote server for chat apps (Gemini, Claude.ai, ChatGPT): streamable HTTP at /mcp; put it behind HTTPS and
        # set VIRADA_KIT_PUBLIC_URL to its public address (for download links and the allowed Host header)
        from mcp.server.transport_security import TransportSecuritySettings
        from urllib.parse import urlparse
        a = sys.argv; port = int(a[a.index('--port') + 1]) if '--port' in a else 8000
        host = a[a.index('--host') + 1] if '--host' in a else '127.0.0.1'
        pub = urlparse(PUBLIC_URL).netloc
        sec = TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                        allowed_hosts=[pub, f'127.0.0.1:{port}', f'localhost:{port}'],
                                        allowed_origins=['https://gemini.google.com', 'https://claude.ai', 'https://chatgpt.com', PUBLIC_URL])
        mcp.run('streamable-http', host=host, port=port, transport_security=sec, stateless_http=False,
                max_request_body_size=16 * 1024 * 1024, max_sessions=500)
    else:
        mcp.run()

if __name__ == '__main__':
    main()
