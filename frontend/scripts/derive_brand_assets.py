"""Derive the web brand assets in public/brand/ from the 1024x1024 source logo.

Usage:  python frontend/scripts/derive_brand_assets.py /path/to/logo.png
Needs Pillow and numpy, optionally imagequant (not part of the app). Re-running overwrites the outputs.

Background removal: only the white area connected to the image border is removed
(flood fill), so the near-white document page inside the "D" stays opaque. Edge pixels
get an alpha from their distance to white and are un-premultiplied against white, which
avoids a white halo on dark backgrounds.
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parent.parent / "public" / "brand"
APP_DIR = Path(__file__).resolve().parent.parent / "src" / "app"
DARK_BG = (11, 16, 32)  # #0B1020, the dark theme background
LIGHT_TEXT = (230, 236, 248)
FONT = "/usr/share/fonts/truetype/sand-box/google/Inter/Inter-VariableFont_opsz,wght.ttf"


# The white document page inside the "D" touches the background through a hairline gap,
# so its area (measured on a 1024 px preview) is excluded from the flood fill.
PAGE_BOX = (108, 362, 350, 662)


def remove_background(img: Image.Image) -> Image.Image:
    rgb = np.asarray(img.convert("RGB")).astype(np.float32)
    dist = 255.0 - rgb.min(axis=2)  # 0 = pure white
    mask = np.where(dist <= 26, 255, 0).astype(np.uint8)
    k = img.width / 1024
    left, top, right, bottom = (round(v * k) for v in PAGE_BOX)
    mask[top:bottom, left:right] = 0
    candidate = Image.fromarray(mask).copy()
    w, h = candidate.size
    for x, y in [(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)] + [
        (0, y) for y in range(h)
    ] + [(w - 1, y) for y in range(h)]:
        if candidate.getpixel((x, y)) == 255:
            ImageDraw.floodfill(candidate, (x, y), 128)
    bg = np.asarray(candidate) == 128
    # Band of pixels next to the background: the anti-aliased edge.
    band_img = Image.fromarray((bg * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(7))
    band = (np.asarray(band_img) > 0) & ~bg
    alpha = np.ones(dist.shape, dtype=np.float32)
    soft = bg | band
    alpha[soft] = np.clip((dist[soft] - 4.0) / 70.0, 0.0, 1.0)
    # Un-premultiply against white: c = a*fg + (1-a)*255  =>  fg = (c - (1-a)*255) / a
    a = np.maximum(alpha, 1e-3)[..., None]
    fg = np.clip((rgb - (1.0 - a) * 255.0) / a, 0, 255)
    out = np.dstack([fg, alpha * 255.0]).round().astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def crop_to_content(img: Image.Image, pad: int = 8) -> Image.Image:
    alpha = np.asarray(img.getchannel("A"))
    ys, xs = np.nonzero(alpha > 8)
    box = (
        max(0, xs.min() - pad),
        max(0, ys.min() - pad),
        min(img.width, xs.max() + pad + 1),
        min(img.height, ys.max() + pad + 1),
    )
    return img.crop(box)


def lighten_dark_text(img: Image.Image, from_row: float = 0.8) -> Image.Image:
    """Recolour the navy part of the wordmark for dark backgrounds (keeps the gradient).

    Only rows below ``from_row`` (the wordmark under the mark) are touched.
    """
    arr = np.asarray(img).astype(np.float32)
    rgb = arr[..., :3]
    lum = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    spread = rgb.max(axis=2) - rgb.min(axis=2)
    rows = np.arange(arr.shape[0])[:, None] >= int(arr.shape[0] * from_row)
    navy = (lum < 120) & (spread < 110) & rows
    out = arr.copy()
    out[navy, 0], out[navy, 1], out[navy, 2] = LIGHT_TEXT
    return Image.fromarray(out.round().astype(np.uint8), "RGBA")


def fit(img: Image.Image, width: int) -> Image.Image:
    height = round(img.height * width / img.width)
    return img.resize((width, height), Image.Resampling.LANCZOS)


def save_png(img: Image.Image, path: Path) -> None:
    """Palette PNG with full alpha via libimagequant (pip package ``imagequant``).

    Pillow's own quantizers merge opaque white with the transparent background, which
    would punch holes into the white document page; without imagequant a lossless RGBA
    PNG is written instead (larger).
    """
    try:
        import imagequant  # noqa: PLC0415  (optional, only for smaller PNGs)
    except ImportError:
        img.save(path, optimize=True)
        return
    imagequant.quantize_pil_image(
        img.convert("RGBA"), dithering_level=0.8, max_colors=256, min_quality=70, max_quality=95
    ).save(path, optimize=True)


def save_pair(img: Image.Image, name: str) -> None:
    save_png(img, OUT / f"{name}.png")
    img.save(OUT / f"{name}.webp", quality=90, method=6)


def square_icon(glyph: Image.Image, size: int, background: tuple[int, int, int] | None,
                padding: float) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (*background, 255) if background else (0, 0, 0, 0))
    inner = round(size * (1 - 2 * padding))
    scale = min(inner / glyph.width, inner / glyph.height)
    resized = glyph.resize(
        (max(1, round(glyph.width * scale)), max(1, round(glyph.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas.alpha_composite(resized, ((size - resized.width) // 2, (size - resized.height) // 2))
    return canvas


def og_image(logo_dark: Image.Image) -> Image.Image:
    w, h = 1200, 630
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    base = np.zeros((h, w, 3), dtype=np.float32) + np.array(DARK_BG, dtype=np.float32)
    for cx, cy, color, radius in [(250, 80, (30, 107, 240), 520), (1000, 560, (124, 58, 237), 560)]:
        glow = np.clip(1 - np.hypot(xx - cx, yy - cy) / radius, 0, 1) ** 2 * 0.35
        base += glow[..., None] * (np.array(color, dtype=np.float32) - base)
    img = Image.fromarray(base.round().astype(np.uint8), "RGB").convert("RGBA")
    logo = fit(logo_dark, 640)
    img.alpha_composite(logo, ((w - logo.width) // 2, 90))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 34)
    font.set_variation_by_axes([14, 500]) if hasattr(font, "set_variation_by_axes") else None
    text = "Upload documents. Search them. Ask questions with cited answers."
    tw = draw.textlength(text, font=font)
    draw.text(((w - tw) / 2, 90 + logo.height + 40), text, font=font, fill=(203, 213, 225))
    return img.convert("RGB")


def main(source: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    full = remove_background(Image.open(source))
    k = full.width / 1024  # boxes below are measured on a 1024 px preview

    def box(left: int, top: int, right: int, bottom: int) -> tuple[int, int, int, int]:
        return (round(left * k), round(top * k), round(right * k), round(bottom * k))

    mark = crop_to_content(full.crop(box(60, 200, 980, 690)))
    glyph = crop_to_content(full.crop(box(60, 280, 450, 690)))  # the "D" with the document
    logo = crop_to_content(full.crop(box(40, 200, 990, 790)))

    save_pair(fit(mark, 480), "mark")
    save_pair(fit(logo, 720), "logo-light")
    save_pair(fit(lighten_dark_text(logo), 720), "logo-dark")

    icons = {size: square_icon(glyph, size, None, 0.04) for size in (16, 32, 48)}
    icons[48].save(APP_DIR / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)],
                   append_images=[icons[16], icons[32]])
    square_icon(mark, 180, DARK_BG, 0.14).convert("RGB").save(OUT / "apple-touch-icon.png",
                                                               optimize=True)
    for size in (192, 512):
        save_png(square_icon(mark, size, DARK_BG, 0.14), OUT / f"icon-{size}.png")
    save_png(og_image(lighten_dark_text(logo)).convert("RGBA"), OUT / "og-image.png")
    for path in sorted(OUT.iterdir()):
        print(f"{path.name:32} {path.stat().st_size / 1024:7.1f} KB")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
