"""
Cards Against Humanity — Discord Bot
=====================================
A fully-featured CAH game bot supporting ad-hoc rounds and full scored games.

Setup:
  1. pip install discord.py
  2. Set your bot token in .env or pass it directly
  3. python bot.py

Commands are prefixed with !cah (configurable below).
"""

import discord
from discord.ext import commands
import json
import random
import asyncio
import os
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

# ── Configuration ────────────────────────────────────────────────────────────

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "YOUR_TOKEN_HERE")
COMMAND_PREFIX = "!cah "
CARDS_FILE = Path(__file__).parent / "cards.json"
HAND_SIZE = 10
MIN_PLAYERS = 3  # minimum players to start a round
DEFAULT_WIN_SCORE = 7
CZAR_PICK_EMOJI = "🃏"
SUBMIT_TIMEOUT = 180   # seconds for players to submit cards
JUDGE_TIMEOUT = 180    # seconds for czar to pick

# ── Card Database ────────────────────────────────────────────────────────────

class CardDB:
    """Loads and manages the card pools. Reshuffles discards when deck runs out."""

    def __init__(self, path: str | Path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._all_white: list[str] = list(data["white"])
        self._all_black: list[dict] = list(data["black"])
        self.reset()

    # ── public api ──

    def reset(self):
        """Shuffle fresh copies of both decks."""
        self.white_draw = list(self._all_white)
        self.black_draw = list(self._all_black)
        self.white_discard: list[str] = []
        self.black_discard: list[dict] = []
        random.shuffle(self.white_draw)
        random.shuffle(self.black_draw)

    def draw_white(self, n: int = 1) -> list[str]:
        cards = []
        for _ in range(n):
            if not self.white_draw:
                if not self.white_discard:
                    raise RuntimeError("No white cards remaining at all!")
                self.white_draw = self.white_discard
                self.white_discard = []
                random.shuffle(self.white_draw)
            cards.append(self.white_draw.pop())
        return cards

    def draw_black(self) -> dict:
        if not self.black_draw:
            if not self.black_discard:
                raise RuntimeError("No black cards remaining at all!")
            self.black_draw = self.black_discard
            self.black_discard = []
            random.shuffle(self.black_draw)
        return self.black_draw.pop()

    def discard_white(self, cards: list[str]):
        self.white_discard.extend(cards)

    def discard_black(self, card: dict):
        self.black_discard.append(card)

    @property
    def total_white(self) -> int:
        return len(self._all_white)

    @property
    def total_black(self) -> int:
        return len(self._all_black)


# ── Game State ───────────────────────────────────────────────────────────────

class Phase(Enum):
    LOBBY = auto()      # waiting for players to join
    PLAYING = auto()    # players submitting white cards
    JUDGING = auto()    # card czar picking a winner
    FINISHED = auto()   # game over

class GameMode(Enum):
    ADHOC = auto()      # single round, no score tracking (still tracks for fun)
    FULL = auto()       # play to a target score

@dataclass
class Player:
    member: discord.Member
    hand: list[str] = field(default_factory=list)
    score: int = 0

    @property
    def name(self) -> str:
        return self.member.display_name

    @property
    def id(self) -> int:
        return self.member.id


class Game:
    """
    Represents one game session in a channel.
    """

    def __init__(self, channel: discord.TextChannel, host: discord.Member,
                 mode: GameMode, win_score: int, cards: CardDB):
        self.channel = channel
        self.host = host
        self.mode = mode
        self.win_score = win_score
        self.cards = cards
        self.cards.reset()

        self.phase = Phase.LOBBY
        self.players: dict[int, Player] = {}        # member_id -> Player
        self.czar_order: list[int] = []              # rotating list of player ids
        self.czar_index: int = 0
        self.round_number: int = 0

        # current round state
        self.black_card: Optional[dict] = None
        self.submissions: dict[int, list[str]] = {}  # player_id -> played white cards
        self.submission_order: list[int] = []         # randomised order for display
        self.round_message: Optional[discord.Message] = None

    # ── Player management ──

    def add_player(self, member: discord.Member) -> bool:
        if member.id in self.players:
            return False
        p = Player(member=member)
        self.players[member.id] = p
        self.czar_order.append(member.id)
        return True

    def remove_player(self, member_id: int) -> Optional[Player]:
        p = self.players.pop(member_id, None)
        if p:
            self.cards.discard_white(p.hand)
            if member_id in self.czar_order:
                idx = self.czar_order.index(member_id)
                self.czar_order.remove(member_id)
                # adjust czar_index if needed
                if self.czar_index >= len(self.czar_order) and self.czar_order:
                    self.czar_index = 0
            # remove their submission if any
            if member_id in self.submissions:
                self.cards.discard_white(self.submissions.pop(member_id))
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

    # ── Round lifecycle ──

    def start_round(self) -> dict:
        """Begin a new round. Returns the black card."""
        self.round_number += 1
        self.phase = Phase.PLAYING
        self.submissions.clear()
        self.submission_order.clear()

        # draw black card
        self.black_card = self.cards.draw_black()

        # deal up to HAND_SIZE for each non-czar player
        for pid, player in self.players.items():
            deficit = HAND_SIZE - len(player.hand)
            if deficit > 0:
                player.hand.extend(self.cards.draw_white(deficit))

        return self.black_card

    def submit_cards(self, player_id: int, indices: list[int]) -> list[str]:
        """
        Player submits card(s) by index (1-based).
        Returns the played cards. Raises ValueError on bad input.
        """
        player = self.players[player_id]
        pick = self.black_card["pick"]

        if len(indices) != pick:
            raise ValueError(f"You must play exactly **{pick}** card(s). You played {len(indices)}.")

        # validate indices
        for i in indices:
            if i < 1 or i > len(player.hand):
                raise ValueError(f"Invalid card number **{i}**. Your hand has {len(player.hand)} cards.")

        # check for duplicates
        if len(set(indices)) != len(indices):
            raise ValueError("You can't play the same card twice.")

        # pull cards out (sort descending so indices don't shift)
        played = []
        for i in sorted(indices, reverse=True):
            played.insert(0, player.hand.pop(i - 1))

        self.submissions[player_id] = played
        return played

    def all_submitted(self) -> bool:
        """Check if all non-czar players have submitted."""
        expected = {pid for pid in self.players if pid != self.czar_id}
        return expected == set(self.submissions.keys())

    def begin_judging(self) -> list[tuple[int, list[str]]]:
        """
        Transition to judging phase. Returns shuffled (player_id, cards) pairs.
        The display order is randomised so the czar can't tell who played what.
        """
        self.phase = Phase.JUDGING
        entries = list(self.submissions.items())
        random.shuffle(entries)
        self.submission_order = [pid for pid, _ in entries]
        return entries

    def pick_winner(self, choice: int) -> Player:
        """
        Czar picks a winner by display number (1-based).
        Returns the winning Player.
        """
        if choice < 1 or choice > len(self.submission_order):
            raise ValueError(f"Pick a number between 1 and {len(self.submission_order)}.")
        winner_id = self.submission_order[choice - 1]
        winner = self.players[winner_id]
        winner.score += 1

        # discard played cards and the black card
        for cards in self.submissions.values():
            self.cards.discard_white(cards)
        self.cards.discard_black(self.black_card)

        return winner

    def advance_czar(self):
        """Move to next czar."""
        self.czar_index = (self.czar_index + 1) % len(self.czar_order)

    def check_game_over(self) -> Optional[Player]:
        """In FULL mode, check if anyone reached the win score."""
        if self.mode == GameMode.ADHOC:
            return None
        for p in self.players.values():
            if p.score >= self.win_score:
                return p
        return None


# ── Formatting helpers ───────────────────────────────────────────────────────

def format_black_card(card: dict) -> str:
    text = card["text"]
    pick = card["pick"]
    formatted = text.replace("_", "▂▂▂▂▂▂")
    label = f"  *(Pick {pick})*" if pick > 1 else ""
    return f"## 🟫 {formatted}{label}"


def format_hand(hand: list[str]) -> str:
    lines = []
    for i, card in enumerate(hand, 1):
        lines.append(f"`{i:>2}.` {card}")
    return "\n".join(lines)


def format_submissions(entries: list[tuple[int, list[str]]]) -> str:
    lines = []
    for i, (_, cards) in enumerate(entries, 1):
        combined = " **|** ".join(cards)
        lines.append(f"**{i}.** {combined}")
    return "\n".join(lines)


def format_scoreboard(players: dict[int, Player]) -> str:
    sorted_players = sorted(players.values(), key=lambda p: p.score, reverse=True)
    lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, p in enumerate(sorted_players):
        medal = medals[i] if i < len(medals) else "▪️"
        lines.append(f"{medal} **{p.name}** — {p.score} point{'s' if p.score != 1 else ''}")
    return "\n".join(lines)


# ── Discord Bot ──────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents,
                   help_command=None)

# channel_id -> Game
active_games: dict[int, Game] = {}


# ── Helper to send hand via DM ──

async def send_hand(player: Player, black_card: Optional[dict] = None):
    """DM the player their current hand."""
    try:
        embed = discord.Embed(title="🃏 Your Hand", color=0xffffff)
        if black_card:
            embed.description = f"**Black card:** {black_card['text'].replace('_', '▂▂▂')}\n*(Pick {black_card['pick']})*\n\n{format_hand(player.hand)}"
        else:
            embed.description = format_hand(player.hand)
        embed.set_footer(text="Play cards in the game channel with: !cah play <number(s)>")
        await player.member.send(embed=embed)
    except discord.Forbidden:
        pass  # can't DM this user


# ── Events ───────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"   Loaded {cards_db.total_white} white cards, {cards_db.total_black} black cards")
    await bot.change_presence(activity=discord.Game(name="Cards Against Humanity | !cah help"))


# ── Commands ─────────────────────────────────────────────────────────────────

@bot.command(name="help")
async def cah_help(ctx: commands.Context):
    embed = discord.Embed(
        title="🃏 Cards Against Humanity — Commands",
        color=0x1a1a1a,
        description="A horrible card game for horrible people."
    )
    embed.add_field(name="🎮 Starting Games", inline=False, value=(
        "**`!cah start [score]`** — Start a full game (default: first to 7)\n"
        "**`!cah quickround`** — Play a single ad-hoc round\n"
        "**`!cah join`** — Join the current game lobby\n"
        "**`!cah begin`** — Host begins the game after enough players join"
    ))
    embed.add_field(name="🎴 Playing", inline=False, value=(
        "**`!cah play <#> [#]`** — Play white card(s) by number from your hand\n"
        "**`!cah hand`** — View your hand (sent via DM)\n"
        "**`!cah pick <#>`** — *(Czar only)* Pick the winning submission"
    ))
    embed.add_field(name="📊 Info & Management", inline=False, value=(
        "**`!cah status`** — Show current game status & scores\n"
        "**`!cah skip`** — *(Host)* Skip the current czar's turn\n"
        "**`!cah remove @player`** — *(Host)* Remove a player\n"
        "**`!cah end`** — *(Host)* End the current game\n"
        "**`!cah cards`** — Show card database stats"
    ))
    embed.set_footer(text="Minimum 3 players to start. Cards are dealt via DM — make sure DMs are open!")
    await ctx.send(embed=embed)


@bot.command(name="cards")
async def cah_cards(ctx: commands.Context):
    embed = discord.Embed(title="📦 Card Database", color=0x333333)
    embed.add_field(name="⬜ White Cards", value=str(cards_db.total_white))
    embed.add_field(name="⬛ Black Cards", value=str(cards_db.total_black))
    embed.add_field(name="File", value=f"`{CARDS_FILE.name}`", inline=False)
    embed.set_footer(text="Edit cards.json to add your own cards!")
    await ctx.send(embed=embed)


@bot.command(name="start")
async def cah_start(ctx: commands.Context, score: int = DEFAULT_WIN_SCORE):
    """Start a full game to a target score."""
    if ctx.channel.id in active_games:
        return await ctx.send("⚠️ A game is already running in this channel. Use `!cah end` first.")

    if score < 1 or score > 50:
        return await ctx.send("⚠️ Score must be between 1 and 50.")

    game = Game(ctx.channel, ctx.author, GameMode.FULL, score, cards_db)
    game.add_player(ctx.author)
    active_games[ctx.channel.id] = game

    embed = discord.Embed(
        title="🃏 Cards Against Humanity",
        description=f"**{ctx.author.display_name}** is starting a game!\n\n"
                    f"🏆 **First to {score} points wins.**\n\n"
                    f"Type **`!cah join`** to join!\n"
                    f"The host will type **`!cah begin`** when everyone is in.",
        color=0x1a1a1a
    )
    embed.add_field(name="Players", value=f"1. {ctx.author.display_name}")
    embed.set_footer(text=f"Minimum {MIN_PLAYERS} players needed")
    await ctx.send(embed=embed)


@bot.command(name="quickround")
async def cah_quickround(ctx: commands.Context):
    """Start a single ad-hoc round."""
    if ctx.channel.id in active_games:
        return await ctx.send("⚠️ A game is already running in this channel. Use `!cah end` first.")

    game = Game(ctx.channel, ctx.author, GameMode.ADHOC, 1, cards_db)
    game.add_player(ctx.author)
    active_games[ctx.channel.id] = game

    embed = discord.Embed(
        title="🃏 Quick Round — Cards Against Humanity",
        description=f"**{ctx.author.display_name}** is starting a quick round!\n\n"
                    f"Type **`!cah join`** to play!\n"
                    f"The host will type **`!cah begin`** when everyone is in.",
        color=0x444444
    )
    embed.add_field(name="Players", value=f"1. {ctx.author.display_name}")
    embed.set_footer(text=f"Minimum {MIN_PLAYERS} players needed")
    await ctx.send(embed=embed)


@bot.command(name="join")
async def cah_join(ctx: commands.Context):
    game = active_games.get(ctx.channel.id)
    if not game:
        return await ctx.send("No game in this channel. Start one with `!cah start` or `!cah quickround`.")

    if game.phase != Phase.LOBBY:
        return await ctx.send("⚠️ The game has already started. Wait for the next game!")

    if game.add_player(ctx.author):
        player_list = "\n".join(f"{i}. {p.name}" for i, p in enumerate(game.players.values(), 1))
        embed = discord.Embed(
            title="✅ Player Joined!",
            description=f"**{ctx.author.display_name}** is in!\n\n**Players ({len(game.players)}):**\n{player_list}",
            color=0x2ecc71
        )
        if len(game.players) >= MIN_PLAYERS:
            embed.set_footer(text="Enough players! Host can type !cah begin to start.")
        else:
            embed.set_footer(text=f"Need {MIN_PLAYERS - len(game.players)} more player(s)")
        await ctx.send(embed=embed)
    else:
        await ctx.send("You're already in the game!")


@bot.command(name="begin")
async def cah_begin(ctx: commands.Context):
    game = active_games.get(ctx.channel.id)
    if not game:
        return await ctx.send("No game in this channel.")
    if ctx.author.id != game.host.id:
        return await ctx.send("Only the host can start the game.")
    if game.phase != Phase.LOBBY:
        return await ctx.send("The game has already started.")
    if len(game.players) < MIN_PLAYERS:
        return await ctx.send(f"⚠️ Need at least **{MIN_PLAYERS}** players. Currently: {len(game.players)}")

    # Randomise czar order
    random.shuffle(game.czar_order)
    await ctx.send("**Let's go!** 🎉 Shuffling cards and dealing hands...")
    await start_round(game)


@bot.command(name="hand")
async def cah_hand(ctx: commands.Context):
    game = active_games.get(ctx.channel.id)
    if not game or ctx.author.id not in game.players:
        return await ctx.send("You're not in an active game here.")
    player = game.players[ctx.author.id]
    await send_hand(player, game.black_card)
    await ctx.message.add_reaction("📬")


@bot.command(name="play")
async def cah_play(ctx: commands.Context, *card_nums: int):
    game = active_games.get(ctx.channel.id)
    if not game:
        return await ctx.send("No active game in this channel.")
    if ctx.author.id not in game.players:
        return await ctx.send("You're not in this game.")
    if game.phase != Phase.PLAYING:
        return await ctx.send("It's not time to play cards right now.")
    if ctx.author.id == game.czar_id:
        return await ctx.send("You're the **Card Czar** this round — you don't play cards, you judge!")
    if ctx.author.id in game.submissions:
        return await ctx.send("You've already submitted this round!")

    if not card_nums:
        pick = game.black_card["pick"]
        return await ctx.send(f"Usage: `!cah play <card#>` — pick **{pick}** card(s) from your hand.")

    try:
        played = game.submit_cards(ctx.author.id, list(card_nums))
    except ValueError as e:
        return await ctx.send(f"⚠️ {e}")

    # Confirm via reaction
    await ctx.message.add_reaction("✅")

    # Delete the message to keep cards hidden (best-effort)
    try:
        await ctx.message.delete(delay=1)
    except (discord.Forbidden, discord.NotFound):
        pass

    # notify the player privately
    try:
        await ctx.author.send(f"✅ You played: **{'** | **'.join(played)}**")
    except discord.Forbidden:
        pass

    # check if all players submitted
    if game.all_submitted():
        await begin_judging_phase(game)
    else:
        waiting_on = [game.players[pid].name for pid in game.players
                      if pid != game.czar_id and pid not in game.submissions]
        await game.channel.send(f"📥 A card has been submitted! Waiting on: {', '.join(waiting_on)}")


@bot.command(name="pick")
async def cah_pick(ctx: commands.Context, choice: int = 0):
    game = active_games.get(ctx.channel.id)
    if not game:
        return await ctx.send("No active game in this channel.")
    if game.phase != Phase.JUDGING:
        return await ctx.send("It's not judging time right now.")
    if ctx.author.id != game.czar_id:
        return await ctx.send("Only the **Card Czar** can pick the winner!")

    if choice == 0:
        return await ctx.send("Usage: `!cah pick <number>` — pick the winning submission.")

    try:
        winner = game.pick_winner(choice)
    except ValueError as e:
        return await ctx.send(f"⚠️ {e}")

    # announce winner
    winning_cards = game.submissions[winner.id]
    embed = discord.Embed(
        title="🏆 Winner!",
        description=f"**{winner.name}** wins this round!\n\n"
                    f"**Winning card(s):** {' | '.join(winning_cards)}\n\n"
                    f"**{winner.name}** now has **{winner.score}** point(s).",
        color=0xf1c40f
    )
    await ctx.send(embed=embed)

    # check game over
    game_winner = game.check_game_over()
    if game_winner:
        game.phase = Phase.FINISHED
        embed = discord.Embed(
            title="🎉🎉🎉 GAME OVER 🎉🎉🎉",
            description=f"**{game_winner.name}** wins the game with **{game_winner.score}** points!\n\n"
                        f"**Final Scores:**\n{format_scoreboard(game.players)}",
            color=0xe74c3c
        )
        await ctx.send(embed=embed)
        del active_games[ctx.channel.id]
        return

    # ad-hoc mode: one round only
    if game.mode == GameMode.ADHOC:
        embed = discord.Embed(
            title="Quick Round Complete!",
            description=f"Thanks for playing!\n\n**Scores:**\n{format_scoreboard(game.players)}",
            color=0x3498db
        )
        await ctx.send(embed=embed)
        game.phase = Phase.FINISHED
        del active_games[ctx.channel.id]
        return

    # next round
    game.advance_czar()
    await asyncio.sleep(3)
    await start_round(game)


@bot.command(name="status")
async def cah_status(ctx: commands.Context):
    game = active_games.get(ctx.channel.id)
    if not game:
        return await ctx.send("No active game in this channel.")

    mode_str = f"Full game — first to {game.win_score}" if game.mode == GameMode.FULL else "Quick Round"

    embed = discord.Embed(title="📊 Game Status", color=0x3498db)
    embed.add_field(name="Mode", value=mode_str, inline=True)
    embed.add_field(name="Round", value=str(game.round_number), inline=True)
    embed.add_field(name="Phase", value=game.phase.name.title(), inline=True)

    if game.czar:
        embed.add_field(name="Card Czar", value=game.czar.name, inline=True)

    embed.add_field(name="Players", value=str(len(game.players)), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer

    if game.black_card and game.phase in (Phase.PLAYING, Phase.JUDGING):
        embed.add_field(name="Black Card", value=game.black_card["text"], inline=False)

    if game.phase == Phase.PLAYING:
        waiting = [game.players[pid].name for pid in game.players
                   if pid != game.czar_id and pid not in game.submissions]
        submitted = [game.players[pid].name for pid in game.submissions]
        embed.add_field(name="✅ Submitted", value=", ".join(submitted) or "None yet", inline=False)
        embed.add_field(name="⏳ Waiting on", value=", ".join(waiting) or "Nobody!", inline=False)

    embed.add_field(name="Scoreboard", value=format_scoreboard(game.players), inline=False)
    await ctx.send(embed=embed)


@bot.command(name="remove")
async def cah_remove(ctx: commands.Context, member: discord.Member = None):
    game = active_games.get(ctx.channel.id)
    if not game:
        return await ctx.send("No active game in this channel.")
    if ctx.author.id != game.host.id:
        return await ctx.send("Only the host can remove players.")
    if not member:
        return await ctx.send("Usage: `!cah remove @player`")
    if member.id not in game.players:
        return await ctx.send("That player isn't in the game.")

    was_czar = (member.id == game.czar_id)
    removed = game.remove_player(member.id)
    await ctx.send(f"🚪 **{removed.name}** has been removed from the game.")

    # if we're below minimum players, end
    if len(game.players) < MIN_PLAYERS:
        await ctx.send("⚠️ Not enough players remaining. Game over!")
        game.phase = Phase.FINISHED
        del active_games[ctx.channel.id]
        return

    # if the czar was removed mid-round, restart the round
    if was_czar and game.phase in (Phase.PLAYING, Phase.JUDGING):
        await ctx.send("The Card Czar was removed. Starting a new round...")
        # return played cards to hands
        for pid, cards in game.submissions.items():
            if pid in game.players:
                game.players[pid].hand.extend(cards)
        game.submissions.clear()
        if game.black_card:
            game.cards.discard_black(game.black_card)
        await start_round(game)

    # if everyone submitted after a removal, trigger judging
    elif game.phase == Phase.PLAYING and game.all_submitted():
        await begin_judging_phase(game)


@bot.command(name="skip")
async def cah_skip(ctx: commands.Context):
    """Host can skip the current czar if they're AFK."""
    game = active_games.get(ctx.channel.id)
    if not game:
        return await ctx.send("No active game in this channel.")
    if ctx.author.id != game.host.id:
        return await ctx.send("Only the host can skip the czar.")
    if game.phase not in (Phase.PLAYING, Phase.JUDGING):
        return await ctx.send("Nothing to skip right now.")

    old_czar_name = game.czar.name if game.czar else "Unknown"

    # return played cards to players
    for pid, cards in game.submissions.items():
        if pid in game.players:
            game.players[pid].hand.extend(cards)
    game.submissions.clear()

    # discard the black card
    if game.black_card:
        game.cards.discard_black(game.black_card)

    game.advance_czar()
    await ctx.send(f"⏭️ Skipped **{old_czar_name}**'s turn as Card Czar. New round starting...")
    await start_round(game)


@bot.command(name="leave")
async def cah_leave(ctx: commands.Context):
    game = active_games.get(ctx.channel.id)
    if not game:
        return await ctx.send("No active game in this channel.")
    if ctx.author.id not in game.players:
        return await ctx.send("You're not in this game.")

    was_czar = (ctx.author.id == game.czar_id)
    game.remove_player(ctx.author.id)
    await ctx.send(f"👋 **{ctx.author.display_name}** has left the game.")

    if len(game.players) < MIN_PLAYERS:
        await ctx.send("⚠️ Not enough players remaining. Game over!")
        game.phase = Phase.FINISHED
        del active_games[ctx.channel.id]
        return

    # same czar-left logic as remove
    if was_czar and game.phase in (Phase.PLAYING, Phase.JUDGING):
        await ctx.send("The Card Czar left. Starting a new round...")
        for pid, cards in game.submissions.items():
            if pid in game.players:
                game.players[pid].hand.extend(cards)
        game.submissions.clear()
        if game.black_card:
            game.cards.discard_black(game.black_card)
        await start_round(game)
    elif game.phase == Phase.PLAYING and game.all_submitted():
        await begin_judging_phase(game)


@bot.command(name="end")
async def cah_end(ctx: commands.Context):
    game = active_games.get(ctx.channel.id)
    if not game:
        return await ctx.send("No active game in this channel.")
    if ctx.author.id != game.host.id:
        return await ctx.send("Only the host can end the game.")

    embed = discord.Embed(
        title="🛑 Game Ended",
        description=f"**{ctx.author.display_name}** ended the game.\n\n"
                    f"**Final Scores:**\n{format_scoreboard(game.players)}",
        color=0xe74c3c
    )
    await ctx.send(embed=embed)
    game.phase = Phase.FINISHED
    del active_games[ctx.channel.id]


# ── Round flow helpers ───────────────────────────────────────────────────────

async def start_round(game: Game):
    """Deal cards, show the black card, DM hands."""
    black = game.start_round()
    czar = game.czar

    embed = discord.Embed(
        title=f"Round {game.round_number}",
        description=f"{format_black_card(black)}\n\n"
                    f"🎩 **Card Czar:** {czar.name}\n\n"
                    f"Check your DMs for your hand, then play with `!cah play <#>`",
        color=0x1a1a1a
    )
    if game.mode == GameMode.FULL:
        embed.set_footer(text=f"First to {game.win_score} points wins!")
    await game.channel.send(embed=embed)

    # DM all players their hands
    for pid, player in game.players.items():
        if pid != game.czar_id:
            await send_hand(player, black)


async def begin_judging_phase(game: Game):
    """All cards in — show them and ask the czar to judge."""
    entries = game.begin_judging()

    embed = discord.Embed(
        title="⚖️ All Cards Are In!",
        description=f"**Black Card:** {game.black_card['text']}\n\n"
                    f"{format_submissions(entries)}\n\n"
                    f"🎩 **{game.czar.name}**, pick the winner with `!cah pick <#>`",
        color=0x9b59b6
    )
    await game.channel.send(embed=embed)


# ── Error handling ───────────────────────────────────────────────────────────

@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.CommandNotFound):
        return  # ignore unknown commands
    if isinstance(error, commands.MemberNotFound):
        return await ctx.send("⚠️ Couldn't find that member. Make sure to @mention them.")
    if isinstance(error, commands.BadArgument):
        return await ctx.send("⚠️ Invalid argument. Check `!cah help` for usage.")
    # raise other errors
    raise error


# ── Run ──────────────────────────────────────────────────────────────────────

cards_db = CardDB(CARDS_FILE)

if __name__ == "__main__":
    if TOKEN == "YOUR_TOKEN_HERE":
        print("=" * 60)
        print("ERROR: Set your bot token!")
        print("  Option 1: export DISCORD_BOT_TOKEN='your-token-here'")
        print("  Option 2: Edit TOKEN at the top of bot.py")
        print("=" * 60)
    else:
        bot.run(TOKEN)
