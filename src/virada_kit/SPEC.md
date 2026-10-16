# Virada kit format, version 1

You are making a cycling kit (a jersey and bib shorts) for the game's riders. The game paints every rider, male or
female, from two flat pictures called **sheets**. Your job: turn the user's reference images into a kit that looks the
same on the game's rider, and export it as a `.kit.zip`.

## The sheets

**Jersey sheet: 2048 x 2048 px.** Panels (pixel rectangles x, y, width, height from the top-left):

| panel | rect | seen as | u (across, 0..1) | v (0..1) |
|---|---|---|---|---|
| `front` | 0, 0, 1024, 1024 | from the front | rider's RIGHT side seam (left edge) to LEFT side seam (right edge) | 0 = lowest hem (bottom edge), 1 = shoulders (top edge) |
| `back` | 1024, 0, 1024, 1024 | from behind | rider's LEFT side seam (left edge) to RIGHT side seam | 0 = hem, 1 = shoulders |
| `sleeve_r` | 0, 1024, 1024, 512 | the right arm from the right, hanging | top of the arm in the middle (u 0.5), underseam at both edges; u < 0.5 is the BACK of the arm | 0 = armhole (TOP edge), 1 = hem (bottom edge) |
| `sleeve_l` | 1024, 1024, 1024, 512 | the left arm from the left, hanging | top of the arm in the middle; u < 0.5 is the FRONT of the arm | 0 = armhole (TOP edge), 1 = hem |
| `collar` | 0, 1536, 2048, 128 | from the front | front of the neck in the middle, back of the neck at both ends | 0 = seam, 1 = top edge |

The rest of the jersey sheet (y > 1664) is unused. FRONT's right edge joins BACK's left edge (the rider's left side);
BACK's right edge joins FRONT's left edge (the right side).

**Bib sheet: 2048 x 1024 px.**

| panel | rect | seen as | u | v |
|---|---|---|---|---|
| `leg_r` | 0, 0, 1024, 1024 | the right leg from the right | outside of the leg in the middle, inside seam at both edges; u > 0.5 is the FRONT of the leg | 0 = gripper hem (bottom edge), 1 = waist |
| `leg_l` | 1024, 0, 1024, 1024 | the left leg from the left | outside in the middle; u < 0.5 is the FRONT | 0 = gripper hem, 1 = waist |

Text drawn upright on any panel reads correctly on the rider (nothing is mirrored).

**Where things land on the body** (the same on every body, within a few per cent):
- the zip runs up FRONT at u = 0.5; the three rear pockets are on BACK, v about 0.08-0.36, u about 0.22-0.78;
- the chest is around v 0.40-0.60 on FRONT; the shoulder tops are the top ~8% of FRONT and BACK (keep fine detail
  out of there: it wraps over the shoulder);
- the cuff band is the bottom ~22% of each sleeve (v 0.78-1); the gripper is the bottom ~10% of each leg (v 0-0.10);
- the bib's top half (v > 0.55) is mostly under the jersey.
The guide pictures (`get_template`) show each body's exact edges, seams, zip and pockets on the sheets.

The game draws its own hems, seams, zip, pocket openings, folds and the silicone dots on cuffs and gripper over your
design, and shades it in its comic look. Paint flat colour: no shading, no folds, no fabric texture, no shadows.

## Two ways to make a sheet

**A. Layers (any model).** Describe the design as layers drawn in order (later ones on top):

| type | fields | draws |
|---|---|---|
| `fill` | colour | the whole panel |
| `gradient` | v [a, b], from, to | a vertical colour fade |
| `band` | v [a, b], colour | a band across the panel |
| `u_band` | u [a, b], colour | a band down the panel |
| `edges` | width, colour | both side edges (side panels), width as a fraction of the panel |
| `chevron` | v, depth, width, colour | a V across the panel (depth > 0 points up in the middle) |
| `stripes` | angle, pitch, width, colour, offset? | parallel stripes (angle in degrees from level; pitch and width in panel heights) |
| `dots` | v [a, b], pitch, max?, colour | a halftone of dots fading from v a (full) to b (none) |
| `shape` | points [[u, v], ...], colour | a filled polygon |
| `line` | points [[u, v], ...], width, colour | a polyline (width in panel heights) |
| `text` | text, panel, at [u, v], height, colour, font?, weight?, letter_spacing?, rotation? | text centred at `at`; height = capital height as a fraction of the panel's height; fonts: Montserrat, Oswald (weights 100-900) |
| `image` | asset, panel, at [u, v], width or height, rotation?, tint?, opacity? | a logo picture (PNG with transparency, added with `add_asset`), centred at `at` |

Every layer except text and image takes `panels` (a list; `"sleeve*"` means both sleeves; default all panels of that
sheet), `opacity`, and `clip` (a polygon [[u, v], ...]: draw only inside it). Bands, shapes, chevrons and lines can
take `edge`: {"width": 0.003, "dark": 0.45} for a printed outline. Shapes and lines use the panel's height as the unit
across too, so a shape keeps its proportions.

**B. A painted sheet (image models).** Paint the whole sheet as one picture at exactly the sheet's size, laid out as
above: start from `get_template(style="clean")` (white panels, their names, which way is up, the zip line, the
pockets, the cuff and gripper bands) and paint over all of it, leaving no outlines or words. Add it with `add_asset`
and use `{"sheet": "<asset name>"}` for that part. Keep each panel's contents inside its rectangle; carry a design
across a seam by matching the edges (FRONT's right edge = BACK's left edge). If your picture comes out a different
size, resize it to the sheet's size exactly. You can mix the two: give both `"sheet"` and `"layers"`, and the layers are
drawn on top of the painted sheet (crisp text and logos over a painted background).

## In a chat app (Gemini, Claude.ai, ChatGPT)
The server is remote there: it can't read files, and you usually can't send it the user's pictures. That's fine:
look at the user's pictures yourself, build the kit from **layers** (shapes, bands, text and the rest draw logos and
marks well), call `preview_kit` and `compare_to_reference` (without the reference: set the rider's views beside the
picture you can see), and `export_kit`; give the user the download link it returns. Pass the kit as a JSON object.

## Workflow
0. **Complete the references first.** A kit needs the FRONT, the BACK and both sleeves; a product picture usually shows
   one side. If the user gave no back (or side) view, make one before building: with an image model, draw the
   missing views in the same design language (a front and a back flat drawing of the jersey and the bibs, laid flat,
   facing the viewer, no model, no shading) and show them to the user to approve or change; without one, describe the
   back you propose and ask. Record every view you made in `provenance.invented`.
1. `get_kit_spec` (this), `get_template` for the guide pictures.
2. Look at the references: list the colours (as sRGB 0..1), the panels, the logos and text, and where each sits on the
   body. Note what the references don't show (often the back, the far sleeve, the bibs).
3. Add logos with `add_asset` (crop them cleanly from the reference or use files the user gives; transparent PNG).
   Measure from the references against landmarks, not the picture's edges: a chest logo is usually centred on the
   zip (FRONT u = 0.5); a three-quarter photo squeezes the side turned away, so things look off-centre in it.
4. Write the kit; `preview_kit` to see it on the riders; `compare_to_reference` with the user's picture and the view
   nearest its angle (`front34_left` = the rider's front turned to show their left side); fix what differs and repeat.
   Check both bodies (male, female) and the back.
5. `validate_kit`, then `export_kit`: it returns the `.kit.zip` itself (attached to the result, and as the resource
   `kit://<file name>`); save it for the user or hand it on. `import_kit` opens a kit file to keep working on it. Fill `provenance`: what you made it with, the references, and `invented`: the
   parts you made up because no reference showed them.

Names and logos: only use names, logos and designs the user owns or made. Submitted kits are reviewed before they
appear in the game.

## Example (layers)
```json
{"name": "Red chevron", "author": "you",
 "jersey": {"layers": [
    {"type": "fill", "colour": [0.96, 0.96, 0.94]},
    {"type": "chevron", "panels": ["front", "back"], "v": 0.52, "depth": -0.12, "width": 0.10, "colour": [0.84, 0.13, 0.15]},
    {"type": "edges", "panels": ["front", "back"], "width": 0.10, "colour": [0.11, 0.11, 0.13]},
    {"type": "fill", "panels": ["sleeve*"], "colour": [0.11, 0.11, 0.13]},
    {"type": "band", "panels": ["sleeve*"], "v": [0.78, 1.0], "colour": [0.84, 0.13, 0.15]},
    {"type": "text", "panel": "front", "text": "RED", "at": [0.5, 0.62], "height": 0.05, "colour": [0.11, 0.11, 0.13], "font": "Oswald", "weight": 600}],
   "zip": [0.11, 0.11, 0.13]},
 "bib": {"layers": [{"type": "fill", "colour": [0.11, 0.11, 0.13]}, {"type": "band", "v": [0, 0.104], "colour": [0.2, 0.2, 0.23]}]},
 "provenance": {"made_with": "...", "references": ["user's front photo"], "invented": ["the back", "the bibs"]}}
```
