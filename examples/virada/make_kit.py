# Acting as the agent: the VIRADA jersey from the owner's reference picture, as layers.
import json, sys
MAROON=[0.40,0.12,0.16]; MAROON_D=[0.30,0.08,0.11]; CORAL=[0.97,0.36,0.33]; WHITE=[0.95,0.95,0.96]; PINK=[0.93,0.55,0.55]; CHAR=[0.19,0.19,0.21]
def V(cx, top, h, w=None, down=1, white=WHITE, coral=CORAL, one=None, panel=None):
    """The V mark: a white stroke (left) and a coral stroke (right) meeting at the bottom. down=-1 for sleeves (v grows downwards)."""
    w = w or h * 0.95; bot = top - down * h
    L = [[cx - w/2, top], [cx - w/2 + w*0.32, top], [cx + w*0.06, bot], [cx - w*0.08, bot]]
    R = [[cx + w/2 - w*0.36, top], [cx + w/2, top], [cx + w*0.10, bot], [cx - w*0.06, bot]]
    ps = {'panels': [panel]} if panel else {}
    if one: return [{'type': 'shape', 'points': L, 'colour': one, **ps}, {'type': 'shape', 'points': R, 'colour': one, **ps}]
    return [{'type': 'shape', 'points': L, 'colour': white, **ps}, {'type': 'shape', 'points': R, 'colour': coral, 'opacity': 0.9, **ps}]
jersey = [
    {'type': 'fill', 'colour': MAROON},
    # the rider's right side: a white side panel from the armpit to the hem, a coral piping line along its edge
    {'type': 'shape', 'panels': ['front'], 'points': [[0, 0], [0.2, 0], [0.17, 0.45], [0.12, 0.84], [0, 0.84]], 'colour': WHITE},
    {'type': 'line', 'panels': ['front'], 'points': [[0.215, 0.0], [0.19, 0.42]], 'width': 0.004, 'colour': CORAL},
    {'type': 'shape', 'panels': ['back'], 'points': [[1, 0], [0.8, 0], [0.83, 0.45], [0.88, 0.84], [1, 0.84]], 'colour': WHITE},
    # the rider's left side: a darker mesh side panel
    {'type': 'u_band', 'panels': ['front'], 'u': [0.9, 1.0], 'colour': MAROON_D},
    {'type': 'u_band', 'panels': ['back'], 'u': [0.0, 0.1], 'colour': MAROON_D},
    # the coral yoke over the left shoulder, front and back
    {'type': 'shape', 'panels': ['front'], 'points': [[0.6, 1.01], [1.01, 1.01], [1.01, 0.8], [0.88, 0.86], [0.72, 0.94]], 'colour': CORAL},
    {'type': 'shape', 'panels': ['back'], 'points': [[-0.01, 1.01], [0.4, 1.01], [0.28, 0.94], [0.12, 0.86], [-0.01, 0.8]], 'colour': CORAL},
    # the coral lines low on the left front: angled, like the reference's
    {'type': 'line', 'panels': ['front'], 'points': [[0.86, 0.58], [0.70, 0.34], [0.66, 0.0]], 'width': 0.004, 'colour': CORAL},
    {'type': 'line', 'panels': ['front'], 'points': [[0.88, 0.50], [0.74, 0.31], [0.72, 0.10]], 'width': 0.004, 'colour': CORAL},
    {'type': 'line', 'panels': ['front'], 'points': [[0.83, 0.39], [0.71, 0.25]], 'width': 0.003, 'colour': CORAL},
    {'type': 'shape', 'panels': ['front'], 'points': [[0.78, 0.62], [0.86, 0.66], [0.74, 0.40], [0.70, 0.42]], 'colour': MAROON_D, 'opacity': 0.8},
    # the chest: the big V, VIRADA, CYCLING VIRTUAL
    *V(0.5, 0.80, 0.21, w=0.25, panel='front'),
    {'type': 'text', 'panel': 'front', 'text': 'VIRADA', 'at': [0.5, 0.545], 'height': 0.075, 'colour': WHITE, 'font': 'Montserrat', 'weight': 600, 'letter_spacing': 0.16},
    {'type': 'text', 'panel': 'front', 'text': 'CYCLING VIRTUAL', 'at': [0.5, 0.49], 'height': 0.028, 'colour': PINK, 'font': 'Montserrat', 'weight': 500, 'letter_spacing': 0.36},
    # the small V on the right chest, under the shoulder
    *V(0.25, 0.90, 0.075, w=0.085, panel='front', white=CORAL, coral=CORAL),
    # sleeves: the right one white, the left one coral with a maroon V towards the hem, on its outside
    {'type': 'fill', 'panels': ['sleeve_r'], 'colour': WHITE},
    {'type': 'fill', 'panels': ['sleeve_l'], 'colour': CORAL},
    *V(0.42, 0.40, 0.30, w=0.16, down=-1, one=MAROON, panel='sleeve_l'),
    {'type': 'fill', 'panels': ['collar'], 'colour': MAROON},
]
kit = {'name': 'Virada', 'author': 'the owner (reference) / Claude (kit)', 'description': 'The Virada team jersey from the owner\'s product picture.',
       'jersey': {'layers': jersey, 'zip': [0.22, 0.06, 0.09]},
       'bib': {'layers': [{'type': 'fill', 'colour': CHAR}]},
       'socks': [0.96, 0.95, 0.92],
       'provenance': {'made_with': 'Claude (by hand, through the virada-kit tools)', 'references': ['owner: product picture, front three-quarter from the left'],
                      'invented': ['the back (continued the side panels and the yoke; plain otherwise)', 'the bibs (plain charcoal, as in the picture)', 'the right sleeve\'s back']}}
json.dump(kit, open(sys.argv[1], 'w'), indent=1)
