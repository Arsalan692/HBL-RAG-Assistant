"""Regenerate the app icons from the official HBL lockup.

Splits hbl-lockup-source.png into the chevron mark and the full lockup, then
writes every icon size the frontend needs into frontend/public/.

    python brand/make_icons.py

Only needs re-running if the source artwork changes, or if a higher-resolution
lockup becomes available — the current source is 794x157 after trimming, which
means the 512px PWA icon is upscaled.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "brand" / "hbl-lockup-source.png"
OUT = ROOT / "frontend" / "public"
OUT.mkdir(parents=True, exist_ok=True)

im = Image.open(SRC).convert("RGBA")
im = im.crop(im.getbbox())  # trim the transparent border
w, h = im.size
print(f"trimmed lockup: {w}x{h}")

# Column-wise opacity profile, used to find the gap between the chevron mark
# and the HBL wordmark.
alpha = im.getchannel("A")
cols = [sum(alpha.crop((x, 0, x + 1, h)).getdata()) for x in range(w)]

runs, start = [], None
for x, v in enumerate(cols):
    if v == 0 and start is None:
        start = x
    elif v != 0 and start is not None:
        runs.append((start, x))
        start = None
gaps = [(a, b) for a, b in runs if b - a > w * 0.02]
split = gaps[0][0] + (gaps[0][1] - gaps[0][0]) // 2 if gaps else w // 3
print(f"gaps {gaps} -> split at x={split}")

mark = im.crop((0, 0, split, h))
mark = mark.crop(mark.getbbox())
print(f"mark: {mark.size}   lockup: {im.size}")


def square(img, size, pad=0.0, bg=None):
    """Fit img inside a square canvas, scaling up or down as needed.

    `Image.thumbnail` only ever shrinks, which silently leaves a small source
    undersized on a large canvas. This scales in both directions.
    """
    inner = max(1, round(size * (1 - 2 * pad)))
    scale = min(inner / img.width, inner / img.height)
    scaled = img.resize(
        (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
        Image.LANCZOS,
    )
    canvas = Image.new("RGBA", (size, size), bg or (0, 0, 0, 0))
    canvas.paste(scaled, ((size - scaled.width) // 2, (size - scaled.height) // 2), scaled)
    return canvas


# --- App assets: trimmed, no baked-in padding, so CSS controls the spacing ---
# HblMark / HblLogo in the frontend hard-code these aspect ratios; if the source
# artwork ever changes proportions, update src/components/common/HblMark.tsx.
mark.save(OUT / "hbl-mark.png")

lockup = im.copy()
lockup.thumbnail((720, 720), Image.LANCZOS)
lockup.save(OUT / "hbl-logo.png")

# --- Browser tabs: transparent, tight fit so the chevron survives 16px ---
square(mark, 16).save(OUT / "favicon-16.png")
square(mark, 32).save(OUT / "favicon-32.png")
square(mark, 256).save(
    OUT / "favicon.ico",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)

# --- Home screen / installed app: iOS composites transparency onto black, so
#     these get an explicit white tile with the mark inset. ---
WHITE = (255, 255, 255, 255)
square(mark, 180, pad=0.16, bg=WHITE).save(OUT / "apple-touch-icon.png")
square(mark, 192, pad=0.16, bg=WHITE).save(OUT / "icon-192.png")
square(mark, 512, pad=0.16, bg=WHITE).save(OUT / "icon-512.png")

for f in sorted(OUT.glob("*.png")) + sorted(OUT.glob("*.ico")):
    with Image.open(f) as probe:
        dims = f"{probe.width}x{probe.height}"
    print(f"  {f.name:<24} {dims:>9}  {f.stat().st_size:>7,} bytes")
