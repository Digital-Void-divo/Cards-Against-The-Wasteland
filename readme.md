# 🃏 Cards Against Humanity — Discord Bot

A fully-featured Cards Against Humanity bot for Discord servers, supporting both quick ad-hoc rounds and full scored games.

## Features

- **Full Games** — Play to a target score (default: 7). First player to reach it wins.
- **Quick Rounds** — One-off rounds for when you just want a quick laugh.
- **Rotating Card Czar** — Automatically cycles through players each round.
- **DM-based Hands** — Cards are sent privately so nobody can see your hand.
- **Hidden Submissions** — Played cards are shuffled before the Czar sees them.
- **Editable Card Database** — All cards live in `cards.json`. Add, remove, or modify freely.
- **Player Management** — Join mid-lobby, leave anytime, host can remove AFK players or skip idle Czars.
- **Pick 2 Support** — Black cards that require multiple white cards work correctly.

## Setup

### 1. Create a Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application** → give it a name → **Create**
3. Go to **Bot** → **Add Bot**
4. Enable these **Privileged Gateway Intents**:
   - ✅ Message Content Intent
   - ✅ Server Members Intent
5. Copy the **Bot Token**

### 2. Invite the Bot to Your Server

Go to **OAuth2 → URL Generator**:
- **Scopes:** `bot`
- **Bot Permissions:** `Send Messages`, `Manage Messages`, `Read Message History`, `Add Reactions`

Open the generated URL to invite the bot.

### 3. Install & Run

```bash
# Install dependency
pip install discord.py

# Set your token
export DISCORD_BOT_TOKEN="your-token-here"

# Run the bot
python bot.py
```

## Commands

All commands use the `!cah` prefix.

### Starting Games

| Command | Description |
|---|---|
| `!cah start [score]` | Start a full game (default: first to 7 points) |
| `!cah quickround` | Start a single ad-hoc round |
| `!cah join` | Join the game lobby |
| `!cah begin` | Host starts the game once enough players join |

### Playing

| Command | Description |
|---|---|
| `!cah play <#> [#]` | Play white card(s) by number from your hand |
| `!cah hand` | Re-send your hand via DM |
| `!cah pick <#>` | *(Czar only)* Pick the winning submission |

### Management

| Command | Description |
|---|---|
| `!cah status` | Show current round, scores, and who we're waiting on |
| `!cah skip` | *(Host)* Skip an AFK Card Czar and start a new round |
| `!cah remove @player` | *(Host)* Remove a player from the game |
| `!cah leave` | Leave the game voluntarily |
| `!cah end` | *(Host)* End the game and show final scores |
| `!cah cards` | Show card database statistics |
| `!cah help` | Show the help menu |

## Game Flow

```
1.  Host runs !cah start 7     →  Game lobby opens
2.  Players run !cah join       →  Players enter lobby
3.  Host runs !cah begin        →  Round 1 starts, hands are dealt via DM
4.  Black card is shown          →  Players see the prompt
5.  Players run !cah play 3     →  Each player secretly submits cards
6.  All submissions shown        →  Shuffled and numbered anonymously
7.  Czar runs !cah pick 2       →  Czar picks the funniest answer
8.  Winner announced             →  Point awarded, next round starts
9.  Repeat until someone hits 7  →  🎉 Game over!
```

## Editing Cards

Open `cards.json` in any text editor. The structure is:

```json
{
  "metadata": { ... },
  "white": [
    "Card text here.",
    "Another white card."
  ],
  "black": [
    {"text": "Why can't I sleep at night?", "pick": 1},
    {"text": "_ + _ = _.", "pick": 2}
  ]
}
```

- **White cards** — Simple strings. These are the answer cards players hold.
- **Black cards** — Objects with `text` and `pick`. Use `_` for blanks. `pick` is how many white cards a player must submit.
- Add as many cards as you want — the bot reshuffles the discard pile when the deck runs out.

## Configuration

Edit the top of `bot.py` to adjust:

```python
COMMAND_PREFIX = "!cah "    # Change the command prefix
HAND_SIZE = 10              # Cards per player hand
MIN_PLAYERS = 3             # Minimum players to start
DEFAULT_WIN_SCORE = 7       # Default points to win
```

## License

Cards Against Humanity content is used under the [Creative Commons BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) license, as released by Cards Against Humanity LLC.
