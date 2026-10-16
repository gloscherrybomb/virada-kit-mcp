"""The look's colour rules: the designed shadow colour of a lit colour (cloth: darker, the hue turned towards
violet-blue, a little richer; skin: less dark, turned towards red). Designer sRGB 0..1, texel by texel."""
import numpy as np

RULES = {
    'cloth': dict(light=0.62, sat=1.08, hue_to=0.70, hue_step=12.0, grey_sat=0.25),
    'skin':  dict(light=0.80, sat=1.15, hue_to=0.00, hue_step=6.0, grey_sat=0.25),
}

def shadow_of(rgb, kind='cloth'):
    """(..., 3) designer sRGB -> its shadow colour."""
    r = RULES[kind]; rgb = np.asarray(rgb, np.float64)
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1); l = (mx + mn) / 2; d = mx - mn
    with np.errstate(divide='ignore', invalid='ignore'):
        s = np.where(d < 1e-9, 0.0, d / np.where(l <= 0.5, mx + mn, 2 - mx - mn))
        rc, gc, bc = (mx - R) / d, (mx - G) / d, (mx - B) / d
        h = np.where(R == mx, bc - gc, np.where(G == mx, 2 + rc - bc, 4 + gc - rc))
    h = np.where(d < 1e-9, 0.0, (h / 6) % 1)
    step = r['hue_step'] / 360; dh = (r['hue_to'] - h + 0.5) % 1 - 0.5
    hc, sc = (h + np.clip(dh, -step, step)) % 1, np.minimum(1.0, s * r['sat'])
    grey = d < 0.08
    h = np.where(grey, r['hue_to'] if kind == 'cloth' else 0.02, hc); s = np.where(grey, r['grey_sat'], sc)
    l = l * r['light']
    q = np.where(l < 0.5, l * (1 + s), l + s - l * s); p = 2 * l - q
    def hue(t):
        t = t % 1
        return np.where(t < 1 / 6, p + (q - p) * 6 * t, np.where(t < 0.5, q, np.where(t < 2 / 3, p + (q - p) * (2 / 3 - t) * 6, p)))
    out = np.stack([hue(h + 1 / 3), hue(h), hue(h - 1 / 3)], -1)
    return np.where((s == 0)[..., None], l[..., None], out).astype(np.float32)
