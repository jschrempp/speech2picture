"""Image post-processing: combine, caption, error-image generation."""

from __future__ import annotations

import base64
import logging
import textwrap
import urllib.request

from PIL import Image, ImageDraw, ImageFont

from src.config import gw

logger = logging.getLogger(__name__)
logToFile = logging.getLogger("s2plog")

# Cache the font so we don't search the filesystem every call.
_font_cache: ImageFont.FreeTypeFont | None = None


def _get_font(size: int = 56) -> ImageFont.FreeTypeFont:
    """Return a truetype Arial font, cached."""
    global _font_cache
    if _font_cache is None:
        _font_cache = ImageFont.truetype("arial.ttf", size)
    return _font_cache


# ---------------------------------------------------------------------------
# Combine images
# ---------------------------------------------------------------------------

def combine_images(
    image_urls: list[str],
    image_modifiers: str,
    keywords: str,
    timestr: str,
    file_prefix: str,
) -> str:
    """Download/decode images, combine into a grid, caption, and save.

    Returns the path to the saved composite image.
    """
    img_objects: list[Image.Image] = []

    for num_url, url_data in enumerate(image_urls):
        file_name: str = f"history/image{num_url}.png"

        if url_data.startswith("http"):
            urllib.request.urlretrieve(url_data, file_name)
        else:
            with open(file_name, "wb") as f:
                f.write(base64.b64decode(url_data))

        img_objects.append(Image.open(file_name))

    caption_area_height: int = 140

    if not gw.single_image:
        img_w, img_h = img_objects[0].size
        total_width: int = img_w * 2
        max_height: int = img_h * 2 + caption_area_height
        new_im = Image.new("RGB", (total_width, max_height))
        locations: list[tuple[int, int]] = [
            (0, 0), (img_w, 0), (0, img_h), (img_w, img_h),
        ]
        for count, loc in enumerate(locations):
            new_im.paste(img_objects[count], loc)
    else:
        total_width = 1024
        max_height = 1024 + caption_area_height
        new_im = Image.new("RGB", (total_width, max_height))
        new_im.paste(img_objects[0], (0, 0))

    # -- Caption ---------------------------------------------------------------
    draw = ImageDraw.Draw(new_im)
    draw.rectangle(
        ((0, new_im.height - caption_area_height),
         (new_im.width, new_im.height)),
        fill="black",
    )
    font: ImageFont.FreeTypeFont = _get_font(56)

    max_text_width: int = int(new_im.width * 0.75)
    lines: list[str]
    for char_width in range(60, 20, -5):
        lines = textwrap.wrap(keywords, width=char_width)
        all_fit: bool = True
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            if bbox[2] - bbox[0] > max_text_width:
                all_fit = False
                break
        if all_fit:
            break
    lines = lines[:2]

    for idx, line in enumerate(lines):
        y_pos: int = new_im.height - caption_area_height + 5 + idx * 60
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w: int = bbox[2] - bbox[0]
        x_pos: float = (new_im.width - text_w) / 2
        draw.text((x_pos, y_pos), line, (255, 255, 255), font=font)

    # -- Save ------------------------------------------------------------------
    new_file_name: str = (
        f"history/{file_prefix}{timestr}-image.png"
    )
    new_im.save(new_file_name)
    return new_file_name


# ---------------------------------------------------------------------------
# Error image
# ---------------------------------------------------------------------------

def generate_error_image(error: Exception, timestr: str) -> str:
    """Create an image displaying the exception text, return its path."""
    total_width: int = 512 * 2
    max_height: int = 512 * 2 + 50
    new_im = Image.new("RGB", (total_width, max_height))
    draw = ImageDraw.Draw(new_im)
    draw.rectangle(
        ((0, 0), (new_im.width, new_im.height)), fill="black",
    )

    caption: str = str(error)
    logToFile.error("Error: %s", caption)

    font: ImageFont.FreeTypeFont = ImageFont.truetype("arial.ttf", 24)
    lines: list[str] = textwrap.wrap(caption, width=60)
    y_text: float = new_im.height / 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w: int = bbox[2] - bbox[0]
        h: int = bbox[3] - bbox[1]
        draw.text(
            ((new_im.width - text_w) / 2, y_text), line, font=font,
        )
        y_text += h

    new_file_name: str = f"errors/{timestr}-imageERROR.png"
    new_im.save(new_file_name)
    return new_file_name