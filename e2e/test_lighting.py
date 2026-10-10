"""E2E: the lighting — faces that look different ways read apart (issue #47 item 6).

A soft room around the model (three's RoomEnvironment as a light probe) under
a key light and a dim fill. On the plate of mini_mold.step (a box of a known
grey) and its cavity block (a known blue):

1. Head on (the six view presets), the face toward the camera: the top is the
   brightest by a clear step, the bottom the darkest; none is washed out (a
   mid grey stays well below white) and none sinks into the background.
2. At the load view the three faces seen together (the top, the front -Y, the
   right +X) are each a clear step apart (on the grey plate: a step in sRGB
   levels shrinks with a darker colour), and the top is the brightest of the
   three on the blue block too.
3. A coloured part keeps its colour on every face seen: lit, its chroma is its
   own (lighting scales a colour; it does not turn it or wash it with grey).

Oracles: the known shapes and colours of testdata/make_step_assembly.py (the
plate 0..100 x 0..60 x 0..15, linear RGB (0.6, 0.6, 0.62); the cavity block
30..70 x 15..45 x 15..35, (0.15, 0.3, 0.75)), window.__cadProject /
__cadPick (each pixel read is on the face meant), canvas pixels, the spec's
background #1d2126. The steps below are the spec's, not read from the code.
"""
from nav_common import nav_session

SCENE = (0x1D, 0x21, 0x26)
STEP = 15  # a difference in brightness one sees at a glance (sRGB levels of luma)
WHITE_MAX = 230  # a mid grey (0.6 linear, sRGB 203 unlit) is drawn below this on every face
OVER_SCENE = 40  # and at least this much over the background
BLUE = (0.15, 0.3, 0.75)

# (preset, the plate's face toward the camera, a point on it, the coordinate the pick must hold)
HEAD_ON = (
    ("上", "+Z", (8, 8, 15), (2, 15)),
    ("下", "-Z", (50, 30, 0), (2, 0)),
    ("正面", "-Y", (50, 0, 7.5), (1, 0)),
    ("背面", "+Y", (50, 60, 7.5), (1, 60)),
    ("右", "+X", (100, 30, 7.5), (0, 100)),
    ("左", "-X", (0, 30, 7.5), (0, 0)),
)
SIDES = ("-Y", "+Y", "+X", "-X")
# at the load view: the plate's and the block's three faces seen together
LOAD_VIEW = {
    "plate +Z": ((8, 8, 15), (2, 15)),
    "plate -Y": ((50, 0, 7.5), (1, 0)),
    "plate +X": ((100, 30, 7.5), (0, 100)),
    "block +Z": ((50, 30, 35), (2, 35)),
    "block -Y": ((50, 15, 25), (1, 15)),
    "block +X": ((70, 18, 25), (0, 70)),  # clear of the core pin at x 75
}


def luma(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def lin(v):
    v /= 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def chroma(rgb_lin):
    s = sum(rgb_lin)
    return [x / s for x in rgb_lin]


with nav_session() as n:
    page = n.page
    n.stub_sidecar()
    n.load(n.paths["step"])

    def spot(img, xy):
        """the drawn colour around a page point (3 x 3 median of a 5 x 5 spot)"""
        cl, ct, cw, ch = n.canvas_rect()
        sx, sy = img.width / cw, img.height / ch
        px = [img.getpixel((int((xy[0] - cl) * sx) + dx, int((xy[1] - ct) * sy) + dy)) for dx in (-2, 0, 2) for dy in (-2, 0, 2)]
        return tuple(sorted(p[i] for p in px)[len(px) // 2] for i in range(3))

    def read(points):
        """{name: drawn colour} for {name: (a point on a face, (axis, value) the pick must hold)}"""
        n.settle()
        img = n.canvas_image()
        out = {}
        for name, (at, (axis, value)) in points.items():
            xy = n.project(at)
            hit = n.pick(xy)
            assert hit and abs(hit["point"][axis] - value) < 0.05, (name, "the pixel is not on the face", at, hit)
            out[name] = spot(img, xy)
        return out

    # ---- 1. head on: the top the brightest, the bottom the darkest, none washed out or lost
    head = {}
    for preset, face, at, pick in HEAD_ON:
        n.click_button(preset)
        head[face] = read({face: (at, pick)})[face]
    lum = {f: round(luma(c), 1) for f, c in head.items()}
    print("1 head on", lum)
    for f in SIDES:
        assert lum["+Z"] - lum[f] >= STEP, ("1 the top must be the brightest by a clear step", f, lum)
        assert lum[f] - lum["-Z"] >= STEP, ("1 the bottom must be the darkest by a clear step", f, lum)
    scene = luma(SCENE)
    for f, v in lum.items():
        assert v <= WHITE_MAX, ("1 washed out", f, lum)
        assert v - scene >= OVER_SCENE, ("1 lost in the background", f, lum)

    # ---- 2. the load view: the three faces seen together, each a clear step apart
    n.click_button("等角")
    n.fit()
    seen = read(LOAD_VIEW)
    lv = {k: round(luma(c), 1) for k, c in seen.items()}
    print("2 load view", lv)
    plate = ["plate +Z", "plate -Y", "plate +X"]
    for i in range(3):
        for j in range(i + 1, 3):
            a, b = plate[i], plate[j]
            assert abs(lv[a] - lv[b]) >= STEP, ("2 two faces seen together look alike", a, b, lv)
    for part in ("plate", "block"):
        faces = [f"{part} +Z", f"{part} -Y", f"{part} +X"]
        assert lv[f"{part} +Z"] == max(lv[f] for f in faces), ("2 the top must be the brightest", part, lv)

    # ---- 3. the block keeps its blue on every face seen
    want = chroma(BLUE)
    for f in ("block +Z", "block -Y", "block +X"):
        got = chroma([lin(v) for v in seen[f]])
        miss = max(abs(a - b) for a, b in zip(got, want))
        assert miss <= 0.025, ("3 the blue turned or washed", f, seen[f], [round(g, 3) for g in got], [round(w, 3) for w in want])
    print("3 colour kept", {f: seen[f] for f in ("block +Z", "block -Y", "block +X")})
print("LIGHTING E2E OK")
