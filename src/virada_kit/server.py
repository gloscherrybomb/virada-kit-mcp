"""The Virada kit MCP server: an AI agent turns a user's kit pictures into a kit file the game can use.

Run it locally (stdio): `uvx virada-kit` or `uv run virada-kit`; or over HTTP: `virada-kit --http [--port 8000]`.
Tools: get_kit_spec, get_template, add_asset, list_assets, render_sheets, preview_kit, compare_to_reference,
validate_kit, export_kit. The kit format: SPEC.md (returned by get_kit_spec).
"""
import base64, io, json, os, sys, tempfile
import numpy as np
from PIL import Image as PILImage
from mcp.server.mcpserver import MCPServer, Image
from . import sheets, preview, kitfile

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = open(os.path.join(HERE, 'SPEC.md')).read()
WORK = os.environ.get('VIRADA_KIT_WORKDIR') or tempfile.mkdtemp(prefix='virada-kit-')
ASSETS: dict = {}            # name -> PIL image (this server's session)
LOCAL = '--http' not in sys.argv   # over HTTP the server never reads or writes paths it is given (only base64 in)

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
def get_kit_spec() -> str:
    """The kit format and how to make a kit: the sheets and their panels, the layer types, the workflow. Read first."""
    return SPEC

@mcp.tool()
def get_template(sheet: str = 'jersey', style: str = 'guide', save_to: str | None = None) -> list:
    """A sheet's template ('jersey' 2048x2048 or 'bib' 2048x1024). style 'guide': the panels and where the game's male
    (blue) and female (pink) riders' kit edges, seams, zip and pockets fall, for placing layers. style 'clean': white
    panels with thin outlines, names and which way is up, the zip line, pockets, cuff and gripper bands: the canvas to
    paint a whole sheet on (route B, e.g. with an image model; paint everything, leave no outlines or words).
    save_to: also write the full-size PNG to this path (local servers)."""
    im = sheets.clean_template(sheet) if style == 'clean' else PILImage.open(os.path.join(sheets.DATA, f'sheet_guide_{sheet}.png'))
    note = f'{sheet} sheet guide, full size {im.size[0]} x {im.size[1]} px (shown smaller).'
    if save_to and LOCAL:
        im.save(os.path.expanduser(save_to)); note += f' Saved full size to {save_to}.'
    return [note, _png(im, 1400)]

@mcp.tool()
def add_asset(name: str, path: str | None = None, base64_png: str | None = None) -> str:
    """Add a picture the kit uses: a logo for an 'image' layer (PNG with transparency is best) or a whole painted sheet
    for {"sheet": name}. Give a local file path or base64 PNG/JPEG data. Names: letters, digits, _ and -."""
    if not name or not all(c.isalnum() or c in '_-' for c in name): return 'name: letters, digits, _ and - only'
    im = _open_image(path, base64_png)
    if max(im.size) > kitfile.MAX_ASSET_PX and list(im.size) not in (sheets.LAYOUT['jersey']['size'], sheets.LAYOUT['bib']['size']):
        im.thumbnail((kitfile.MAX_ASSET_PX, kitfile.MAX_ASSET_PX))
    ASSETS[name] = im.convert('RGBA')
    return f'added "{name}": {im.size[0]} x {im.size[1]} px' + (' (has transparency)' if im.mode in ('RGBA', 'LA', 'P') else ' (no transparency: it will be a rectangle)')

@mcp.tool()
def list_assets() -> str:
    """The pictures added so far."""
    return json.dumps({n: list(im.size) for n, im in ASSETS.items()}) if ASSETS else 'no assets yet'

@mcp.tool()
def validate_kit(kit: dict) -> str:
    """Check a kit object against the format. Returns 'valid' or the problems to fix."""
    p = kitfile.validate(_kit(kit), ASSETS)
    return 'valid' if not p else 'problems:\n- ' + '\n- '.join(p)

@mcp.tool()
def render_sheets(kit: dict) -> list:
    """The kit's two finished sheets as pictures (jersey, then bib), to check the flat layout."""
    kit = _kit(kit); p = kitfile.validate(kit, ASSETS)
    if p: return ['problems:\n- ' + '\n- '.join(p)]
    js, bs = kitfile.render_sheets(kit, ASSETS)
    return ['jersey sheet (2048 x 2048, shown smaller), then bib sheet (2048 x 1024)', _png(js, 1024), _png(bs, 1024)]

@mcp.tool()
def preview_kit(kit: dict, body: str = 'male', views: list[str] | None = None) -> list:
    """The kit on the game's rider, in the game's look. body: 'male' or 'female'. views (any of front, front34_left,
    left, back, right, front34_right; default front, front34_left, back). front34_left = the front turned to show the
    rider's left side, like most product photos."""
    kit = _kit(kit); p = kitfile.validate(kit, ASSETS)
    if p: return ['problems:\n- ' + '\n- '.join(p)]
    views = views or ['front', 'front34_left', 'back']
    bad = [v for v in views if v not in preview.VIEWS]
    if bad: return [f'unknown views {bad}; use {list(preview.VIEWS)}']
    ims = kitfile.previews(kit, ASSETS, bodies=(body,), views=tuple(views))
    return [f'{body}: ' + ', '.join(views), _png(preview.sheet_of_views(list(ims.values()), views, cols=min(3, len(views)), scale=0.6))]

@mcp.tool()
def compare_to_reference(kit: dict, reference_path: str | None = None, reference_base64: str | None = None,
                         body: str = 'male', view: str = 'front34_left', jersey_only: bool = True) -> list:
    """The user's reference picture beside the kit on the game's rider from a similar angle, to spot what differs
    (colours, where panels and logos sit, sizes). Pick the view nearest the reference's angle. The rider is cropped to
    the jersey (jersey_only, default) or to the jersey and bibs, as product pictures are framed."""
    kit = _kit(kit); p = kitfile.validate(kit, ASSETS)
    if p: return ['problems:\n- ' + '\n- '.join(p)]
    ref = _open_image(reference_path, reference_base64).convert('RGB')
    vs = [view] + (['front'] if view != 'front' else [])          # and straight on: centring and size read true there
    ims = kitfile.previews(kit, ASSETS, bodies=(body,), views=tuple(vs))
    crops = [preview.crop_to_kit(ims[f'{body}_{v}'], body, v, jersey_only=jersey_only) for v in vs]
    return [f'left: the reference; then the kit on the {body} rider: {", ".join(vs)}. Judge centring and size on the '
            'straight front view: a three-quarter picture squeezes the side turned away.',
            _png(preview.sheet_of_views([ref] + crops, ['reference'] + [f'{body} {v}' for v in vs], cols=len(vs) + 1, scale=0.6))]

@mcp.tool()
def export_kit(kit: dict, path: str | None = None) -> list:
    """Write the kit file (.kit.zip: kit.json, the two finished sheets, its pictures, previews). path: where (local
    servers; default the server's work folder). Returns the file's path and a preview to check."""
    kit = _kit(kit)
    path = os.path.expanduser(path) if (path and LOCAL) else os.path.join(WORK, ''.join(c if c.isalnum() else '_' for c in kit.get('name', 'kit')).strip('_').lower() or 'kit')
    try: out = kitfile.export(kit, ASSETS, path)
    except ValueError as e: return [f'not exported, problems: {e}']
    ims = kitfile.previews(kit, ASSETS, bodies=('male', 'female'), views=('front34_left',))
    return [f'exported {out} ({os.path.getsize(out) // 1024} KB). Send this file in to have it reviewed for the game.',
            _png(preview.sheet_of_views(list(ims.values()), ['male', 'female'], cols=2, scale=0.5))]

def main():
    if '--http' in sys.argv:
        port = int(sys.argv[sys.argv.index('--port') + 1]) if '--port' in sys.argv else 8000
        mcp.run('streamable-http', port=port)
    else:
        mcp.run()

if __name__ == '__main__':
    main()
