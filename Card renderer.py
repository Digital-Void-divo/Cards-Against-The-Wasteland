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

# Prefer Liberation Sans (Helvetica-compatible), fall back to DejaVu Sans
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
    return paths[-1]  # fallback, let PIL error if truly missing

FONT_BOLD_PATH = _find_font(_FONT_PATHS_BOLD)
FONT_REG_PATH = _find_font(_FONT_PATHS_REG)


# ── Design Constants ─────────────────────────────────────────────────────────

# Card dimensions
CARD_W = 280
CARD_H = 390
CORNER_R = 16
CARD_PAD = 24        # inner padding
TEXT_AREA_W = CARD_W - (CARD_PAD * 2)

# Colors
BG_COLOR       = (30, 30, 30)         # dark table
BLACK_CARD_BG  = (0, 0, 0)
BLACK_CARD_FG  = (255, 255, 255)
WHITE_CARD_BG  = (255, 255, 255)
WHITE_CARD_FG  = (15, 15, 15)
BLANK_COLOR    = (255, 255, 255)      # underline color on black cards
FILLED_COLOR   = (255, 210, 60)       # gold for filled-in answers
SHADOW_COLOR   = (0, 0, 0, 80)
NUMBER_BG      = (60, 60, 60)
NUMBER_FG      = (255, 255, 255)
LOGO_BLACK     = (255, 255, 255, 140) # white logo text on black card
LOGO_WHITE     = (0, 0, 0, 100)       # black logo text on white card

# Spacing
CARD_GAP = 18
CANVAS_PAD = 28

# Font sizes
CARD_FONT_SIZE = 22
CARD_FONT_SIZE_SMALL = 18  # for longer text
LOGO_FONT_SIZE = 11
NUMBER_FONT_SIZE = 16
FILLED_FONT_SIZE = 22


# ── Font Loading ─────────────────────────────────────────────────────────────

def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except (OSError, IOError):
        return ImageFont.load_default()

def _get_card_font(text: str, bold: bool = True) -> ImageFont.FreeTypeFont:
    """Use a smaller font for long card text."""
    path = FONT_BOLD_PATH if bold else FONT_REG_PATH
    size = CARD_FONT_SIZE_SMALL if len(text) > 100 else CARD_FONT_SIZE
    return _load_font(path, size)


# ── Text Wrapping ────────────────────────────────────────────────────────────

def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
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
            # Check if single word is too long
            bbox_word = font.getbbox(word)
            if (bbox_word[2] - bbox_word[0]) > max_width:
                # Force-break long word
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
    """Calculate total height of wrapped text."""
    if not lines:
        return 0
    line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]
    return len(lines) * line_h + (len(lines) - 1) * spacing


# ── Drawing Primitives ───────────────────────────────────────────────────────

def _rounded_rect(draw: ImageDraw.Draw, xy: tuple, radius: int, fill):
    """Draw a rounded rectangle."""
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill)


def _draw_shadow(img: Image.Image, x: int, y: int, w: int, h: int, offset: int = 4):
    """Draw a subtle drop shadow behind a card."""
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
               text: str, number: int = None, bold: bool = True):
    """Draw a single card at position (x, y) on the image."""
    draw = ImageDraw.Draw(img)

    bg = BLACK_CARD_BG if is_black else WHITE_CARD_BG
    fg = BLACK_CARD_FG if is_black else WHITE_CARD_FG
    logo_col = LOGO_BLACK[:3] if is_black else LOGO_WHITE[:3]

    # Shadow
    _draw_shadow(img, x, y, CARD_W, CARD_H)
    draw = ImageDraw.Draw(img)  # refresh after composite

    # Card body
    _rounded_rect(draw, (x, y, x + CARD_W, y + CARD_H), CORNER_R, fill=bg)

    # Card text
    font = _get_card_font(text, bold=bold)
    lines = _wrap_text(text, font, TEXT_AREA_W)
    line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]
    spacing = 5

    ty = y + CARD_PAD
    for line in lines:
        # Don't overflow the card (leave room for logo)
        if ty + line_h > y + CARD_H - 50:
            # Draw ellipsis and stop
            draw.text((x + CARD_PAD, ty), "...", fill=fg, font=font)
            break
        draw.text((x + CARD_PAD, ty), line, fill=fg, font=font)
        ty += line_h + spacing

    # "Cards Against Humanity" logo at bottom
    logo_font = _load_font(FONT_BOLD_PATH, LOGO_FONT_SIZE)
    logo_text = "Cards Against Humanity"
    logo_bbox = logo_font.getbbox(logo_text)
    logo_w = logo_bbox[2] - logo_bbox[0]
    draw.text((x + CARD_PAD, y + CARD_H - 32), logo_text, fill=logo_col, font=logo_font)

    # Small card icon before the logo (simple rectangle representation)
    icon_x = x + CARD_PAD + logo_w + 6
    icon_y = y + CARD_H - 30
    # Just skip if it'd go off-card

    # Number badge (for submission numbering)
    if number is not None:
        num_font = _load_font(FONT_BOLD_PATH, NUMBER_FONT_SIZE)
        num_text = str(number)
        num_bbox = num_font.getbbox(num_text)
        num_w = num_bbox[2] - num_bbox[0] + 16
        num_h = num_bbox[3] - num_bbox[1] + 10

        # Circle/pill at top-right
        nr_x = x + CARD_W - num_w - 8
        nr_y = y + 8
        draw.rounded_rectangle(
            (nr_x, nr_y, nr_x + num_w, nr_y + num_h),
            radius=num_h // 2,
            fill=NUMBER_BG if not is_black else (80, 80, 80))
        draw.text((nr_x + 8, nr_y + 4), num_text, fill=NUMBER_FG, font=num_font)


def _draw_black_card_filled(img: Image.Image, x: int, y: int,
                            card_text: str, answers: list[str]):
    """Draw a black card with blanks filled in with gold answer text."""
    draw = ImageDraw.Draw(img)

    # Shadow + card body
    _draw_shadow(img, x, y, CARD_W, CARD_H)
    draw = ImageDraw.Draw(img)
    _rounded_rect(draw, (x, y, x + CARD_W, y + CARD_H), CORNER_R, fill=BLACK_CARD_BG)

    # Build the filled text — replace _ with answers
    font = _get_card_font(card_text, bold=True)
    parts = card_text.split("_")

    # Build a flat list of (text, is_answer) segments
    segments = []
    for i, part in enumerate(parts):
        if part:
            segments.append((part, False))
        if i < len(answers):
            segments.append((answers[i], True))

    # Now wrap and draw with mixed colors
    # Simple approach: construct full text, wrap it, then re-color answer portions
    full_text = card_text
    for ans in answers:
        full_text = full_text.replace("_", ans, 1)

    lines = _wrap_text(full_text, font, TEXT_AREA_W)
    line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]
    spacing = 5

    # For coloring, we need to track which characters are answer text
    # Build a color map
    color_map = []  # list of (char, is_answer) for the full text
    temp = card_text
    answer_texts = list(answers)
    i = 0
    while i < len(temp):
        if temp[i] == "_" and answer_texts:
            ans = answer_texts.pop(0)
            for ch in ans:
                color_map.append((ch, True))
            i += 1  # skip the _
        else:
            color_map.append((temp[i], False))
            i += 1

    # Now draw line by line with per-character coloring
    char_idx = 0
    ty = y + CARD_PAD

    for line in lines:
        if ty + line_h > y + CARD_H - 50:
            draw.text((x + CARD_PAD, ty), "...", fill=BLACK_CARD_FG, font=font)
            break

        # Draw character by character for mixed coloring
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

        # Account for spaces between lines in the character index
        if char_idx < len(color_map) and line:
            # Skip the space that was used as a line break
            if char_idx < len(color_map) and color_map[char_idx][0] == " ":
                char_idx += 1

    # Logo
    logo_font = _load_font(FONT_BOLD_PATH, LOGO_FONT_SIZE)
    draw.text((x + CARD_PAD, y + CARD_H - 32), "Cards Against Humanity",
              fill=LOGO_BLACK[:3], font=logo_font)


def _draw_blank_lines(img: Image.Image, draw: ImageDraw.Draw,
                      x: int, y: int, text: str, font: ImageFont.FreeTypeFont):
    """For black cards, draw visible underlines where _ appears."""
    # This is handled by replacing _ with _____ in the text before rendering
    pass


# ── Public API ───────────────────────────────────────────────────────────────

def render_black_card(card_text: str, pick: int = 1) -> io.BytesIO:
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
    _draw_card(img, CANVAS_PAD, CANVAS_PAD, is_black=True, text=display_text, bold=True)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


def render_judging(card_text: str, pick: int,
                   submissions: list[list[str]],
                   numbers: bool = True) -> io.BytesIO:
    """
    Render black card + all white submission cards.
    submissions: list of [card_text, ...] per player (pick-2 = 2 cards per entry).
    Returns a BytesIO PNG.
    """
    display_text = card_text.replace("_", "_____")
    if pick > 1:
        display_text += f"\n\nPICK {pick}"

    # Calculate layout
    # For pick-1: one white card per submission
    # For pick-2+: stack cards vertically per submission
    n_subs = len(submissions)

    # Each submission column width
    col_w = CARD_W

    # For pick-2, stack cards vertically in each column
    cards_per_sub = max(len(s) for s in submissions) if submissions else 1
    sub_h = CARD_H if cards_per_sub == 1 else (CARD_H * cards_per_sub + CARD_GAP * (cards_per_sub - 1))

    total_card_h = max(CARD_H, sub_h)

    canvas_w = CANVAS_PAD + CARD_W + CARD_GAP * 2 + (col_w * n_subs + CARD_GAP * max(0, n_subs - 1)) + CANVAS_PAD
    canvas_h = CANVAS_PAD + total_card_h + CANVAS_PAD

    # Cap width — if too many submissions, scale down is ok (Discord handles it)
    img = Image.new("RGB", (canvas_w, canvas_h), BG_COLOR)

    # Draw black card (centered vertically)
    bc_y = CANVAS_PAD + (total_card_h - CARD_H) // 2
    _draw_card(img, CANVAS_PAD, bc_y, is_black=True, text=display_text, bold=True)

    # Draw white submission cards
    wx = CANVAS_PAD + CARD_W + CARD_GAP * 2
    for i, sub_cards in enumerate(submissions):
        num = i + 1 if numbers else None
        for j, card_text in enumerate(sub_cards):
            wy = CANVAS_PAD + j * (CARD_H + CARD_GAP)
            _draw_card(img, wx, wy, is_black=False, text=card_text,
                      number=num if j == 0 else None, bold=False)
        wx += col_w + CARD_GAP

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


def render_winner(card_text: str, answers: list[str]) -> io.BytesIO:
    """
    Render the black card with answers filled in (gold text).
    Returns a BytesIO PNG.
    """
    canvas_w = CARD_W + CANVAS_PAD * 2
    canvas_h = CARD_H + CANVAS_PAD * 2

    img = Image.new("RGB", (canvas_w, canvas_h), BG_COLOR)
    _draw_black_card_filled(img, CANVAS_PAD, CANVAS_PAD, card_text, answers)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


# ── Quick test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Test 1: Black card alone
    buf1 = render_black_card(
        "In his newest and most difficult stunt, David Blaine must escape from _.",
        pick=1
    )
    with open("/tmp/test_black.png", "wb") as f:
        f.write(buf1.read())
    print("✅ test_black.png")

    # Test 2: Judging view
    buf2 = render_judging(
        "In his newest and most difficult stunt, David Blaine must escape from _.",
        pick=1,
        submissions=[
            ["My inner demons."],
            ["A 55-gallon drum of lube."],
            ["The entire Mormon Tabernacle Choir."],
        ]
    )
    with open("/tmp/test_judging.png", "wb") as f:
        f.write(buf2.read())
    print("✅ test_judging.png")

    # Test 3: Winner with filled text
    buf3 = render_winner(
        "In his newest and most difficult stunt, David Blaine must escape from _.",
        ["my inner demons"]
    )
    with open("/tmp/test_winner.png", "wb") as f:
        f.write(buf3.read())
    print("✅ test_winner.png")

    # Test 4: Pick 2
    buf4 = render_judging(
        "Step 1: _. Step 2: _. Step 3: Profit.",
        pick=2,
        submissions=[
            ["Getting really high.", "Puppies!"],
            ["Racism.", "A balanced breakfast."],
        ]
    )
    with open("/tmp/test_pick2.png", "wb") as f:
        f.write(buf4.read())
    print("✅ test_pick2.png")

    # Test 5: Pick 2 winner
    buf5 = render_winner(
        "Step 1: _. Step 2: _. Step 3: Profit.",
        ["Getting really high", "Puppies"]
    )
    with open("/tmp/test_winner2.png", "wb") as f:
        f.write(buf5.read())
    print("✅ test_winner2.png")
