"""
card_renderer.py — Generates Cards Against Humanity card images.

Produces images for four game phases:
  1. Round start:  Black card only on a dark table
  2. Judging:      Black card + numbered white answer cards
  3. Winner:       Black card with winning answers filled in
  4. Hand view:    Player's white cards in a 5x2 grid (scaled down)
"""

from PIL import Image, ImageDraw, ImageFont
import textwrap, io, os
from pathlib import Path

# ── Font Setup ───────────────────────────────────────────────────────────────

def _find_font(bold: bool = False) -> str:
    """
    Search common system font locations for a usable sans-serif font.
    Checks Linux, macOS, and Windows paths. Returns the first found path,
    or None if nothing is found (PIL will use its tiny fallback bitmap font).

    If a file called font.otf or font.ttf exists in the same directory
    as this script, it will always be used first for both bold and regular.
    """
    _here = os.path.dirname(os.path.abspath(__file__))
    for local_name in ("font.otf", "font.ttf", "Font.otf", "Font.ttf"):
        local_path = os.path.join(_here, local_name)
        if os.path.exists(local_path):
            print(f"[card_renderer] Using local font: {local_path}")
            return local_path

    candidates_bold = [
        # Linux — Liberation (Helvetica-compatible)
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        # Linux — DejaVu
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        # Linux — Noto
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-ExtraBold.ttf",
        # Linux — Ubuntu font
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf",
        # macOS
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/SFNSDisplay-Bold.otf",
        # Windows
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
        "C:/Windows/Fonts/verdanab.ttf",
    ]
    candidates_reg = [
        # Linux — Liberation
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
        # Linux — DejaVu
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        # Linux — Noto
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        # Linux — Ubuntu
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-Regular.ttf",
        # macOS
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/SFNSDisplay.otf",
        # Windows
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/verdana.ttf",
    ]
    candidates = candidates_bold if bold else candidates_reg
    for p in candidates:
        if os.path.exists(p):
            return p

    # Last resort: walk common font directories looking for any .ttf
    search_dirs = [
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        os.path.expanduser("~/.fonts"),
        "/Library/Fonts",
        "C:/Windows/Fonts",
    ]
    for d in search_dirs:
        if os.path.isdir(d):
            for root, _, files in os.walk(d):
                for f in files:
                    if f.lower().endswith(".ttf") or f.lower().endswith(".otf"):
                        return os.path.join(root, f)

    return None   # will trigger load_default() in _load_font


FONT_BOLD_PATH = _find_font(bold=True)
FONT_REG_PATH  = _find_font(bold=False)

if FONT_BOLD_PATH:
    print(f"[card_renderer] Bold font:    {FONT_BOLD_PATH}")
else:
    print("[card_renderer] WARNING: No bold font found — text will be tiny! Install fonts-liberation or fonts-dejavu.")

if FONT_REG_PATH:
    print(f"[card_renderer] Regular font: {FONT_REG_PATH}")
else:
    print("[card_renderer] WARNING: No regular font found — text will be tiny!")


# ── Design Constants — Full Size (in-game cards) ─────────────────────────────

CARD_W = 840
CARD_H = 1170
CORNER_R = 48
CARD_PAD = 72
TEXT_AREA_W = CARD_W - (CARD_PAD * 2)

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

CARD_GAP   = 54
CANVAS_PAD = 84

CARD_FONT_SIZE       = 66
CARD_FONT_SIZE_SMALL = 54
LOGO_FONT_SIZE       = 18
PACK_FONT_SIZE       = 18
NUMBER_FONT_SIZE     = 48

LOGO_TEXT = "Cards Against the Wasteland"


# ── Design Constants — Hand Size (~35% scale) ─────────────────────────────────

HAND_CARD_W = 300
HAND_CARD_H = 500          # taller to accommodate larger text
HAND_CORNER_R = 16
HAND_CARD_PAD = 22
HAND_TEXT_AREA_W = HAND_CARD_W - (HAND_CARD_PAD * 2)

HAND_CARD_FONT_SIZE       = 38   # was 22 — much more readable
HAND_CARD_FONT_SIZE_SMALL = 30   # was 17 — for longer card texts
HAND_LOGO_FONT_SIZE       = 9
HAND_PACK_FONT_SIZE       = 9
HAND_NUMBER_FONT_SIZE     = 20

HAND_CARD_GAP   = 14
HAND_CANVAS_PAD = 20
HAND_COLS       = 5


# ── Font Loading ─────────────────────────────────────────────────────────────

def _load_font(path, size: int):
    if path and os.path.exists(path):
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()

def _get_card_font(text: str, bold: bool = True) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD_PATH if bold else FONT_REG_PATH
    size = CARD_FONT_SIZE_SMALL if len(text) > 100 else CARD_FONT_SIZE
    return _load_font(path, size)

def _get_hand_font(text: str, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD_PATH if bold else FONT_REG_PATH
    size = HAND_CARD_FONT_SIZE_SMALL if len(text) > 80 else HAND_CARD_FONT_SIZE
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


# ── Drawing Primitives ───────────────────────────────────────────────────────

def _rounded_rect(draw: ImageDraw.Draw, xy: tuple, radius: int, fill):
    draw.rounded_rectangle(xy, radius=radius, fill=fill)


def _draw_shadow(img: Image.Image, x: int, y: int, w: int, h: int,
                 corner_r: int = None, offset: int = 4):
    if corner_r is None:
        corner_r = CORNER_R
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(overlay)
    shadow_draw.rounded_rectangle(
        (x + offset, y + offset, x + w + offset, y + h + offset),
        radius=corner_r, fill=SHADOW_COLOR)
    img.paste(Image.alpha_composite(
        img.convert("RGBA"), overlay
    ).convert("RGB"), (0, 0))
    return img


def _draw_card(img: Image.Image, x: int, y: int, is_black: bool,
               text: str, number: int = None, bold: bool = True,
               pack_name: str = None):
    """Draw a full-size card at position (x, y)."""
    draw = ImageDraw.Draw(img)

    bg = BLACK_CARD_BG if is_black else WHITE_CARD_BG
    fg = BLACK_CARD_FG if is_black else WHITE_CARD_FG
    logo_col = LOGO_BLACK[:3] if is_black else LOGO_WHITE[:3]

    _draw_shadow(img, x, y, CARD_W, CARD_H, corner_r=CORNER_R)
    draw = ImageDraw.Draw(img)
    _rounded_rect(draw, (x, y, x + CARD_W, y + CARD_H), CORNER_R, fill=bg)

    font = _get_card_font(text, bold=bold)
    lines = _wrap_text(text, font, TEXT_AREA_W)
    line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]
    spacing = 10

    footer_reserved = CARD_PAD + LOGO_FONT_SIZE + 8 + PACK_FONT_SIZE

    ty = y + CARD_PAD
    for line in lines:
        if ty + line_h > y + CARD_H - footer_reserved:
            draw.text((x + CARD_PAD, ty), "...", fill=fg, font=font)
            break
        draw.text((x + CARD_PAD, ty), line, fill=fg, font=font)
        ty += line_h + spacing

    logo_font = _load_font(FONT_REG_PATH, LOGO_FONT_SIZE)
    pack_font = _load_font(FONT_REG_PATH, PACK_FONT_SIZE)

    logo_y = y + CARD_H - CARD_PAD - LOGO_FONT_SIZE - 8 - PACK_FONT_SIZE
    draw.text((x + CARD_PAD, logo_y), LOGO_TEXT, fill=logo_col, font=logo_font)

    if pack_name:
        pack_y = y + CARD_H - CARD_PAD - PACK_FONT_SIZE
        pack_line = pack_name
        while (pack_font.getbbox(pack_line)[2] - pack_font.getbbox(pack_line)[0] > TEXT_AREA_W
               and len(pack_line) > 5):
            pack_line = pack_line[:-2] + "…"
        draw.text((x + CARD_PAD, pack_y), pack_line, fill=logo_col, font=pack_font)

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


def _draw_hand_card(img: Image.Image, x: int, y: int,
                    text: str, number: int,
                    pack_name: str = None,
                    highlight: bool = False,
                    dimmed: bool = False):
    """Draw a scaled-down white card for the hand view."""
    draw = ImageDraw.Draw(img)

    # Gold border for pending/selected cards
    if highlight:
        _draw_shadow(img, x - 3, y - 3, HAND_CARD_W + 6, HAND_CARD_H + 6,
                     corner_r=HAND_CORNER_R + 2, offset=3)
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle(
            (x - 4, y - 4, x + HAND_CARD_W + 4, y + HAND_CARD_H + 4),
            radius=HAND_CORNER_R + 2, fill=FILLED_COLOR)
    else:
        _draw_shadow(img, x, y, HAND_CARD_W, HAND_CARD_H,
                     corner_r=HAND_CORNER_R, offset=3)
        draw = ImageDraw.Draw(img)

    _rounded_rect(draw, (x, y, x + HAND_CARD_W, y + HAND_CARD_H),
                  HAND_CORNER_R, fill=WHITE_CARD_BG)

    fg = WHITE_CARD_FG
    logo_col = LOGO_WHITE[:3]

    font = _get_hand_font(text)
    lines = _wrap_text(text, font, HAND_TEXT_AREA_W)
    line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]
    spacing = 4

    footer_reserved = HAND_CARD_PAD + HAND_LOGO_FONT_SIZE + 5 + HAND_PACK_FONT_SIZE

    ty = y + HAND_CARD_PAD
    for line in lines:
        if ty + line_h > y + HAND_CARD_H - footer_reserved:
            draw.text((x + HAND_CARD_PAD, ty), "...", fill=fg, font=font)
            break
        draw.text((x + HAND_CARD_PAD, ty), line, fill=fg, font=font)
        ty += line_h + spacing

    logo_font = _load_font(FONT_REG_PATH, HAND_LOGO_FONT_SIZE)
    pack_font = _load_font(FONT_REG_PATH, HAND_PACK_FONT_SIZE)

    logo_y = y + HAND_CARD_H - HAND_CARD_PAD - HAND_LOGO_FONT_SIZE - 5 - HAND_PACK_FONT_SIZE
    draw.text((x + HAND_CARD_PAD, logo_y), LOGO_TEXT, fill=logo_col, font=logo_font)

    if pack_name:
        pack_y = y + HAND_CARD_H - HAND_CARD_PAD - HAND_PACK_FONT_SIZE
        pack_line = pack_name
        while (pack_font.getbbox(pack_line)[2] - pack_font.getbbox(pack_line)[0] > HAND_TEXT_AREA_W
               and len(pack_line) > 5):
            pack_line = pack_line[:-2] + "…"
        draw.text((x + HAND_CARD_PAD, pack_y), pack_line, fill=logo_col, font=pack_font)

    # Number badge — top-left
    num_font = _load_font(FONT_BOLD_PATH, HAND_NUMBER_FONT_SIZE)
    num_text = str(number)
    num_bbox = num_font.getbbox(num_text)
    num_w = num_bbox[2] - num_bbox[0] + 10
    num_h = num_bbox[3] - num_bbox[1] + 8
    draw.rounded_rectangle(
        (x + 6, y + 6, x + 6 + num_w, y + 6 + num_h),
        radius=num_h // 2, fill=NUMBER_BG)
    draw.text((x + 11, y + 10), num_text, fill=NUMBER_FG, font=num_font)

    # Dim submitted cards with a dark overlay
    if dimmed:
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ov_draw = ImageDraw.Draw(overlay)
        ov_draw.rounded_rectangle(
            (x, y, x + HAND_CARD_W, y + HAND_CARD_H),
            radius=HAND_CORNER_R, fill=(0, 0, 0, 120))
        merged = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        img.paste(merged)


def _draw_black_card_filled(img: Image.Image, x: int, y: int,
                            card_text: str, answers: list[str],
                            pack_name: str = None):
    """Draw a black card with blanks filled in with gold answer text."""
    draw = ImageDraw.Draw(img)

    _draw_shadow(img, x, y, CARD_W, CARD_H, corner_r=CORNER_R)
    draw = ImageDraw.Draw(img)
    _rounded_rect(draw, (x, y, x + CARD_W, y + CARD_H), CORNER_R, fill=BLACK_CARD_BG)

    font = _get_card_font(card_text, bold=True)

    full_text = card_text
    for ans in answers:
        full_text = full_text.replace("_", ans, 1)

    lines = _wrap_text(full_text, font, TEXT_AREA_W)
    line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]
    spacing = 10

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
    """Render just the black card (for round start). Returns a BytesIO PNG."""
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
    white_packs: list of [pack_name, ...] per submission.
    Returns a BytesIO PNG.
    """
    display_text = card_text.replace("_", "_____")
    if pick > 1:
        display_text += f"\n\nPICK {pick}"

    n_subs = len(submissions)
    cards_per_sub = max(len(s) for s in submissions) if submissions else 1
    sub_h = CARD_H if cards_per_sub == 1 else (CARD_H * cards_per_sub + CARD_GAP * (cards_per_sub - 1))
    total_card_h = max(CARD_H, sub_h)

    canvas_w = (CANVAS_PAD + CARD_W + CARD_GAP * 2
                + CARD_W * n_subs + CARD_GAP * max(0, n_subs - 1)
                + CANVAS_PAD)
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
                       number=num if j == 0 else None, bold=False, pack_name=wp)
        wx += CARD_W + CARD_GAP

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


def render_winner(card_text: str, answers: list[str], pack_name: str = None) -> io.BytesIO:
    """Render the black card with answers filled in (gold text). Returns a BytesIO PNG."""
    canvas_w = CARD_W + CANVAS_PAD * 2
    canvas_h = CARD_H + CANVAS_PAD * 2

    img = Image.new("RGB", (canvas_w, canvas_h), BG_COLOR)
    _draw_black_card_filled(img, CANVAS_PAD, CANVAS_PAD, card_text, answers,
                            pack_name=pack_name)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


def render_hand(cards: list[str],
                white_packs: dict[str, str] = None,
                pending: list[str] = None,
                submitted: list[str] = None) -> io.BytesIO:
    """
    Render a player's hand as a 5-column grid of small white cards.

    cards:       List of card text strings (up to 10).
    white_packs: Dict mapping card text -> pack name.
    pending:     Cards selected but not yet finalized — shown with gold highlight.
    submitted:   Cards already submitted this round — shown dimmed.

    Returns a BytesIO PNG.
    """
    pending_set   = set(pending or [])
    submitted_set = set(submitted or [])
    white_packs   = white_packs or {}

    n    = len(cards)
    cols = min(n, HAND_COLS)
    rows = (n + HAND_COLS - 1) // HAND_COLS

    canvas_w = HAND_CANVAS_PAD * 2 + cols * HAND_CARD_W + (cols - 1) * HAND_CARD_GAP
    canvas_h = HAND_CANVAS_PAD * 2 + rows * HAND_CARD_H + (rows - 1) * HAND_CARD_GAP

    img = Image.new("RGB", (canvas_w, canvas_h), BG_COLOR)

    for idx, card_text in enumerate(cards):
        col = idx % HAND_COLS
        row = idx // HAND_COLS
        x = HAND_CANVAS_PAD + col * (HAND_CARD_W + HAND_CARD_GAP)
        y = HAND_CANVAS_PAD + row * (HAND_CARD_H + HAND_CARD_GAP)

        _draw_hand_card(
            img, x, y,
            text=card_text,
            number=idx + 1,
            pack_name=white_packs.get(card_text),
            highlight=card_text in pending_set,
            dimmed=card_text in submitted_set,
        )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


# ── Quick test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    PACK = "Standard Pack"

    buf1 = render_black_card(
        "In his newest and most difficult stunt, David Blaine must escape from _.",
        pick=1, pack_name=PACK)
    with open("/tmp/test_black.png", "wb") as f:
        f.write(buf1.read())
    print("✅ test_black.png")

    buf2 = render_judging(
        "In his newest and most difficult stunt, David Blaine must escape from _.",
        pick=1,
        submissions=[["My inner demons."], ["A 55-gallon drum of lube."], ["The entire Mormon Tabernacle Choir."]],
        black_pack=PACK,
        white_packs=[["Geek Pack"], ["Base Set"], ["Absurdist Pack"]])
    with open("/tmp/test_judging.png", "wb") as f:
        f.write(buf2.read())
    print("✅ test_judging.png")

    buf3 = render_winner(
        "In his newest and most difficult stunt, David Blaine must escape from _.",
        ["my inner demons"], pack_name=PACK)
    with open("/tmp/test_winner.png", "wb") as f:
        f.write(buf3.read())
    print("✅ test_winner.png")

    buf4 = render_judging(
        "Step 1: _. Step 2: _. Step 3: Profit.",
        pick=2,
        submissions=[["Getting really high.", "Puppies!"], ["Racism.", "A balanced breakfast."]],
        black_pack="Base Set",
        white_packs=[["Base Set", "Geek Pack"], ["Base Set", "Base Set"]])
    with open("/tmp/test_pick2.png", "wb") as f:
        f.write(buf4.read())
    print("✅ test_pick2.png")

    buf5 = render_winner(
        "Step 1: _. Step 2: _. Step 3: Profit.",
        ["Getting really high", "Puppies"], pack_name="Geek Pack")
    with open("/tmp/test_winner2.png", "wb") as f:
        f.write(buf5.read())
    print("✅ test_winner2.png")

    sample_hand = [
        "Coat hanger abortions.", "A tiny horse.", "Vehicular manslaughter.",
        "The clitoris.", "A bleached asshole.", "Crystal meth.",
        "Roofies.", "My inner demons.", "Puppies!", "Getting really high."
    ]
    sample_packs = {c: "Base Set" for c in sample_hand}
    buf6 = render_hand(
        sample_hand, white_packs=sample_packs,
        pending=["A tiny horse."], submitted=["Crystal meth."])
    with open("/tmp/test_hand.png", "wb") as f:
        f.write(buf6.read())
    print("✅ test_hand.png")
