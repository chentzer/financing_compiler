"""Draw the app icon (same as public/icon.svg) as PNGs for the installable
website and the Android launcher. Run once after changing the icon:

    ../.venv/Scripts/python scripts/make-icons.py      (needs Pillow)
"""

from pathlib import Path

from PIL import Image, ImageDraw

WEB = Path(__file__).resolve().parents[1]
TEAL, WHITE, AMBER = (15, 118, 110, 255), (255, 255, 255, 255), (251, 191, 36, 255)
SS = 4  # supersampling


def draw(size: int, *, background: str, glyph_box: float) -> Image.Image:
    """background: "rounded" (the SVG), "square" (full bleed) or "none".
    glyph_box: share of the image the SVG's 64x64 box takes, centred."""
    n = size * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if background == "rounded":
        d.rounded_rectangle([0, 0, n - 1, n - 1], radius=n * 14 / 64, fill=TEAL)
    elif background == "square":
        d.rectangle([0, 0, n, n], fill=TEAL)
    u = n * glyph_box / 64
    o = (n - 64 * u) / 2
    p = lambda x, y: (o + x * u, o + y * u)  # noqa: E731
    w = round(6 * u)
    for a, b in ((p(18, 44), p(18, 20)), (p(18, 20), p(40, 20)), (p(18, 32), p(34, 32))):
        d.line([a, b], fill=WHITE, width=w)
    for x, y in ((18, 44), (18, 20), (40, 20), (18, 32), (34, 32)):
        cx, cy = p(x, y)
        d.ellipse([cx - w / 2, cy - w / 2, cx + w / 2, cy + w / 2], fill=WHITE)
    cx, cy = p(46, 42)
    d.ellipse([cx - 6 * u, cy - 6 * u, cx + 6 * u, cy + 6 * u], fill=AMBER)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    pub = WEB / "public"
    draw(192, background="rounded", glyph_box=1).save(pub / "icon-192.png")
    draw(512, background="rounded", glyph_box=1).save(pub / "icon-512.png")
    draw(512, background="square", glyph_box=0.8).save(pub / "icon-maskable-512.png")
    draw(180, background="square", glyph_box=0.9).save(pub / "apple-touch-icon.png")

    res = WEB / "android" / "app" / "src" / "main" / "res"
    for dpi, launcher in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
        folder = res / f"mipmap-{dpi}"
        draw(launcher, background="rounded", glyph_box=1).save(folder / "ic_launcher.png")
        round_icon = draw(launcher, background="square", glyph_box=0.85)
        mask = Image.new("L", round_icon.size, 0)
        ImageDraw.Draw(mask).ellipse([0, 0, launcher - 1, launcher - 1], fill=255)
        round_icon.putalpha(mask)
        round_icon.save(folder / "ic_launcher_round.png")
        # Adaptive icon foreground: 108dp canvas, glyph inside the 66dp safe zone.
        fg = launcher * 108 // 48
        draw(fg, background="none", glyph_box=72 / 108).save(folder / "ic_launcher_foreground.png")


if __name__ == "__main__":
    main()
