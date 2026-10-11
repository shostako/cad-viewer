"""Draw the app's icon (cad-viewer.ico, next to this file): a cube in the app's
blue (style.css --cv-accent) on its dark surface. Run before PyInstaller."""
from pathlib import Path

from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((8, 8, S - 8, S - 8), radius=44, fill=(21, 25, 31, 255))  # --cv-surface-solid
top, ur, lr, bottom, ll, ul, c = (128, 42), (210, 89), (210, 183), (128, 230), (46, 183), (46, 89), (128, 136)
d.polygon([top, ur, c, ul], fill=(106, 172, 255))  # --cv-accent-hover
d.polygon([ul, c, bottom, ll], fill=(76, 154, 255))  # --cv-accent
d.polygon([c, ur, lr, bottom], fill=(47, 104, 186))
for a, b in ((top, ur), (ur, lr), (lr, bottom), (bottom, ll), (ll, ul), (ul, top), (c, ur), (c, ul), (c, bottom)):
    d.line((a, b), fill=(230, 235, 241), width=5)  # --cv-text
out = Path(__file__).with_name("cad-viewer.ico")
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(out)
