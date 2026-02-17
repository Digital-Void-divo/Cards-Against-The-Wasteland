"""
card_renderer.py — Generates Cards Against Humanity card images.

Produces images for three game phases:
  1. Round start:  Black card only on a dark table
  2. Judging:      Black card + numbered white answer cards
  3. Winner:       Black card with winning answers filled in
"""

from PIL import Image, ImageDraw, ImageFont
import textwrap, io, os
from pathlib import Path

# ── Font Setup ───────────────────────────────────────────────────────────────

_FONT_PATHS_BOLD = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
_FONT_PATHS_REG = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

def _find_font(paths: list[str]) -> str:
    for p in paths:
        if os.path.exists(p):
            return p
    return paths[-1]

FONT_BOLD_PATH = _find_font(_FONT_PATHS_BOLD)
FONT_REG_PATH  = _find_font(_FONT_PATHS_REG)


# ── Design Constants ─────────────────────────────────────────────────────────

# Card dimensions (3x original)
CARD_W = 840
CARD_H = 1170
CORNER_R = 48
CARD_PAD = 72
TEXT_AREA_W = CARD_W - (CARD_PAD * 2)

# Colors
BG_COLOR       = (30, 30, 30)
BLACK_CARD_BG  = (0, 0, 0)
BLACK_CARD_FG  = (255, 255, 255)
WHITE_CARD_BG  = (255, 255, 255)
WHITE_CARD_FG  = (15, 15, 15)
BLANK_COLOR    = (255, 255, 255)
FILLED_COLOR   = (255, 210, 60)
SHADOW_COLOR   = (0, 0, 0, 80)
NUMBER_BG      = (60, 60, 60)
NUMBER_FG      = (255, 255, 255)
LOGO_BLACK     = (255, 255, 255, 140)
LOGO_WHITE     = (0, 0, 0, 100)

# Spacing (3x original)
CARD_GAP   = 54
CANVAS_PAD = 84

# Font sizes
CARD_FONT_SIZE       = 66   # 3x original 22
CARD_FONT_SIZE_SMALL = 54   # 3x original 18
LOGO_FONT_SIZE       = 18   # 2x original 9
PACK_FONT_SIZE       = 18   # 2x original 9 — separate line for pack name
NUMBER_FONT_SIZE     = 48   # 3x original 16

LOGO_TEXT = "Cards Against the Wasteland"


# ── Font Loading ─────────────────────────────────────────────────────────────

def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except (OSError, IOError):
        return ImageFont.load_default()

def _get_card_font(text: str, bold: bool = True) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD_PATH if bold else FONT_REG_PATH
    size = CARD_FONT_SIZE_SMALL if len(text) > 100 else CARD_FONT_SIZE
    return _load_font(path, size)


# ── Text Wrapping ────────────────────────────────────────────────────────────

def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test = f"{current_line} {word}".strip()
        bbox = font.getbbox(test)
        w = bbox[2] - bbox[0]
        if w <= max_width:
            current_line = test
        else:
            if current_line:
                lines.append(current_line)
            bbox_word = font.getbbox(word)
            if (bbox_word[2] - bbox_word[0]) > max_width:
                partial = ""
                for ch in word:
                    test_ch = partial + ch
                    bw = font.getbbox(test_ch)
                    if (bw[2] - bw[0]) > max_width and partial:
                        lines.append(partial)
                        partial = ch
                    else:
                        partial = test_ch
                current_line = partial
            else:
                current_line = word

    if current_line:
        lines.append(current_line)

    return lines if lines else [""]


def _text_block_height(lines: list[str], font: ImageFont.FreeTypeFont, spacing: int = 4) -> int:
    if not lines:
        return 0
    line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]
    return len(lines) * line_h + (len(lines) - 1) * spacing


# ── Drawing Primitives ───────────────────────────────────────────────────────

def _rounded_rect(draw: ImageDraw.Draw, xy: tuple, radius: int, fill):
    draw.rounded_rectangle(xy, radius=radius, fill=fill)


def _draw_shadow(img: Image.Image, x: int, y: int, w: int, h: int, offset: int = 4):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(overlay)
    shadow_draw.rounded_rectangle(
        (x + offset, y + offset, x + w + offset, y + h + offset),
        radius=CORNER_R, fill=SHADOW_COLOR)
    img.paste(Image.alpha_composite(
        img.convert("RGBA"),
        overlay
    ).convert("RGB"), (0, 0))
    return img


def _draw_card(img: Image.Image, x: int, y: int, is_black: bool,
               text: str, number: int = None, bold: bool = True,
               pack_name: str = None):
    """Draw a single card at position (x, y) on the image."""
    draw = ImageDraw.Draw(img)

    bg = BLACK_CARD_BG if is_black else WHITE_CARD_BG
    fg = BLACK_CARD_FG if is_black else WHITE_CARD_FG
    logo_col = LOGO_BLACK[:3] if is_black else LOGO_WHITE[:3]

    _draw_shadow(img, x, y, CARD_W, CARD_H)
    draw = ImageDraw.Draw(img)

    _rounded_rect(draw, (x, y, x + CARD_W, y + CARD_H), CORNER_R, fill=bg)

    # Card text
    font = _get_card_font(text, bold=bold)
    lines = _wrap_text(text, font, TEXT_AREA_W)
    line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]
    spacing = 10

    # Reserve space for two-line footer: logo line + pack line
    footer_reserved = CARD_PAD + LOGO_FONT_SIZE + 8 + PACK_FONT_SIZE

    ty = y + CARD_PAD
    for line in lines:
        if ty + line_h > y + CARD_H - footer_reserved:
            draw.text((x + CARD_PAD, ty), "...", fill=fg, font=font)
            break
        draw.text((x + CARD_PAD, ty), line, fill=fg, font=font)
        ty += line_h + spacing

    # Footer — two lines
    logo_font = _load_font(FONT_REG_PATH, LOGO_FONT_SIZE)
    pack_font = _load_font(FONT_REG_PATH, PACK_FONT_SIZE)

    # Line 1: game logo
    logo_y = y + CARD_H - CARD_PAD - LOGO_FONT_SIZE - 8 - PACK_FONT_SIZE
    draw.text((x + CARD_PAD, logo_y), LOGO_TEXT, fill=logo_col, font=logo_font)

    # Line 2: this card's pack name
    if pack_name:
        pack_y = y + CARD_H - CARD_PAD - PACK_FONT_SIZE
        pack_line = pack_name
        while (pack_font.getbbox(pack_line)[2] - pack_font.getbbox(pack_line)[0] > TEXT_AREA_W
               and len(pack_line) > 5):
            pack_line = pack_line[:-2] + "…"
        draw.text((x + CARD_PAD, pack_y), pack_line, fill=logo_col, font=pack_font)

    # Number badge
    if number is not None:
        num_font = _load_font(FONT_BOLD_PATH, NUMBER_FONT_SIZE)
        num_text = str(number)
        num_bbox = num_font.getbbox(num_text)
        num_w = num_bbox[2] - num_bbox[0] + 24
        num_h = num_bbox[3] - num_bbox[1] + 16
        nr_x = x + CARD_W - num_w - 14
        nr_y = y + 14
        draw.rounded_rectangle(
            (nr_x, nr_y, nr_x + num_w, nr_y + num_h),
            radius=num_h // 2,
            fill=NUMBER_BG if not is_black else (80, 80, 80))
        draw.text((nr_x + 12, nr_y + 8), num_text, fill=NUMBER_FG, font=num_font)


def _draw_black_card_filled(img: Image.Image, x: int, y: int,
                            card_text: str, answers: list[str],
                            pack_name: str = None):
    """Draw a black card with blanks filled in with gold answer text."""
    draw = ImageDraw.Draw(img)

    _draw_shadow(img, x, y, CARD_W, CARD_H)
    draw = ImageDraw.Draw(img)
    _rounded_rect(draw, (x, y, x + CARD_W, y + CARD_H), CORNER_R, fill=BLACK_CARD_BG)

    font = _get_card_font(card_text, bold=True)

    # Build full text with answers substituted
    full_text = card_text
    for ans in answers:
        full_text = full_text.replace("_", ans, 1)

    lines = _wrap_text(full_text, font, TEXT_AREA_W)
    line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]
    spacing = 10

    # Build character-level color map
    color_map = []
    temp = card_text
    answer_texts = list(answers)
    i = 0
    while i < len(temp):
        if temp[i] == "_" and answer_texts:
            ans = answer_texts.pop(0)
            for ch in ans:
                color_map.append((ch, True))
            i += 1
        else:
            color_map.append((temp[i], False))
            i += 1

    footer_reserved = CARD_PAD + LOGO_FONT_SIZE + 8 + PACK_FONT_SIZE

    char_idx = 0
    ty = y + CARD_PAD

    for line in lines:
        if ty + line_h > y + CARD_H - footer_reserved:
            draw.text((x + CARD_PAD, ty), "...", fill=BLACK_CARD_FG, font=font)
            break

        tx = x + CARD_PAD
        for ch in line:
            if char_idx < len(color_map):
                _, is_answer = color_map[char_idx]
                color = FILLED_COLOR if is_answer else BLACK_CARD_FG
                char_idx += 1
            else:
                color = BLACK_CARD_FG

            draw.text((tx, ty), ch, fill=color, font=font)
            char_w = font.getbbox(ch)[2] - font.getbbox(ch)[0]
            tx += char_w

        ty += line_h + spacing

        if char_idx < len(color_map) and line:
            if char_idx < len(color_map) and color_map[char_idx][0] == " ":
                char_idx += 1

    # Footer — two lines
    logo_font = _load_font(FONT_REG_PATH, LOGO_FONT_SIZE)
    pack_font = _load_font(FONT_REG_PATH, PACK_FONT_SIZE)

    logo_y = y + CARD_H - CARD_PAD - LOGO_FONT_SIZE - 8 - PACK_FONT_SIZE
    draw.text((x + CARD_PAD, logo_y), LOGO_TEXT, fill=LOGO_BLACK[:3], font=logo_font)

    if pack_name:
        pack_y = y + CARD_H - CARD_PAD - PACK_FONT_SIZE
        pack_line = pack_name
        while (pack_font.getbbox(pack_line)[2] - pack_font.getbbox(pack_line)[0] > TEXT_AREA_W
               and len(pack_line) > 5):
            pack_line = pack_line[:-2] + "…"
        draw.text((x + CARD_PAD, pack_y), pack_line, fill=LOGO_BLACK[:3], font=pack_font)


# ── Public API ───────────────────────────────────────────────────────────────

def render_black_card(card_text: str, pick: int = 1, pack_name: str = None) -> io.BytesIO:
    """
    Render just the black card (for round start).
    Returns a BytesIO PNG.
    """
    display_text = card_text.replace("_", "_____")
    if pick > 1:
        display_text += f"\n\nPICK {pick}"

    canvas_w = CARD_W + CANVAS_PAD * 2
    canvas_h = CARD_H + CANVAS_PAD * 2

    img = Image.new("RGB", (canvas_w, canvas_h), BG_COLOR)
    _draw_card(img, CANVAS_PAD, CANVAS_PAD, is_black=True, text=display_text,
               bold=True, pack_name=pack_name)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


def render_judging(card_text: str, pick: int,
                   submissions: list[list[str]],
                   numbers: bool = True,
                   black_pack: str = None,
                   white_packs: list[list[str]] = None) -> io.BytesIO:
    """
    Render black card + all white submission cards.
    black_pack: pack name for the black card.
    white_packs: list of [pack_name, ...] per submission, matching submissions structure.
    Returns a BytesIO PNG.
    """
    display_text = card_text.replace("_", "_____")
    if pick > 1:
        display_text += f"\n\nPICK {pick}"

    n_subs = len(submissions)
    cards_per_sub = max(len(s) for s in submissions) if submissions else 1
    sub_h = CARD_H if cards_per_sub == 1 else (CARD_H * cards_per_sub + CARD_GAP * (cards_per_sub - 1))
    total_card_h = max(CARD_H, sub_h)

    canvas_w = CANVAS_PAD + CARD_W + CARD_GAP * 2 + (CARD_W * n_subs + CARD_GAP * max(0, n_subs - 1)) + CANVAS_PAD
    canvas_h = CANVAS_PAD + total_card_h + CANVAS_PAD

    img = Image.new("RGB", (canvas_w, canvas_h), BG_COLOR)

    bc_y = CANVAS_PAD + (total_card_h - CARD_H) // 2
    _draw_card(img, CANVAS_PAD, bc_y, is_black=True, text=display_text,
               bold=True, pack_name=black_pack)

    wx = CANVAS_PAD + CARD_W + CARD_GAP * 2
    for i, sub_cards in enumerate(submissions):
        num = i + 1 if numbers else None
        for j, wcard_text in enumerate(sub_cards):
            wy = CANVAS_PAD + j * (CARD_H + CARD_GAP)
            wp = None
            if white_packs and i < len(white_packs) and j < len(white_packs[i]):
                wp = white_packs[i][j]
            _draw_card(img, wx, wy, is_black=False, text=wcard_text,
                      number=num if j == 0 else None, bold=False,
                      pack_name=wp)
        wx += CARD_W + CARD_GAP

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


def render_winner(card_text: str, answers: list[str], pack_name: str = None) -> io.BytesIO:
    """
    Render the black card with answers filled in (gold text).
    Returns a BytesIO PNG.
    """
    canvas_w = CARD_W + CANVAS_PAD * 2
    canvas_h = CARD_H + CANVAS_PAD * 2

    img = Image.new("RGB", (canvas_w, canvas_h), BG_COLOR)
    _draw_black_card_filled(img, CANVAS_PAD, CANVAS_PAD, card_text, answers,
                            pack_name=pack_name)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


# ── Quick test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    PACK = "Standard Pack"

    buf1 = render_black_card(
        "In his newest and most difficult stunt, David Blaine must escape from _.",
        pick=1, pack_name=PACK
    )
    with open("/tmp/test_black.png", "wb") as f:
        f.write(buf1.read())
    print("✅ test_black.png")

    buf2 = render_judging(
        "In his newest and most difficult stunt, David Blaine must escape from _.",
        pick=1,
        submissions=[
            ["My inner demons."],
            ["A 55-gallon drum of lube."],
            ["The entire Mormon Tabernacle Choir."],
        ],
        black_pack=PACK,
        white_packs=[["Geek Pack"], ["Base Set"], ["Absurdist Pack"]]
    )
    with open("/tmp/test_judging.png", "wb") as f:
        f.write(buf2.read())
    print("✅ test_judging.png")

    buf3 = render_winner(
        "In his newest and most difficult stunt, David Blaine must escape from _.",
        ["my inner demons"],
        pack_name=PACK
    )
    with open("/tmp/test_winner.png", "wb") as f:
        f.write(buf3.read())
    print("✅ test_winner.png")

    buf4 = render_judging(
        "Step 1: _. Step 2: _. Step 3: Profit.",
        pick=2,
        submissions=[
            ["Getting really high.", "Puppies!"],
            ["Racism.", "A balanced breakfast."],
        ],
        black_pack="Base Set",
        white_packs=[["Base Set", "Geek Pack"], ["Base Set", "Base Set"]]
    )
    with open("/tmp/test_pick2.png", "wb") as f:
        f.write(buf4.read())
    print("✅ test_pick2.png")

    buf5 = render_winner(
        "Step 1: _. Step 2: _. Step 3: Profit.",
        ["Getting really high", "Puppies"],
        pack_name="Geek Pack"
    )
    with open("/tmp/test_winner2.png", "wb") as f:
        f.write(buf5.read())
    print("✅ test_winner2.png")
