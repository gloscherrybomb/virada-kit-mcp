import json, os, zipfile
import numpy as np
from PIL import Image
from virada_kit import sheets, kitfile, preview, shade

EX = os.path.join(os.path.dirname(sheets.__file__), 'data', 'examples')

def kit_of(j='red_chevron', b='bib_black'):
    jd = json.load(open(os.path.join(EX, j + '.json'))); bd = json.load(open(os.path.join(EX, b + '.json')))
    return {'name': jd['name'], 'jersey': {'layers': jd['layers'], 'zip': jd.get('zip', [0.1, 0.1, 0.1])}, 'bib': {'layers': bd['layers']}}

def test_panel_corners():
    assert sheets.to_sheet('front', 0.0, 1.0) == (0.0, 0.0)
    assert sheets.to_sheet('back', 0.0, 0.0) == (0.5, 0.5)
    assert sheets.to_sheet('sleeve_l', 1.0, 0.0) == (1.0, 0.5)          # sleeves: v = 0 at the armhole, the panel's top

def test_shape_lands_where_asked():
    im = sheets.render({'background': [0, 0, 0], 'layers': [{'type': 'shape', 'panels': ['front'], 'points': [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]], 'colour': [1, 1, 1]}]}, 'jersey')
    on = np.nonzero(im[:1024, :1024, 0] > 0.5)
    assert abs(on[0].min() / 1024 - 0.25) < 0.003 and abs(on[1].max() / 1024 - 0.75) < 0.003
    assert im[:1024, 1024:, 0].max() == 0                             # nothing on BACK

def test_text_and_painted_sheet_mix():
    base = Image.new('RGB', (2048, 2048), (255, 0, 0))
    im = sheets.render({'sheet': base, 'layers': [{'type': 'text', 'panel': 'front', 'text': 'AB', 'at': [0.5, 0.5], 'height': 0.1, 'colour': [0, 0, 1]}]}, 'jersey')
    assert im[0, 0, 0] == 1.0 and (im[:1024, :1024, 2] > 0.9).sum() > 500

def test_validate_catches_mistakes():
    k = kit_of(); assert kitfile.validate(k, {}) == []
    k['jersey']['layers'].append({'type': 'band', 'panels': ['frontt'], 'v': [0, 1], 'colour': [2, 0, 0]})
    probs = ' '.join(kitfile.validate(k, {}))
    assert 'frontt' in probs and 'colour' in probs

def test_previews_cover_every_view():
    js, bs = kitfile.render_sheets(kit_of(), {})
    for b in ('male', 'female'):
        for v in preview.VIEWS:
            im = preview.render_view(js, bs, b, v)
            assert im.shape == (1024, 768, 3) and np.isfinite(im).all()

def test_export_round_trip(tmp_path):
    p = kitfile.export(kit_of(), {}, str(tmp_path / 'k'))
    with zipfile.ZipFile(p) as z:
        names = z.namelist()
    assert {'kit.json', 'jersey.png', 'bib.png'} <= set(names) and any(n.startswith('previews/') for n in names)
    kit, assets, js, bs = kitfile.load(p)
    assert kit['format'] == 'virada-kit' and js.shape == (2048, 2048, 3) and bs.shape == (1024, 2048, 3)

def test_shadow_rule_greys_get_a_tint():
    s = shade.shadow_of(np.array([0.96, 0.96, 0.96]), 'cloth')
    assert s[2] > s[0]                                                # white's shadow turns violet-blue
