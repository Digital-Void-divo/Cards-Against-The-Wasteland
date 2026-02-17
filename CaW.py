"""
Cards Against Humanity — Discord Bot  v3.0
============================================
Fully in-channel with ephemeral interactions. No DMs needed.

Setup:
  1. pip install discord.py
  2. export DISCORD_BOT_TOKEN="your-token"
  3. python CaW.py
"""

import discord
from discord.ext import commands
from discord import ui
import json, random, asyncio, os, io
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

# Card image renderer
from card_renderer import render_black_card, render_judging, render_winner

# ── Configuration ────────────────────────────────────────────────────────────

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "YOUR_TOKEN_HERE")
COMMAND_PREFIX = "!cah "
HAND_SIZE = 10
MIN_PLAYERS = 3
DEFAULT_WIN_SCORE = 7
BLANK = "▬▬▬▬▬"

# Card file — checks script dir then cwd
_script_dir = Path(os.path.dirname(os.path.abspath(__file__)))
if (_script_dir / "cards.json").exists():
    CARDS_FILE = _script_dir / "cards.json"
elif Path("cards.json").exists():
    CARDS_FILE = Path("cards.json")
else:
    print(f"ERROR: cards.json not found in {_script_dir} or {Path.cwd()}")
    exit(1)


# ── Colors ───────────────────────────────────────────────────────────────────

class C:
    BLACK   = 0x1a1a1a
    WHITE   = 0xf5f5f5
    GOLD    = 0xf1c40f
    GREEN   = 0x2ecc71
    BLUE    = 0x3498db
    PURPLE  = 0x9b59b6
    RED     = 0xe74c3c
    ORANGE  = 0xe67e22
    DARK    = 0x2c2f33


# ── Card Database ────────────────────────────────────────────────────────────

class CardDB:
    def __init__(self, path: str | Path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.packs: dict[str, dict] = data["packs"]

    @property
    def pack_ids(self) -> list[str]:
        return list(self.packs.keys())

    def pack_info(self, pack_id: str) -> dict:
        p = self.packs[pack_id]
        return {
            "name": p["name"],
            "description": p.get("description", ""),
            "white_count": len(p["white"]),
            "black_count": len(p["black"]),
        }

    def build_deck(self, pack_ids: list[str]) -> tuple[list[str], list[dict], dict[str, str]]:
        whites, blacks = [], []
        white_pack: dict[str, str] = {}   # card text -> pack name
        for pid in pack_ids:
            if pid in self.packs:
                pack_name = self.packs[pid]["name"]
                for w in self.packs[pid]["white"]:
                    whites.append(w)
                    white_pack[w] = pack_name
                for b in self.packs[pid]["black"]:
                    blacks.append({**b, "pack": pack_name})
        return whites, blacks, white_pack

    @property
    def total_white(self) -> int:
        return sum(len(p["white"]) for p in self.packs.values())

    @property
    def total_black(self) -> int:
        return sum(len(p["black"]) for p in self.packs.values())


class Deck:
    def __init__(self, whites: list[str], blacks: list[dict]):
        self.white_draw = list(whites)
        self.black_draw = list(blacks)
        self.white_discard: list[str] = []
        self.black_discard: list[dict] = []
        random.shuffle(self.white_draw)
        random.shuffle(self.black_draw)

    def draw_white(self, n: int = 1) -> list[str]:
        cards = []
        for _ in range(n):
            if not self.white_draw:
                if not self.white_discard:
                    raise RuntimeError("No white cards left!")
                self.white_draw = self.white_discard
                self.white_discard = []
                random.shuffle(self.white_draw)
            cards.append(self.white_draw.pop())
        return cards

    def draw_black(self) -> dict:
        if not self.black_draw:
            if not self.black_discard:
                raise RuntimeError("No black cards left!")
            self.black_draw = self.black_discard
            self.black_discard = []
            random.shuffle(self.black_draw)
        return self.black_draw.pop()

    def discard_white(self, cards: list[str]):
        self.white_discard.extend(cards)

    def discard_black(self, card: dict):
        self.black_discard.append(card)


# ── Game State ───────────────────────────────────────────────────────────────

class Phase(Enum):
    LOBBY    = auto()
    PACKS    = auto()
    PLAYING  = auto()
    JUDGING  = auto()
    FINISHED = auto()

class GameMode(Enum):
    ADHOC = auto()
    FULL  = auto()

@dataclass
class Player:
    member: discord.Member
    hand: list[str] = field(default_factory=list)
    score: int = 0
    pending_picks: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.member.display_name

    @property
    def id(self) -> int:
        return self.member.id


class Game:
    def __init__(self, channel: discord.TextChannel, host: discord.Member,
                 mode: GameMode, win_score: int):
        self.channel = channel
        self.host = host
        self.mode = mode
        self.win_score = win_score
        self.deck: Optional[Deck] = None
        self.selected_packs: list[str] = []
        self.white_pack: dict[str, str] = {}   # card text -> pack name

        self.phase = Phase.LOBBY
        self.players: dict[int, Player] = {}
        self.czar_order: list[int] = []
        self.czar_index: int = 0
        self.round_number: int = 0

        self.black_card: Optional[dict] = None
        self.submissions: dict[int, list[str]] = {}
        self.submission_order: list[int] = []

        # reference to the active round view so it persists
        self.round_view: Optional["RoundPlayView"] = None

    def add_player(self, member: discord.Member) -> bool:
        if member.id in self.players:
            return False
        self.players[member.id] = Player(member=member)
        self.czar_order.append(member.id)
        return True

    def remove_player(self, member_id: int) -> Optional[Player]:
        p = self.players.pop(member_id, None)
        if p:
            if self.deck:
                self.deck.discard_white(p.hand)
                self.deck.discard_white(p.pending_picks)
            if member_id in self.czar_order:
                self.czar_order.remove(member_id)
                if self.czar_index >= len(self.czar_order) and self.czar_order:
                    self.czar_index = 0
            if member_id in self.submissions:
                if self.deck:
                    self.deck.discard_white(self.submissions.pop(member_id))
                if member_id in self.submission_order:
                    self.submission_order.remove(member_id)
        return p

    @property
    def czar_id(self) -> Optional[int]:
        if not self.czar_order:
            return None
        return self.czar_order[self.czar_index % len(self.czar_order)]

    @property
    def czar(self) -> Optional[Player]:
        cid = self.czar_id
        return self.players.get(cid) if cid else None

    def setup_deck(self, pack_ids: list[str], db: CardDB):
        self.selected_packs = pack_ids
        whites, blacks, white_pack = db.build_deck(pack_ids)
        self.deck = Deck(whites, blacks)
        self.white_pack = white_pack

    def start_round(self) -> dict:
        self.round_number += 1
        self.phase = Phase.PLAYING
        self.submissions.clear()
        self.submission_order.clear()
        self.black_card = self.deck.draw_black()
        for pid, player in self.players.items():
            player.pending_picks.clear()
            deficit = HAND_SIZE - len(player.hand)
            if deficit > 0:
                player.hand.extend(self.deck.draw_white(deficit))
        return self.black_card

    def submit_card_by_value(self, player_id: int, card_text: str):
        player = self.players[player_id]
        if card_text in player.hand:
            player.hand.remove(card_text)
            player.pending_picks.append(card_text)

    def finalize_submission(self, player_id: int):
        player = self.players[player_id]
        self.submissions[player_id] = list(player.pending_picks)
        player.pending_picks.clear()

    def cancel_pending(self, player_id: int):
        player = self.players[player_id]
        player.hand.extend(player.pending_picks)
        player.pending_picks.clear()

    def all_submitted(self) -> bool:
        expected = {pid for pid in self.players if pid != self.czar_id}
        return expected == set(self.submissions.keys())

    def begin_judging(self) -> list[tuple[int, list[str]]]:
        self.phase = Phase.JUDGING
        entries = list(self.submissions.items())
        random.shuffle(entries)
        self.submission_order = [pid for pid, _ in entries]
        return entries

    def pick_winner(self, choice: int) -> Player:
        if choice < 1 or choice > len(self.submission_order):
            raise ValueError(f"Pick 1–{len(self.submission_order)}.")
        winner_id = self.submission_order[choice - 1]
        winner = self.players[winner_id]
        winner.score += 1
        for cards in self.submissions.values():
            self.deck.discard_white(cards)
        self.deck.discard_black(self.black_card)
        return winner

    def advance_czar(self):
        self.czar_index = (self.czar_index + 1) % len(self.czar_order)

    def check_game_over(self) -> Optional[Player]:
        if self.mode == GameMode.ADHOC:
            return None
        for p in self.players.values():
            if p.score >= self.win_score:
                return p
        return None


# ── Formatting ───────────────────────────────────────────────────────────────

def fmt_black(card: dict, answers: list[str] = None) -> str:
    text = card["text"]
    if answers:
        for ans in answers:
            text = text.replace("_", f"**{ans}**", 1)
        return text
    else:
        formatted = text.replace("_", BLANK)
        if card["pick"] > 1:
            formatted += f"\n\n*⎡ PICK {card['pick']} — play cards one at a time, in order ⎤*"
        return formatted

def fmt_scores(players: dict[int, Player], compact: bool = False) -> str:
    sorted_p = sorted(players.values(), key=lambda p: p.score, reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, p in enumerate(sorted_p):
        medal = medals[i] if i < len(medals) else "▫️"
        pts = f"{p.score} pt{'s' if p.score != 1 else ''}"
        lines.append(f"{medal} **{p.name}** — {pts}" if not compact else f"{medal} {p.name}: {pts}")
    return "\n".join(lines)

def trunc(text: str, n: int = 95) -> str:
    return text[:n] + "…" if len(text) > n else text

def waiting_names(game: Game) -> list[str]:
    return [game.players[pid].name for pid in game.players
            if pid != game.czar_id and pid not in game.submissions
            and pid not in [p for p in game.players if game.players[p].pending_picks]]

def submitted_names(game: Game) -> list[str]:
    return [game.players[pid].name for pid in game.submissions]

def in_progress_names(game: Game) -> list[str]:
    """Players who have started picking but not finalized."""
    return [game.players[pid].name for pid in game.players
            if pid != game.czar_id and pid not in game.submissions
            and game.players[pid].pending_picks]


# ── UI VIEWS ─────────────────────────────────────────────────────────────────

# ──────────── Pack Selection (Checkbox-style Toggle Buttons) ────────────

class PackSelectView(ui.View):
    """
    Checkbox-style pack picker.
    Each pack gets its own toggle button — green = selected, grey = deselected.
    Up to 25 packs supported (Discord button limit).
    """
    def __init__(self, game: Game, db: CardDB):
        super().__init__(timeout=120)
        self.game = game
        self.db = db
        # Default: only "base" selected (or first pack if no "base")
        first = "base" if "base" in db.pack_ids else db.pack_ids[0]
        self.selected: set[str] = {first}

        for idx, pid in enumerate(list(db.pack_ids)[:20]):   # rows 0-3, max 5 per row
            info = db.pack_info(pid)
            is_on = pid in self.selected
            btn = ui.Button(
                label=self._btn_label(info),
                emoji="✅" if is_on else "⬜",
                style=discord.ButtonStyle.success if is_on else discord.ButtonStyle.secondary,
                custom_id=f"pack_toggle_{pid}",
                row=self._btn_row(idx),
            )
            btn.callback = self._make_toggle(pid)
            self.add_item(btn)

        confirm = ui.Button(
            label="Confirm Packs",
            emoji="✅",
            style=discord.ButtonStyle.green,
            custom_id="pack_confirm",
            row=4,
        )
        confirm.callback = self._confirm
        self.add_item(confirm)

    @staticmethod
    def _btn_label(info: dict) -> str:
        desc = info["description"][:28] + "…" if len(info["description"]) > 28 else info["description"]
        return f"{info['name']}  •  {info['white_count']}⬜{info['black_count']}⬛  •  {desc}"[:80]

    @staticmethod
    def _btn_row(index: int) -> int:
        return min(index // 5, 3)

    def _make_toggle(self, pid: str):
        async def toggle(interaction: discord.Interaction):
            if interaction.user.id != self.game.host.id:
                return await interaction.response.send_message(
                    "Only the host can choose packs.", ephemeral=True)

            if pid in self.selected:
                if len(self.selected) == 1:
                    return await interaction.response.send_message(
                        "You must keep at least one pack selected!", ephemeral=True)
                self.selected.discard(pid)
            else:
                self.selected.add(pid)

            for child in self.children:
                if getattr(child, "custom_id", None) == f"pack_toggle_{pid}":
                    is_on = pid in self.selected
                    child.emoji = "✅" if is_on else "⬜"
                    child.style = (discord.ButtonStyle.success
                                   if is_on else discord.ButtonStyle.secondary)
                    break

            await interaction.response.edit_message(
                embed=self._build_embed(), view=self)

        return toggle

    async def _confirm(self, interaction: discord.Interaction):
        if interaction.user.id != self.game.host.id:
            return await interaction.response.send_message(
                "Only the host can confirm.", ephemeral=True)

        pack_list = list(self.selected)
        self.game.setup_deck(pack_list, self.db)
        pack_names = ", ".join(self.db.pack_info(p)["name"] for p in pack_list)

        self.stop()
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="✅ Packs Locked In!",
                description=f"**Using:** {pack_names}",
                color=C.GREEN),
            view=self)

        # Show lobby
        self.game.phase = Phase.LOBBY
        lobby_view = LobbyView(self.game, self.db)
        await interaction.followup.send(
            embed=lobby_view._embed(f"⏳ Need {MIN_PLAYERS - 1} more player(s)"),
            view=lobby_view)

    def _build_embed(self) -> discord.Embed:
        total_w = sum(self.db.pack_info(p)["white_count"] for p in self.selected)
        total_b = sum(self.db.pack_info(p)["black_count"] for p in self.selected)
        pack_names = ", ".join(self.db.pack_info(p)["name"] for p in self.selected)

        lines = []
        for pid in self.db.pack_ids:
            info = self.db.pack_info(pid)
            tick = "✅" if pid in self.selected else "⬜"
            lines.append(
                f"{tick} **{info['name']}** — "
                f"{info['white_count']}⬜ {info['black_count']}⬛ — "
                f"*{info['description']}*"
            )

        return discord.Embed(
            title="📦 Choose Your Card Packs",
            description="\n".join(lines) +
                        f"\n\n**Selected:** {pack_names}\n"
                        f"**Total cards:** {total_w}⬜ {total_b}⬛\n\n"
                        f"*Toggle packs above, then click **Confirm**.*",
            color=C.BLUE)


# ──────────── Lobby ────────────

class LobbyView(ui.View):
    def __init__(self, game: Game, db: CardDB):
        super().__init__(timeout=600)
        self.game = game
        self.db = db

    def _player_list(self) -> str:
        return "\n".join(f"` {i}. ` {p.name}" for i, p in enumerate(self.game.players.values(), 1))

    def _embed(self, footer: str) -> discord.Embed:
        mode = f"First to **{self.game.win_score}** points" if self.game.mode == GameMode.FULL else "**Quick Round**"

        pack_line = ""
        if self.game.selected_packs:
            pack_names = ", ".join(self.db.pack_info(p)["name"] for p in self.game.selected_packs)
            total_w = sum(self.db.pack_info(p)["white_count"] for p in self.game.selected_packs)
            total_b = sum(self.db.pack_info(p)["black_count"] for p in self.game.selected_packs)
            pack_line = f"\n📦 **Packs:** {pack_names} ({total_w}⬜ {total_b}⬛)"

        embed = discord.Embed(
            title="🃏 Cards Against Humanity",
            description=f"**{self.game.host.display_name}** is hosting!\n\n"
                        f"🏆 {mode}{pack_line}\n\n**Players:**\n{self._player_list()}",
            color=C.BLACK)
        embed.set_footer(text=footer)
        return embed

    @ui.button(label="Join Game", style=discord.ButtonStyle.green, emoji="🎮")
    async def join_btn(self, interaction: discord.Interaction, button: ui.Button):
        if self.game.phase != Phase.LOBBY:
            return await interaction.response.send_message("Game already started!", ephemeral=True)
        if self.game.add_player(interaction.user):
            n = len(self.game.players)
            status = "✅ Enough players — host can start!" if n >= MIN_PLAYERS else f"⏳ Need {MIN_PLAYERS - n} more"
            await interaction.response.edit_message(embed=self._embed(status), view=self)
        else:
            await interaction.response.send_message("You're already in!", ephemeral=True)

    @ui.button(label="Begin Game", style=discord.ButtonStyle.blurple, emoji="🚀")
    async def begin_btn(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.game.host.id:
            return await interaction.response.send_message("Only the host can start.", ephemeral=True)
        if len(self.game.players) < MIN_PLAYERS:
            return await interaction.response.send_message(
                f"Need {MIN_PLAYERS} players. Currently: {len(self.game.players)}", ephemeral=True)

        self.stop()
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=self._embed("🎮 Game starting..."), view=self)

        random.shuffle(self.game.czar_order)
        await interaction.followup.send(
            embed=discord.Embed(title="🃏 Let's Go!", description="Shuffling the deck and dealing hands...", color=C.DARK))
        await start_round(self.game)


# ──────────── Ephemeral Hand Select (Pick 1) ────────────

class EphemeralHandSelect(ui.View):
    """Sent as an ephemeral followup. Player picks one card via dropdown."""
    def __init__(self, game: Game, player: Player, pick_num: int, total_picks: int):
        super().__init__(timeout=300)
        self.game = game
        self.player = player
        self.pick_num = pick_num
        self.total_picks = total_picks
        self.done = False

        ordinals = {1: "first", 2: "second", 3: "third"}
        label = "Pick a card" if total_picks == 1 else f"Pick your {ordinals.get(pick_num, f'#{pick_num}')} card"

        options = []
        for i, card in enumerate(player.hand):
            options.append(discord.SelectOption(label=trunc(card, 95), value=str(i), emoji="🃏"))

        sel = ui.Select(placeholder=label, min_values=1, max_values=1, options=options[:25])
        sel.callback = self.on_select
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        if self.done:
            return await interaction.response.send_message("Already submitted!", ephemeral=True)

        idx = int(interaction.data["values"][0])
        if idx >= len(self.player.hand):
            return await interaction.response.send_message("Invalid card.", ephemeral=True)

        card_text = self.player.hand[idx]
        self.game.submit_card_by_value(self.player.id, card_text)

        if self.pick_num >= self.total_picks:
            self.game.finalize_submission(self.player.id)
            self.done = True
            self.stop()

            played = self.game.submissions[self.player.id]
            played_str = "\n".join(f"` {i}. ` {c}" for i, c in enumerate(played, 1))

            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="✅ Cards Submitted!",
                    description=f"You played:\n{played_str}",
                    color=C.GREEN),
                view=None)

            await update_round_status(self.game)

            if self.game.all_submitted():
                await begin_judging_phase(self.game)

        else:
            self.done = True
            self.stop()

            ordinals = {1: "first", 2: "second", 3: "third"}
            next_num = self.pick_num + 1
            next_label = ordinals.get(next_num, f"#{next_num}")

            picked_so_far = ", ".join(f"**{c}**" for c in self.player.pending_picks)

            await interaction.response.edit_message(
                embed=discord.Embed(
                    title=f"✅ Card {self.pick_num} locked in!",
                    description=f"You picked: **{card_text}**\n\nNow pick your **{next_label}** card below.",
                    color=C.ORANGE),
                view=None)

            next_view = EphemeralHandSelect(self.game, self.player, next_num, self.total_picks)
            bc = fmt_black(self.game.black_card)
            await interaction.followup.send(
                embed=discord.Embed(
                    title=f"🃏 Pick your {next_label} card",
                    description=f"**Black Card:**\n>>> {bc}\n\n"
                                f"**Already picked:** {picked_so_far}\n\n"
                                f"**Your remaining cards:**\n" +
                                "\n".join(f"` {i}. ` {c}" for i, c in enumerate(self.player.hand, 1)),
                    color=C.PURPLE),
                view=next_view,
                ephemeral=True)


# ──────────── Round Play Button (in channel) ────────────

class RoundPlayView(ui.View):
    """
    Persistent view on the round embed.
    Players click 'Play Card(s)' to get their hand ephemerally.
    """
    def __init__(self, game: Game):
        super().__init__(timeout=None)
        self.game = game

    @ui.button(label="Play Card(s)", style=discord.ButtonStyle.green, emoji="🃏")
    async def play_btn(self, interaction: discord.Interaction, button: ui.Button):
        game = self.game
        uid = interaction.user.id

        if uid not in game.players:
            return await interaction.response.send_message(
                "You're not in this game!", ephemeral=True)

        if game.phase != Phase.PLAYING:
            return await interaction.response.send_message(
                "It's not time to play cards right now.", ephemeral=True)

        if uid == game.czar_id:
            return await interaction.response.send_message(
                "🎩 You're the **Card Czar** this round!\nSit back and wait — you'll judge once everyone submits.",
                ephemeral=True)

        if uid in game.submissions:
            played = game.submissions[uid]
            played_str = "\n".join(f"` {i}. ` {c}" for i, c in enumerate(played, 1))
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title="✅ Already Submitted",
                    description=f"Your cards this round:\n{played_str}",
                    color=C.GREEN),
                ephemeral=True)

        player = game.players[uid]

        if player.pending_picks:
            ordinals = {1: "first", 2: "second", 3: "third"}
            next_num = len(player.pending_picks) + 1
            next_label = ordinals.get(next_num, f"#{next_num}")
            picked_so_far = ", ".join(f"**{c}**" for c in player.pending_picks)

            view = EphemeralHandSelect(game, player, next_num, game.black_card["pick"])
            bc = fmt_black(game.black_card)
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"🃏 Continue — pick your {next_label} card",
                    description=f"**Black Card:**\n>>> {bc}\n\n"
                                f"**Already picked:** {picked_so_far}\n\n"
                                f"**Your remaining cards:**\n" +
                                "\n".join(f"` {i}. ` {c}" for i, c in enumerate(player.hand, 1)),
                    color=C.PURPLE),
                view=view, ephemeral=True)

        pick = game.black_card["pick"]
        view = EphemeralHandSelect(game, player, 1, pick)
        bc = fmt_black(game.black_card)

        hand_display = "\n".join(f"` {i:>2}. ` {card}" for i, card in enumerate(player.hand, 1))

        embed = discord.Embed(
            title=f"🃏 Your Hand — Round {game.round_number}",
            color=C.BLACK)
        embed.add_field(name="⬛ Black Card", value=f">>> {bc}", inline=False)
        embed.add_field(name="⬜ Your Cards", value=hand_display, inline=False)

        if pick > 1:
            embed.set_footer(text=f"This card requires {pick} answers — pick them one at a time, in order!")
        else:
            embed.set_footer(text="Select a card from the dropdown below.")

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @ui.button(label="View Hand", style=discord.ButtonStyle.gray, emoji="👁️")
    async def view_btn(self, interaction: discord.Interaction, button: ui.Button):
        game = self.game
        uid = interaction.user.id

        if uid not in game.players:
            return await interaction.response.send_message("You're not in this game!", ephemeral=True)

        if uid == game.czar_id:
            return await interaction.response.send_message(
                "🎩 You're the **Card Czar** — no hand to view!", ephemeral=True)

        player = game.players[uid]
        hand_display = "\n".join(f"` {i:>2}. ` {card}" for i, card in enumerate(player.hand, 1))

        embed = discord.Embed(title="👁️ Your Hand", description=hand_display, color=C.WHITE)
        if uid in game.submissions:
            played = game.submissions[uid]
            embed.add_field(name="✅ You played", value="\n".join(f"` • ` {c}" for c in played), inline=False)
        elif player.pending_picks:
            embed.add_field(name="⏳ In progress", value="\n".join(f"` • ` {c}" for c in player.pending_picks), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


# ──────────── Judging (Ephemeral Czar Pick) ────────────

class JudgingButtonView(ui.View):
    def __init__(self, game: Game, entries: list[tuple[int, list[str]]]):
        super().__init__(timeout=None)
        self.game = game
        self.entries = entries
        self.done = False

    @ui.button(label="Pick the Winner", style=discord.ButtonStyle.blurple, emoji="🎩")
    async def pick_btn(self, interaction: discord.Interaction, button: ui.Button):
        if self.done:
            return await interaction.response.send_message("Winner already picked!", ephemeral=True)
        if interaction.user.id != self.game.czar_id:
            return await interaction.response.send_message(
                "Only the **Card Czar** can pick the winner!", ephemeral=True)

        view = CzarPickDropdown(self.game, self.entries, self)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🎩 Pick the Winner",
                description="Choose the funniest submission below.\nYour pick will be revealed to everyone!",
                color=C.PURPLE),
            view=view, ephemeral=True)

    async def disable_all(self, message: discord.Message):
        self.done = True
        self.stop()
        for child in self.children:
            child.disabled = True
        try:
            await message.edit(view=self)
        except discord.NotFound:
            pass


class CzarPickDropdown(ui.View):
    def __init__(self, game: Game, entries: list[tuple[int, list[str]]],
                 parent_view: JudgingButtonView):
        super().__init__(timeout=300)
        self.game = game
        self.entries = entries
        self.parent_view = parent_view
        self.done = False

        options = []
        for i, (pid, cards) in enumerate(entries, 1):
            combined = " | ".join(cards)
            options.append(discord.SelectOption(
                label=f"#{i}: {trunc(combined, 90)}",
                value=str(i), emoji="⭐"))

        sel = ui.Select(placeholder="Pick the funniest...", min_values=1, max_values=1, options=options[:25])
        sel.callback = self.on_pick
        self.add_item(sel)

    async def on_pick(self, interaction: discord.Interaction):
        if self.done:
            return await interaction.response.send_message("Already picked!", ephemeral=True)

        choice = int(interaction.data["values"][0])
        winner = self.game.pick_winner(choice)
        self.done = True
        self.stop()

        winning_cards = self.game.submissions[winner.id]
        filled = fmt_black(self.game.black_card, winning_cards)

        winner_img = render_winner(
            self.game.black_card["text"], winning_cards,
            pack_name=self.game.black_card.get("pack", ""))
        card_file = discord.File(winner_img, filename="winner.png")

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="✅ Winner Selected!",
                description=f"You picked **{winner.name}**'s answer.\nRevealing to the channel...",
                color=C.GREEN),
            view=None)

        embed = discord.Embed(title="🏆 Round Winner!", color=C.GOLD)
        embed.set_image(url="attachment://winner.png")
        embed.add_field(
            name=f"🎉 {winner.name} wins this round!",
            value=f"\n>>> {filled}", inline=False)
        embed.add_field(
            name="Score",
            value=f"**{winner.name}** now has **{winner.score}** point{'s' if winner.score != 1 else ''}",
            inline=False)
        embed.add_field(
            name="Scoreboard",
            value=fmt_scores(self.game.players, compact=True), inline=False)
        await self.game.channel.send(embed=embed, file=card_file)

        game_winner = self.game.check_game_over()
        if game_winner:
            self.game.phase = Phase.FINISHED
            embed = discord.Embed(
                title="🎊  GAME OVER  🎊",
                description=f"# 🏆 {game_winner.name} wins!\n\n"
                            f"with **{game_winner.score}** points\n\n"
                            f"**Final Scores:**\n{fmt_scores(self.game.players)}",
                color=C.GOLD)
            await self.game.channel.send(embed=embed)
            if self.game.channel.id in active_games:
                del active_games[self.game.channel.id]
            return

        if self.game.mode == GameMode.ADHOC:
            embed = discord.Embed(
                title="✅ Quick Round Complete!",
                description=f"Thanks for playing!\n\n{fmt_scores(self.game.players)}",
                color=C.BLUE)
            await self.game.channel.send(embed=embed)
            self.game.phase = Phase.FINISHED
            if self.game.channel.id in active_games:
                del active_games[self.game.channel.id]
            return

        self.game.advance_czar()
        await asyncio.sleep(3)
        await start_round(self.game)


# ── Round Flow ───────────────────────────────────────────────────────────────

async def start_round(game: Game):
    black = game.start_round()
    czar = game.czar

    non_czar = [game.players[pid].name for pid in game.players if pid != game.czar_id]

    card_img = render_black_card(
        black["text"], black["pick"],
        pack_name=black.get("pack", ""))
    card_file = discord.File(card_img, filename="black_card.png")

    embed = discord.Embed(title=f"━━━━ Round {game.round_number} ━━━━", color=C.BLACK)
    embed.set_image(url="attachment://black_card.png")
    embed.add_field(name="🎩 Card Czar", value=f"{czar.member.mention}", inline=True)
    embed.add_field(name="⏳ Waiting On", value=", ".join(non_czar), inline=True)

    footer = f"First to {game.win_score} pts" if game.mode == GameMode.FULL else "Quick Round"
    embed.set_footer(text=f"{footer} • Click below to view your hand and play!")

    view = RoundPlayView(game)
    game.round_view = view
    msg = await game.channel.send(embed=embed, file=card_file, view=view)
    game._round_msg = msg


async def update_round_status(game: Game):
    msg = getattr(game, "_round_msg", None)
    if not msg:
        return

    black = game.black_card
    czar = game.czar

    done = submitted_names(game)
    still_waiting = [game.players[pid].name for pid in game.players
                     if pid != game.czar_id and pid not in game.submissions]
    in_prog = in_progress_names(game)

    embed = discord.Embed(title=f"━━━━ Round {game.round_number} ━━━━", color=C.BLACK)
    embed.add_field(name="⬛ Black Card", value=f">>> {fmt_black(black)}", inline=False)
    embed.add_field(name="🎩 Card Czar", value=f"{czar.member.mention}", inline=True)

    status_parts = []
    if done:
        status_parts.append(f"✅ {', '.join(done)}")
    if in_prog:
        status_parts.append(f"✍️ {', '.join(in_prog)}")
    if still_waiting:
        status_parts.append(f"⏳ {', '.join(still_waiting)}")

    embed.add_field(name="Status", value="\n".join(status_parts) or "Everyone submitted!", inline=True)

    footer = f"First to {game.win_score} pts" if game.mode == GameMode.FULL else "Quick Round"
    embed.set_footer(text=f"{footer} • Click below to view your hand and play!")

    try:
        await msg.edit(embed=embed)
    except discord.NotFound:
        pass


async def begin_judging_phase(game: Game):
    entries = game.begin_judging()

    if game.round_view:
        game.round_view.stop()

    submission_cards = [cards for _, cards in entries]

    judging_img = render_judging(
        game.black_card["text"], game.black_card["pick"],
        submission_cards,
        numbers=True,
        black_pack=game.black_card.get("pack", ""),
        white_packs=[[game.white_pack.get(c, "") for c in cards]
                     for cards in submission_cards])
    card_file = discord.File(judging_img, filename="judging.png")

    embed = discord.Embed(title="⚖️ All Cards Are In!", color=C.PURPLE)
    embed.set_image(url="attachment://judging.png")

    subs_text = ""
    for i, (pid, cards) in enumerate(entries, 1):
        combined = " **┃** ".join(cards)
        subs_text += f"**` {i} `** {combined}\n"

    embed.add_field(name="📋 Submissions", value=subs_text, inline=False)
    embed.add_field(
        name="🎩 Czar",
        value=f"{game.czar.member.mention} — click the button to pick the winner!",
        inline=False)

    view = JudgingButtonView(game, entries)
    await game.channel.send(embed=embed, file=card_file, view=view)


# ── Bot Setup ────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents, help_command=None)
active_games: dict[int, Game] = {}
cards_db = CardDB(CARDS_FILE)


@bot.event
async def on_ready():
    print(f"✅  {bot.user} online | {cards_db.total_white}⬜ {cards_db.total_black}⬛ across {len(cards_db.pack_ids)} packs")
    await bot.change_presence(activity=discord.Game(name="Cards Against Humanity | !cah help"))


# ── Commands ─────────────────────────────────────────────────────────────────

@bot.command(name="help")
async def cah_help(ctx: commands.Context):
    embed = discord.Embed(
        title="🃏 Cards Against Humanity",
        description="*A horrible card game for horrible people.*",
        color=C.BLACK)
    embed.add_field(name="🎮 Starting", inline=False, value=(
        "`!cah start [score]` — Full game (default: first to 7)\n"
        "`!cah quickround` — Single round\n"
        "Select packs, then use the **Join** / **Begin** buttons!"))
    embed.add_field(name="🎴 Playing", inline=False, value=(
        "Click **Play Card(s)** on the round post — your hand appears privately.\n"
        "Pick-2 cards are submitted one at a time in order.\n"
        "Only you can see your hand and selection!"))
    embed.add_field(name="🎩 Judging", inline=False, value=(
        "The Card Czar clicks **Pick the Winner** — they see a private dropdown.\n"
        "The winner is then revealed to the whole channel."))
    embed.add_field(name="📊 Management", inline=False, value=(
        "`!cah status` — Scores & round info\n"
        "`!cah skip` — *(Host)* Skip AFK czar\n"
        "`!cah remove @player` — *(Host)* Remove player\n"
        "`!cah leave` — Leave the game\n"
        "`!cah end` — *(Host)* End game\n"
        "`!cah cards` — Card database stats"))
    embed.set_footer(text=f"Min {MIN_PLAYERS} players • No DMs needed — everything is in-channel!")
    await ctx.send(embed=embed)


@bot.command(name="cards")
async def cah_cards(ctx: commands.Context):
    embed = discord.Embed(title="📦 Card Packs", color=C.BLUE)
    for pid in cards_db.pack_ids:
        info = cards_db.pack_info(pid)
        embed.add_field(
            name=info["name"],
            value=f"{info['white_count']}⬜ • {info['black_count']}⬛\n*{info['description']}*",
            inline=False)
    embed.set_footer(text=f"Total: {cards_db.total_white}⬜ {cards_db.total_black}⬛ • Edit cards.json to add more!")
    await ctx.send(embed=embed)


@bot.command(name="start")
async def cah_start(ctx: commands.Context, score: int = DEFAULT_WIN_SCORE):
    if ctx.channel.id in active_games:
        return await ctx.send("⚠️ A game is already running here. Use `!cah end` first.")
    if score < 1 or score > 50:
        return await ctx.send("⚠️ Score must be between 1 and 50.")
    game = Game(ctx.channel, ctx.author, GameMode.FULL, score)
    game.add_player(ctx.author)
    active_games[ctx.channel.id] = game
    game.phase = Phase.PACKS
    pack_view = PackSelectView(game, cards_db)
    await ctx.send(embed=pack_view._build_embed(), view=pack_view)


@bot.command(name="quickround")
async def cah_quickround(ctx: commands.Context):
    if ctx.channel.id in active_games:
        return await ctx.send("⚠️ A game is already running here. Use `!cah end` first.")
    game = Game(ctx.channel, ctx.author, GameMode.ADHOC, 1)
    game.add_player(ctx.author)
    active_games[ctx.channel.id] = game
    game.phase = Phase.PACKS
    pack_view = PackSelectView(game, cards_db)
    await ctx.send(embed=pack_view._build_embed(), view=pack_view)


@bot.command(name="status")
async def cah_status(ctx: commands.Context):
    game = active_games.get(ctx.channel.id)
    if not game:
        return await ctx.send("No active game in this channel.")
    mode_str = f"Full game — first to {game.win_score}" if game.mode == GameMode.FULL else "Quick Round"
    embed = discord.Embed(title="📊 Game Status", color=C.BLUE)
    embed.add_field(name="Mode", value=mode_str, inline=True)
    embed.add_field(name="Round", value=str(game.round_number) or "—", inline=True)
    embed.add_field(name="Phase", value=game.phase.name.title(), inline=True)
    if game.czar:
        embed.add_field(name="🎩 Czar", value=game.czar.name, inline=True)
    embed.add_field(name="Players", value=str(len(game.players)), inline=True)
    if game.black_card and game.phase in (Phase.PLAYING, Phase.JUDGING):
        embed.add_field(name="⬛ Black Card", value=game.black_card["text"], inline=False)
    if game.phase == Phase.PLAYING:
        done = submitted_names(game)
        waiting = [game.players[pid].name for pid in game.players
                   if pid != game.czar_id and pid not in game.submissions]
        embed.add_field(name="✅ Submitted", value=", ".join(done) or "None", inline=True)
        embed.add_field(name="⏳ Waiting", value=", ".join(waiting) or "Nobody!", inline=True)
    embed.add_field(name="Scoreboard", value=fmt_scores(game.players), inline=False)
    await ctx.send(embed=embed)


@bot.command(name="skip")
async def cah_skip(ctx: commands.Context):
    game = active_games.get(ctx.channel.id)
    if not game:
        return await ctx.send("No active game.")
    if ctx.author.id != game.host.id:
        return await ctx.send("Only the host can skip.")
    if game.phase not in (Phase.PLAYING, Phase.JUDGING):
        return await ctx.send("Nothing to skip.")
    old_czar = game.czar.name if game.czar else "Unknown"
    for pid, cards in game.submissions.items():
        if pid in game.players:
            game.players[pid].hand.extend(cards)
    game.submissions.clear()
    for pid in game.players:
        game.cancel_pending(pid)
    if game.black_card:
        game.deck.discard_black(game.black_card)
    if game.round_view:
        game.round_view.stop()
    game.advance_czar()
    await ctx.send(f"⏭️ Skipped **{old_czar}**. New round starting...")
    await start_round(game)


@bot.command(name="remove")
async def cah_remove(ctx: commands.Context, member: discord.Member = None):
    game = active_games.get(ctx.channel.id)
    if not game:
        return await ctx.send("No active game.")
    if ctx.author.id != game.host.id:
        return await ctx.send("Only the host can remove players.")
    if not member or member.id not in game.players:
        return await ctx.send("Usage: `!cah remove @player`")
    was_czar = (member.id == game.czar_id)
    removed = game.remove_player(member.id)
    await ctx.send(f"🚪 **{removed.name}** removed from the game.")
    if len(game.players) < MIN_PLAYERS:
        await ctx.send("⚠️ Not enough players. Game over!")
        game.phase = Phase.FINISHED
        del active_games[ctx.channel.id]
        return
    if was_czar and game.phase in (Phase.PLAYING, Phase.JUDGING):
        await ctx.send("Czar was removed — restarting round...")
        for pid, cards in game.submissions.items():
            if pid in game.players:
                game.players[pid].hand.extend(cards)
        game.submissions.clear()
        if game.black_card:
            game.deck.discard_black(game.black_card)
        if game.round_view:
            game.round_view.stop()
        await start_round(game)
    elif game.phase == Phase.PLAYING and game.all_submitted():
        await begin_judging_phase(game)


@bot.command(name="leave")
async def cah_leave(ctx: commands.Context):
    game = active_games.get(ctx.channel.id)
    if not game or ctx.author.id not in game.players:
        return await ctx.send("You're not in a game here.")
    was_czar = (ctx.author.id == game.czar_id)
    game.remove_player(ctx.author.id)
    await ctx.send(f"👋 **{ctx.author.display_name}** left the game.")
    if len(game.players) < MIN_PLAYERS:
        await ctx.send("⚠️ Not enough players. Game over!")
        game.phase = Phase.FINISHED
        del active_games[ctx.channel.id]
        return
    if was_czar and game.phase in (Phase.PLAYING, Phase.JUDGING):
        await ctx.send("Czar left — restarting round...")
        for pid, cards in game.submissions.items():
            if pid in game.players:
                game.players[pid].hand.extend(cards)
        game.submissions.clear()
        if game.black_card:
            game.deck.discard_black(game.black_card)
        if game.round_view:
            game.round_view.stop()
        await start_round(game)
    elif game.phase == Phase.PLAYING and game.all_submitted():
        await begin_judging_phase(game)


@bot.command(name="end")
async def cah_end(ctx: commands.Context):
    game = active_games.get(ctx.channel.id)
    if not game:
        return await ctx.send("No active game.")
    if ctx.author.id != game.host.id:
        return await ctx.send("Only the host can end the game.")
    if game.round_view:
        game.round_view.stop()
    embed = discord.Embed(
        title="🛑 Game Ended",
        description=f"**{ctx.author.display_name}** ended the game.\n\n"
                    f"**Final Scores:**\n{fmt_scores(game.players)}",
        color=C.RED)
    await ctx.send(embed=embed)
    game.phase = Phase.FINISHED
    del active_games[ctx.channel.id]


@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MemberNotFound):
        return await ctx.send("⚠️ Couldn't find that member.")
    if isinstance(error, commands.BadArgument):
        return await ctx.send("⚠️ Invalid argument. See `!cah help`.")
    raise error


# ── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if TOKEN == "YOUR_TOKEN_HERE":
        print("=" * 60)
        print("  Set your bot token:  export DISCORD_BOT_TOKEN='...'")
        print("=" * 60)
    else:
        bot.run(TOKEN)
