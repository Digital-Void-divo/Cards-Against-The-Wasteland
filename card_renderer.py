"""
card_renderer.py — Generates Cards Against Humanity card images.

Produces images for four game phases:
  1. Round start:  Black card only on a dark table
  2. Judging:      Black card + numbered white answer cards
  3. Winner:       Black card with winning answers filled in
  4. Hand view:    Player's white cards in a 5x2 grid (scaled down)

Pack logos:
  Place a file named {pack_id}.png (e.g. base.png, geek.png) in the same
  directory as this script. It will be used as the footer logo on cards from
  that pack, scaled to fit the footer area automatically.
  Recommended source resolution: 400px tall at whatever width your logo needs.
  If no image is found, the pack name falls back to plain text.
"""

from PIL import Image, ImageDraw, ImageFont, ImageOps
import io, os

# ── Font Setup ───────────────────────────────────────────────────────────────

def _find_font(bold: bool = False) -> str:
    """
    Search common system font locations for a usable sans-serif font.
    If font.otf / font.ttf exists next to this script, it is always used first.
    """
    _here = os.path.dirname(os.path.abspath(__file__))
    for local_name in ("font.otf", "font.ttf", "Font.otf", "Font.ttf"):
        local_path = os.path.join(_here, local_name)
        if os.path.exists(local_path):
            print(f"[card_renderer] Using local font: {local_path}")
            return local_path

    candidates_bold = [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
    ]
    candidates_reg = [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
    ]
    for p in (candidates_bold if bold else candidates_reg):
        if os.path.exists(p):
            return p

    # Last resort: walk common font dirs
    for d in ["/usr/share/fonts", "/usr/local/share/fonts",
              os.path.expanduser("~/.fonts"), "/Library/Fonts",
              "C:/Windows/Fonts"]:
        if os.path.isdir(d):
            for root, _, files in os.walk(d):
                for f in files:
                    if f.lower().endswith((".ttf", ".otf")):
                        return os.path.join(root, f)
    return None


FONT_BOLD_PATH = _find_font(bold=True)
FONT_REG_PATH  = _find_font(bold=False)

if FONT_BOLD_PATH:
    print(f"[card_renderer] Bold font:    {FONT_BOLD_PATH}")
else:
    print("[card_renderer] WARNING: No bold font found — install fonts-liberation or fonts-dejavu.")
if FONT_REG_PATH:
    print(f"[card_renderer] Regular font: {FONT_REG_PATH}")
else:
    print("[card_renderer] WARNING: No regular font found.")


# ── Design Constants — Full Size ─────────────────────────────────────────────

CARD_W = 900
CARD_H = 1200
CORNER_R = 48
CARD_PAD = 72
TEXT_AREA_W = CARD_W - (CARD_PAD * 2)

BG_COLOR       = (30, 30, 30)
BLACK_CARD_BG  = (0, 0, 0)
BLACK_CARD_FG  = (255, 255, 255)
WHITE_CARD_BG  = (255, 255, 255)
WHITE_CARD_FG  = (15, 15, 15)
FILLED_COLOR   = (255, 210, 60)
SHADOW_COLOR   = (0, 0, 0, 80)
NUMBER_BG      = (60, 60, 60)
NUMBER_FG      = (255, 255, 255)
LOGO_BLACK     = (255, 255, 255, 140)
LOGO_WHITE     = (0, 0, 0, 100)

CARD_GAP   = 54
CANVAS_PAD = 84

CARD_FONT_SIZE       = 48
CARD_FONT_SIZE_SMALL = 36
LOGO_FONT_SIZE       = 16
PACK_FONT_SIZE       = 16
NUMBER_FONT_SIZE     = 32

# Total footer height (text fallback): logo line + gap + pack line
FOOTER_H      = LOGO_FONT_SIZE + 8 + PACK_FONT_SIZE   # = 44px
FOOTER_RESERVED = CARD_PAD + FOOTER_H

LOGO_TEXT = "Cards Against the Wasteland"


# ── Design Constants — Hand Size (~35%) ──────────────────────────────────────

HAND_CARD_W = 450
HAND_CARD_H = 600
HAND_CORNER_R = 16
HAND_CARD_PAD = 22
HAND_TEXT_AREA_W = HAND_CARD_W - (HAND_CARD_PAD * 2)

HAND_CARD_FONT_SIZE       = 24
HAND_CARD_FONT_SIZE_SMALL = 18
HAND_LOGO_FONT_SIZE       = 8
HAND_PACK_FONT_SIZE       = 8
HAND_NUMBER_FONT_SIZE     = 16

HAND_CARD_GAP   = 14
HAND_CANVAS_PAD = 20
HAND_COLS       = 5

HAND_FOOTER_H        = HAND_LOGO_FONT_SIZE + 5 + HAND_PACK_FONT_SIZE   # = 23px
HAND_FOOTER_RESERVED = HAND_CARD_PAD + HAND_FOOTER_H


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

def _get_card_font(text: str, bold: bool = True):
    path = FONT_BOLD_PATH if bold else FONT_REG_PATH
    size = CARD_FONT_SIZE_SMALL if len(text) > 100 else CARD_FONT_SIZE
    return _load_font(path, size)

def _get_hand_font(text: str, bold: bool = False):
    path = FONT_BOLD_PATH if bold else FONT_REG_PATH
    size = HAND_CARD_FONT_SIZE_SMALL if len(text) > 80 else HAND_CARD_FONT_SIZE
    return _load_font(path, size)


# ── Pack Logo Image Cache ─────────────────────────────────────────────────────

_logo_cache: dict[str, Image.Image | None] = {}

def _load_pack_logo(pack_id: str, is_black: bool) -> Image.Image | None:
    """
    Load {pack_id}_black.png or {pack_id}_white.png from the script directory.
    Results are cached per variant. Returns RGBA image if found, None otherwise.
    """
    variant = "black" if is_black else "white"
    cache_key = f"{pack_id}_{variant}"
    if cache_key in _logo_cache:
        return _logo_cache[cache_key]
    if not pack_id:
        _logo_cache[cache_key] = None
        return None
    _here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(_here, f"{pack_id}_{variant}.png")
    if not os.path.exists(path):
        _logo_cache[cache_key] = None
        return None
    try:
        logo = Image.open(path).convert("RGBA")
        _logo_cache[cache_key] = logo
        print(f"[card_renderer] Loaded pack logo: {path}")
        return logo
    except Exception as e:
        print(f"[card_renderer] Failed to load logo {path}: {e}")
        _logo_cache[cache_key] = None
        return None


def _paste_logo(canvas: Image.Image, pack_id: str,
                x: int, y: int, target_h: int, max_w: int,
                is_black: bool = False):
    """
    Load the correct logo variant (_black.png or _white.png),
    scale it to target_h tall (preserving aspect ratio, capped at max_w),
    and composite it onto canvas at (x, y).
    Returns True if a logo was found and placed, False otherwise.
    """
    logo = _load_pack_logo(pack_id, is_black)
    if logo is None:
        return False

    orig_w, orig_h = logo.size
    scale = target_h / orig_h
    new_w = int(orig_w * scale)
    if new_w > max_w:
        scale = max_w / orig_w
        new_w = max_w
        target_h = int(orig_h * scale)

    logo_scaled = logo.resize((new_w, target_h), Image.LANCZOS)

    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.paste(logo_scaled, (x, y), logo_scaled)
    canvas.paste(canvas_rgba.convert("RGB"), (0, 0))
    return True


# ── Text Wrapping ────────────────────────────────────────────────────────────

def _wrap_text(text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        test = f"{current_line} {word}".strip()
        w = font.getbbox(test)[2] - font.getbbox(test)[0]
        if w <= max_width:
            current_line = test
        else:
            if current_line:
                lines.append(current_line)
            bw = font.getbbox(word)[2] - font.getbbox(word)[0]
            if bw > max_width:
                partial = ""
                for ch in word:
                    test_ch = partial + ch
                    if font.getbbox(test_ch)[2] - font.getbbox(test_ch)[0] > max_width and partial:
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

def _rounded_rect(draw, xy, radius, fill):
    draw.rounded_rectangle(xy, radius=radius, fill=fill)


def _draw_shadow(img, x, y, w, h, corner_r=None, offset=4):
    if corner_r is None:
        corner_r = CORNER_R
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rounded_rectangle(
        (x + offset, y + offset, x + w + offset, y + h + offset),
        radius=corner_r, fill=SHADOW_COLOR)
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"), (0, 0))


def _draw_footer(img, draw, x, y,
                 card_w, card_h, card_pad, text_area_w,
                 footer_h, logo_font_size, pack_font_size, gap,
                 is_black, pack_id, pack_name):
    """
    Draw the footer area of a card.
    - If a pack logo image exists for pack_id, paste it scaled to footer_h.
    - Otherwise draw LOGO_TEXT on line 1 and pack_name on line 2.
    """
    logo_col = LOGO_BLACK[:3] if is_black else LOGO_WHITE[:3]
    footer_y = y + card_h - card_pad - footer_h

    logo_placed = False
    if pack_id:
        logo_placed = _paste_logo(
            img, pack_id,
            x=x + card_pad,
            y=footer_y,
            target_h=footer_h,
            max_w=text_area_w,
            is_black=is_black)
        draw = ImageDraw.Draw(img)  # refresh after paste

    if not logo_placed:
        # Text fallback: two lines
        logo_font = _load_font(FONT_REG_PATH, logo_font_size)
        pack_font = _load_font(FONT_REG_PATH, pack_font_size)
        draw.text((x + card_pad, footer_y), LOGO_TEXT, fill=logo_col, font=logo_font)
        if pack_name:
            pack_y = y + card_h - card_pad - pack_font_size
            pack_line = pack_name
            while (pack_font.getbbox(pack_line)[2] - pack_font.getbbox(pack_line)[0] > text_area_w
                   and len(pack_line) > 5):
                pack_line = pack_line[:-2] + "…"
            draw.text((x + card_pad, pack_y), pack_line, fill=logo_col, font=pack_font)


def _draw_card(img, x, y, is_black, text,
               number=None, bold=True, pack_id=None, pack_name=None):
    """Draw a full-size card."""
    draw = ImageDraw.Draw(img)
    bg = BLACK_CARD_BG if is_black else WHITE_CARD_BG
    fg = BLACK_CARD_FG if is_black else WHITE_CARD_FG

    _draw_shadow(img, x, y, CARD_W, CARD_H, corner_r=CORNER_R)
    draw = ImageDraw.Draw(img)
    _rounded_rect(draw, (x, y, x + CARD_W, y + CARD_H), CORNER_R, fill=bg)

    font = _get_card_font(text, bold=bold)
    lines = _wrap_text(text, font, TEXT_AREA_W)
    line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]

    ty = y + CARD_PAD
    for line in lines:
        if ty + line_h > y + CARD_H - FOOTER_RESERVED:
            draw.text((x + CARD_PAD, ty), "...", fill=fg, font=font)
            break
        draw.text((x + CARD_PAD, ty), line, fill=fg, font=font)
        ty += line_h + 10

    _draw_footer(img, draw, x, y,
                 CARD_W, CARD_H, CARD_PAD, TEXT_AREA_W,
                 FOOTER_H, LOGO_FONT_SIZE, PACK_FONT_SIZE, 8,
                 is_black, pack_id, pack_name)
    draw = ImageDraw.Draw(img)

    if number is not None:
        num_font = _load_font(FONT_BOLD_PATH, NUMBER_FONT_SIZE)
        num_text = str(number)
        num_bbox = num_font.getbbox(num_text)
        num_w = num_bbox[2] - num_bbox[0] + 24
        num_h = num_bbox[3] - num_bbox[1] + 16
        nr_x = x + CARD_W - num_w - 14
        draw.rounded_rectangle(
            (nr_x, y + 14, nr_x + num_w, y + 14 + num_h),
            radius=num_h // 2,
            fill=NUMBER_BG if not is_black else (80, 80, 80))
        draw.text((nr_x + 12, y + 22), num_text, fill=NUMBER_FG, font=num_font)


def _draw_hand_card(img, x, y, text, number,
                    pack_id=None, pack_name=None,
                    highlight=False, dimmed=False):
    """Draw a scaled-down white card for the hand view."""
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

    font = _get_hand_font(text)
    lines = _wrap_text(text, font, HAND_TEXT_AREA_W)
    line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]

    ty = y + HAND_CARD_PAD
    for line in lines:
        if ty + line_h > y + HAND_CARD_H - HAND_FOOTER_RESERVED:
            draw.text((x + HAND_CARD_PAD, ty), "...", fill=WHITE_CARD_FG, font=font)
            break
        draw.text((x + HAND_CARD_PAD, ty), line, fill=WHITE_CARD_FG, font=font)
        ty += line_h + 4

    _draw_footer(img, draw, x, y,
                 HAND_CARD_W, HAND_CARD_H, HAND_CARD_PAD, HAND_TEXT_AREA_W,
                 HAND_FOOTER_H, HAND_LOGO_FONT_SIZE, HAND_PACK_FONT_SIZE, 5,
                 is_black=False, pack_id=pack_id, pack_name=pack_name)
    draw = ImageDraw.Draw(img)

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

    if dimmed:
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(overlay).rounded_rectangle(
            (x, y, x + HAND_CARD_W, y + HAND_CARD_H),
            radius=HAND_CORNER_R, fill=(0, 0, 0, 120))
        merged = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        img.paste(merged)


def _draw_black_card_filled(img, x, y, card_text, answers,
                             pack_id=None, pack_name=None):
    """Draw a black card with blanks filled in gold."""
    _draw_shadow(img, x, y, CARD_W, CARD_H, corner_r=CORNER_R)
    draw = ImageDraw.Draw(img)
    _rounded_rect(draw, (x, y, x + CARD_W, y + CARD_H), CORNER_R, fill=BLACK_CARD_BG)

    font = _get_card_font(card_text, bold=True)
    full_text = card_text
    for ans in answers:
        full_text = full_text.replace("_", ans, 1)

    lines = _wrap_text(full_text, font, TEXT_AREA_W)
    line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]

    # Build character color map
    color_map = []
    temp, answer_texts = card_text, list(answers)
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

    char_idx = 0
    ty = y + CARD_PAD
    for line in lines:
        if ty + line_h > y + CARD_H - FOOTER_RESERVED:
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
            tx += font.getbbox(ch)[2] - font.getbbox(ch)[0]
        ty += line_h + 10
        if char_idx < len(color_map) and line:
            if color_map[char_idx][0] == " ":
                char_idx += 1

    _draw_footer(img, draw, x, y,
                 CARD_W, CARD_H, CARD_PAD, TEXT_AREA_W,
                 FOOTER_H, LOGO_FONT_SIZE, PACK_FONT_SIZE, 8,
                 is_black=True, pack_id=pack_id, pack_name=pack_name)


# ── Public API ───────────────────────────────────────────────────────────────

def render_black_card(card_text: str, pick: int = 1,
                      pack_id: str = None, pack_name: str = None) -> io.BytesIO:
    """Render just the black card (round start). Returns BytesIO PNG."""
    display_text = card_text.replace("_", "_____")
    if pick > 1:
        display_text += f"\n\nPICK {pick}"
    img = Image.new("RGB", (CARD_W + CANVAS_PAD * 2, CARD_H + CANVAS_PAD * 2), BG_COLOR)
    _draw_card(img, CANVAS_PAD, CANVAS_PAD, is_black=True, text=display_text,
               bold=True, pack_id=pack_id, pack_name=pack_name)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


def render_judging(card_text: str, pick: int,
                   submissions: list[list[str]],
                   numbers: bool = True,
                   black_pack_id: str = None, black_pack_name: str = None,
                   white_pack_ids: list[list[str]] = None,
                   white_pack_names: list[list[str]] = None) -> io.BytesIO:
    """
    Render black card + all white submission cards.
    black_pack_id / black_pack_name: for the black card footer.
    white_pack_ids / white_pack_names: [[pack_id, ...], ...] per submission.
    Returns BytesIO PNG.
    """
    display_text = card_text.replace("_", "_____")
    if pick > 1:
        display_text += f"\n\nPICK {pick}"

    n_subs = len(submissions)
    cards_per_sub = max(len(s) for s in submissions) if submissions else 1
    sub_h = CARD_H if cards_per_sub == 1 else CARD_H * cards_per_sub + CARD_GAP * (cards_per_sub - 1)
    total_h = max(CARD_H, sub_h)

    canvas_w = (CANVAS_PAD + CARD_W + CARD_GAP * 2
                + CARD_W * n_subs + CARD_GAP * max(0, n_subs - 1)
                + CANVAS_PAD)
    img = Image.new("RGB", (canvas_w, CANVAS_PAD + total_h + CANVAS_PAD), BG_COLOR)

    bc_y = CANVAS_PAD + (total_h - CARD_H) // 2
    _draw_card(img, CANVAS_PAD, bc_y, is_black=True, text=display_text,
               bold=True, pack_id=black_pack_id, pack_name=black_pack_name)

    wx = CANVAS_PAD + CARD_W + CARD_GAP * 2
    for i, sub_cards in enumerate(submissions):
        num = i + 1 if numbers else None
        for j, wtext in enumerate(sub_cards):
            wy = CANVAS_PAD + j * (CARD_H + CARD_GAP)
            wpid  = white_pack_ids[i][j]  if white_pack_ids  and i < len(white_pack_ids)  and j < len(white_pack_ids[i])  else None
            wpname = white_pack_names[i][j] if white_pack_names and i < len(white_pack_names) and j < len(white_pack_names[i]) else None
            _draw_card(img, wx, wy, is_black=False, text=wtext,
                       number=num if j == 0 else None, bold=False,
                       pack_id=wpid, pack_name=wpname)
        wx += CARD_W + CARD_GAP

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


def render_winner(card_text: str, answers: list[str],
                  pack_id: str = None, pack_name: str = None) -> io.BytesIO:
    """Render black card with answers filled in gold. Returns BytesIO PNG."""
    img = Image.new("RGB", (CARD_W + CANVAS_PAD * 2, CARD_H + CANVAS_PAD * 2), BG_COLOR)
    _draw_black_card_filled(img, CANVAS_PAD, CANVAS_PAD, card_text, answers,
                            pack_id=pack_id, pack_name=pack_name)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


def render_hand(cards: list[str],
                white_pack_ids: dict[str, str] = None,
                white_pack_names: dict[str, str] = None,
                pending: list[str] = None,
                submitted: list[str] = None) -> io.BytesIO:
    """
    Render a player's hand as a 5-column grid of small white cards.

    white_pack_ids:  dict mapping card text -> pack_id  (for logo image lookup)
    white_pack_names: dict mapping card text -> pack display name (text fallback)
    pending:   cards selected but not finalized — gold highlight
    submitted: cards already submitted — dimmed
    Returns BytesIO PNG.
    """
    pending_set   = set(pending or [])
    submitted_set = set(submitted or [])
    white_pack_ids   = white_pack_ids or {}
    white_pack_names = white_pack_names or {}

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
            img, x, y, text=card_text, number=idx + 1,
            pack_id=white_pack_ids.get(card_text),
            pack_name=white_pack_names.get(card_text),
            highlight=card_text in pending_set,
            dimmed=card_text in submitted_set)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


# ── Quick test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    buf1 = render_black_card(
        "In his newest and most difficult stunt, David Blaine must escape from _.",
        pick=1, pack_id="base", pack_name="🎴 Base Set")
    with open("/tmp/test_black.png", "wb") as f: f.write(buf1.read())
    print("✅ test_black.png")

    buf2 = render_judging(
        "In his newest and most difficult stunt, David Blaine must escape from _.",
        pick=1,
        submissions=[["My inner demons."], ["A 55-gallon drum of lube."], ["The entire Mormon Tabernacle Choir."]],
        black_pack_id="base", black_pack_name="🎴 Base Set",
        white_pack_ids=[["geek"], ["base"], ["absurd"]],
        white_pack_names=[["🤓 Geek Pack"], ["🎴 Base Set"], ["🤪 Absurdist Pack"]])
    with open("/tmp/test_judging.png", "wb") as f: f.write(buf2.read())
    print("✅ test_judging.png")

    buf3 = render_winner(
        "In his newest and most difficult stunt, David Blaine must escape from _.",
        ["my inner demons"], pack_id="base", pack_name="🎴 Base Set")
    with open("/tmp/test_winner.png", "wb") as f: f.write(buf3.read())
    print("✅ test_winner.png")

    sample_hand = [
        "Coat hanger abortions.", "A tiny horse.", "Vehicular manslaughter.",
        "The clitoris.", "A bleached asshole.", "Crystal meth.",
        "Roofies.", "My inner demons.", "Puppies!", "Getting really high."
    ]
    buf4 = render_hand(
        sample_hand,
        white_pack_ids={c: "base" for c in sample_hand},
        white_pack_names={c: "🎴 Base Set" for c in sample_hand},
        pending=["A tiny horse."], submitted=["Crystal meth."])
    with open("/tmp/test_hand.png", "wb") as f: f.write(buf4.read())
    print("✅ test_hand.png")
