"""The Virada kit MCP server: an AI agent turns a user's kit pictures into a kit file the game can use.

Run it locally (stdio): `uvx virada-kit` or `uv run virada-kit`; or over HTTP: `virada-kit --http [--port 8000]`.
Tools: get_kit_spec, get_template, add_asset, list_assets, render_sheets, preview_kit, compare_to_reference,
validate_kit, export_kit (hands the file back to the agent), import_kit. Resource: kit://<file name>. The kit format: SPEC.md (returned by get_kit_spec).
"""
import base64, io, json, os, sys, tempfile
import numpy as np
from PIL import Image as PILImage
from mcp.server.mcpserver import MCPServer, Image, Context
from mcp.types import EmbeddedResource, BlobResourceContents
from . import sheets, preview, kitfile, limits

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = open(os.path.join(HERE, 'SPEC.md')).read()
LOCAL_ = '--http' not in sys.argv
# exported kits land here: a folder the user can find (local), or a temporary one (a remote server)
WORK = os.environ.get('VIRADA_KIT_WORKDIR') or (os.path.expanduser('~/virada-kits') if LOCAL_ else tempfile.mkdtemp(prefix='virada-kit-'))
os.makedirs(WORK, exist_ok=True)
LOCAL = LOCAL_                # over HTTP the server never reads or writes paths it is given (only base64 in)
import collections
SESSIONS = collections.OrderedDict()   # one asset store per connected agent: {session: {name: PIL image}}
MAX_SESSIONS_KEPT = 24                  # a remote server keeps the pictures of the most recent agents only
MAX_SESSION_PX = 12_000_000             # and at most this many pixels of pictures per agent (two sheets and logos)
LIMITER = limits.Limiter()
def _assets(ctx):
    key = id(ctx.session) if ctx is not None and LOCAL is False else 'local'
    if key in SESSIONS: SESSIONS.move_to_end(key)
    while len(SESSIONS) >= MAX_SESSIONS_KEPT and key not in SESSIONS: SESSIONS.popitem(last=False)
    return SESSIONS.setdefault(key, {})
def _gate(ctx, tool):
    """None, or the reason this call must wait (remote servers only)."""
    if LOCAL: return None
    return LIMITER.take(limits.client_of(getattr(ctx, 'headers', None) if ctx is not None else None), tool)
def _hv(fn):
    """fn, run only when its turn comes: at most a few previews and exports at once on a remote server."""
    def run(*a, **k):
        if LOCAL: return fn(*a, **k)
        if not LIMITER.heavy.acquire(timeout=limits.HEAVY_WAIT):
            raise RuntimeError('busy: many kits are being worked on right now; try again in a minute')
        try: return fn(*a, **k)
        finally: LIMITER.heavy.release()
    return run

mcp = MCPServer('virada-kit', title='Virada kit maker', version='0.1.0',
                instructions='Makes cycling kits (jersey + bib shorts) for the Virada game from the user\'s reference '
                             'pictures. Start with get_kit_spec; preview and compare until the kit on the game\'s rider '
                             'matches the references; then export_kit.')

def _png(img, max_side=None):
    im = img if isinstance(img, PILImage.Image) else PILImage.fromarray((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8))
    im = im.convert('RGB')
    if max_side and max(im.size) > max_side: im.thumbnail((max_side, max_side))
    b = io.BytesIO(); im.save(b, 'PNG'); return Image(data=b.getvalue(), format='png')

def _open_image(path=None, base64_data=None):
    if path:
        if not LOCAL: raise ValueError('this server is remote: send the picture as base64, not a path')
        return PILImage.open(os.path.expanduser(path)).copy()
    if base64_data:
        if base64_data.startswith('data:'): base64_data = base64_data.split(',', 1)[1]
        return PILImage.open(io.BytesIO(base64.b64decode(base64_data))).copy()
    raise ValueError('give a path or base64 data')

def _kit(kit):
    if isinstance(kit, str): kit = json.loads(kit)
    return kit

@mcp.tool()
def get_kit_spec(ctx: Context = None) -> str:
    """The kit format and how to make a kit: the sheets and their panels, the layer types, the workflow. Read first."""
    why = _gate(ctx, 'get_kit_spec')
    if why: return why
    return SPEC

@mcp.tool()
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

@mcp.tool()
def add_asset(name: str, path: str | None = None, base64_png: str | None = None, ctx: Context = None) -> str:
    """Add a picture the kit uses: a logo for an 'image' layer (PNG with transparency is best) or a whole painted sheet
    for {"sheet": name}. Give a local file path or base64 PNG/JPEG data. Names: letters, digits, _ and -."""
    why = _gate(ctx, 'add_asset')
    if why: return why
    ASSETS = _assets(ctx)
    if not name or not all(c.isalnum() or c in '_-' for c in name): return 'name: letters, digits, _ and - only'
    im = _open_image(path, base64_png)
    if max(im.size) > kitfile.MAX_ASSET_PX and list(im.size) not in (sheets.LAYOUT['jersey']['size'], sheets.LAYOUT['bib']['size']):
        im.thumbnail((kitfile.MAX_ASSET_PX, kitfile.MAX_ASSET_PX))
    if not LOCAL:
        used = sum(a.size[0] * a.size[1] for n_, a in ASSETS.items() if n_ != name)
        if len(ASSETS) >= kitfile.MAX_ASSETS and name not in ASSETS: return f'at most {kitfile.MAX_ASSETS} pictures per kit'
        if used + im.size[0] * im.size[1] > MAX_SESSION_PX: return 'too many picture pixels for one kit: use smaller logos'
    ASSETS[name] = im.convert('RGBA')
    return f'added "{name}": {im.size[0]} x {im.size[1]} px' + (' (has transparency)' if im.mode in ('RGBA', 'LA', 'P') else ' (no transparency: it will be a rectangle)')

@mcp.tool()
def list_assets(ctx: Context = None) -> str:
    """The pictures added so far."""
    why = _gate(ctx, 'list_assets')
    if why: return why
    ASSETS = _assets(ctx)
    return json.dumps({n: list(im.size) for n, im in ASSETS.items()}) if ASSETS else 'no assets yet'

@mcp.tool()
def validate_kit(kit: dict, ctx: Context = None) -> str:
    """Check a kit object against the format. Returns 'valid' or the problems to fix."""
    why = _gate(ctx, 'validate_kit')
    if why: return why
    ASSETS = _assets(ctx)
    p = kitfile.validate(_kit(kit), ASSETS)
    return 'valid' if not p else 'problems:\n- ' + '\n- '.join(p)

@mcp.tool()
def render_sheets(kit: dict, ctx: Context = None) -> list:
    """The kit's two finished sheets as pictures (jersey, then bib), to check the flat layout."""
    why = _gate(ctx, 'render_sheets')
    if why: return [why]
    ASSETS = _assets(ctx)
    kit = _kit(kit); p = kitfile.validate(kit, ASSETS)
    if p: return ['problems:\n- ' + '\n- '.join(p)]
    js, bs = _hv(kitfile.render_sheets)(kit, ASSETS)
    return ['jersey sheet (2048 x 2048, shown smaller), then bib sheet (2048 x 1024)', _png(js, 1024), _png(bs, 1024)]

@mcp.tool()
def preview_kit(kit: dict, body: str = 'male', views: list[str] | None = None, ctx: Context = None) -> list:
    """The kit on the game's rider, in the game's look. body: 'male' or 'female'. views (any of front, front34_left,
    left, back, right, front34_right; default front, front34_left, back). front34_left = the front turned to show the
    rider's left side, like most product photos."""
    why = _gate(ctx, 'preview_kit')
    if why: return [why]
    ASSETS = _assets(ctx)
    kit = _kit(kit); p = kitfile.validate(kit, ASSETS)
    if p: return ['problems:\n- ' + '\n- '.join(p)]
    views = views or ['front', 'front34_left', 'back']
    bad = [v for v in views if v not in preview.VIEWS]
    if bad: return [f'unknown views {bad}; use {list(preview.VIEWS)}']
    ims = _hv(kitfile.previews)(kit, ASSETS, bodies=(body,), views=tuple(views))
    return [f'{body}: ' + ', '.join(views), _png(preview.sheet_of_views(list(ims.values()), views, cols=min(3, len(views)), scale=0.6))]

@mcp.tool()
def compare_to_reference(kit: dict, reference_path: str | None = None, reference_base64: str | None = None,
                         body: str = 'male', view: str = 'front34_left', jersey_only: bool = True, ctx: Context = None) -> list:
    """The user's reference picture beside the kit on the game's rider from a similar angle, to spot what differs
    (colours, where panels and logos sit, sizes). Pick the view nearest the reference's angle. The rider is cropped to
    the jersey (jersey_only, default) or to the jersey and bibs, as product pictures are framed. If you can't send the
    picture's bytes (a chat app), leave the reference out: you get the rider's views alone to set beside the picture
    you can see."""
    why = _gate(ctx, 'compare_to_reference')
    if why: return [why]
    ASSETS = _assets(ctx)
    kit = _kit(kit); p = kitfile.validate(kit, ASSETS)
    if p: return ['problems:\n- ' + '\n- '.join(p)]
    ref = _open_image(reference_path, reference_base64).convert('RGB') if (reference_path or reference_base64) else None
    vs = [view] + (['front'] if view != 'front' else [])          # and straight on: centring and size read true there
    ims = _hv(kitfile.previews)(kit, ASSETS, bodies=(body,), views=tuple(vs))
    crops = [preview.crop_to_kit(ims[f'{body}_{v}'], body, v, jersey_only=jersey_only) for v in vs]
    pics, labs = ([ref] if ref else []) + crops, (['reference'] if ref else []) + [f'{body} {v}' for v in vs]
    return [('left: the reference; then ' if ref else '') + f'the kit on the {body} rider: {", ".join(vs)}. Judge centring '
            'and size on the straight front view: a three-quarter picture squeezes the side turned away.',
            _png(preview.sheet_of_views(pics, labs, cols=len(pics), scale=0.6))]

def _kit_blob(path):
    name = os.path.basename(path)
    return EmbeddedResource(resource=BlobResourceContents(uri=f'kit://{name}', mimeType='application/zip',
                                                          blob=base64.b64encode(open(path, 'rb').read()).decode()))

@mcp.tool()
def export_kit(kit: dict, path: str | None = None, ctx: Context = None) -> list:
    """Write the kit file (.kit.zip: kit.json, the two finished sheets, its pictures, previews) and hand it back: the
    result carries the file itself (an embedded resource, application/zip, also readable later as kit://<file name>)
    for you to save or pass on, plus where the server wrote it (path: local servers; default its work folder) and a
    preview to check."""
    why = _gate(ctx, 'export_kit')
    if why: return [why]
    ASSETS = _assets(ctx)
    kit = _kit(kit)
    path = os.path.expanduser(path) if (path and LOCAL) else os.path.join(WORK, ''.join(c if c.isalnum() else '_' for c in kit.get('name', 'kit')).strip('_').lower() or 'kit')
    try: out = _hv(kitfile.export)(kit, ASSETS, path)
    except ValueError as e: return [f'not exported, problems: {e}']
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

@mcp.resource('kit://{name}', name='kit file', description='A kit file this server exported (.kit.zip)', mime_type='application/zip')
def kit_file(name: str) -> bytes:
    p = EXPORTED.get(name) or os.path.join(WORK, name)
    if not os.path.exists(p) or not name.endswith('.kit.zip'): raise ValueError(f'no exported kit {name}')
    return open(p, 'rb').read()

@mcp.tool()
def import_kit(path: str | None = None, base64_zip: str | None = None, ctx: Context = None) -> list:
    """Open a .kit.zip (made here or elsewhere) to keep working on it: returns its kit object (to edit and pass to the
    other tools) and adds its pictures as assets; also shows it on the riders."""
    why = _gate(ctx, 'import_kit')
    if why: return [why]
    ASSETS = _assets(ctx)
    if path:
        if not LOCAL: return ['this server is remote: send the file as base64, not a path']
        src = os.path.expanduser(path)
    elif base64_zip:
        src = os.path.join(WORK, 'imported.kit.zip'); open(src, 'wb').write(base64.b64decode(base64_zip.split(',', 1)[-1]))
    else: return ['give a path or base64_zip']
    kit, assets, js, bs = kitfile.load(src); ASSETS.update({n: im.convert('RGBA') for n, im in assets.items()})
    for k in ('format', 'version', 'exported'): kit.pop(k, None)
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
