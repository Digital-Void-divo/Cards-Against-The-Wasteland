# 🃏 Cards Against Humanity — Discord Bot

A fully-featured Cards Against Humanity bot for Discord. No DMs required — everything happens in-channel using private ephemeral messages only the player can see.

## Features

- **Fully In-Channel** — No DMs needed. Players click buttons to see their hand privately via ephemeral messages.
- **Button & Dropdown UI** — Join, play cards, and judge all through interactive components.
- **Full Games** — Play to a target score (default: 7). First player to reach it wins.
- **Quick Rounds** — One-off rounds for a quick laugh.
- **Multi-Pack Support** — Select which card packs to use before each game via dropdown.
- **Sequential Pick-2** — Cards requiring multiple answers are submitted one at a time to guarantee order.
- **Hidden Czar Pick** — The Card Czar picks the winner via a private ephemeral dropdown, then the result is revealed.
- **Live Status Updates** — The round embed updates in real-time showing who has submitted.
- **Player Management** — Host can remove AFK players, skip idle Czars, or end the game.

## Setup

### 1. Create a Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application** → give it a name → **Create**
3. Go to **Bot** → **Add Bot**
4. Enable these **Privileged Gateway Intents**:
   - ✅ Message Content Intent
   - ✅ Server Members Intent
5. Copy the **Bot Token**

### 2. Invite the Bot

Go to **OAuth2 → URL Generator**:
- **Scopes:** `bot`
- **Bot Permissions:** `Send Messages`, `Manage Messages`, `Read Message History`, `Add Reactions`

Open the generated URL to invite the bot.

### 3. Install & Run

```bash
pip install discord.py
export DISCORD_BOT_TOKEN="your-token-here"
python bot.py
```

## How It Works

```
1.  !cah start 7              →  Lobby opens with Join/Begin buttons
2.  Players click Join          →  Player list updates live
3.  Host clicks Begin           →  Pack selection dropdown appears
4.  Host picks packs & confirms →  Round 1 starts
5.  Black card shown with       →  "Play Card(s)" and "View Hand" buttons
    @Czar mention
6.  Players click Play Card(s)  →  They see their hand PRIVATELY (ephemeral)
7.  Select from dropdown        →  Card submitted (only they see confirmation)
8.  Round embed updates live    →  Shows ✅ submitted / ⏳ waiting
9.  All cards in                →  Submissions shown, Czar gets "Pick Winner" button
10. Czar clicks Pick Winner     →  PRIVATE dropdown (ephemeral) to choose
11. Winner revealed to all!     →  Score updated, next round auto-starts
```

## Commands

| Command | Description |
|---|---|
| `!cah start [score]` | Start a full game (default: first to 7) |
| `!cah quickround` | Start a single round |
| `!cah status` | Show scores, round info, who's submitted |
| `!cah skip` | *(Host)* Skip AFK Card Czar |
| `!cah remove @player` | *(Host)* Remove a player |
| `!cah leave` | Leave the game |
| `!cah end` | *(Host)* End the game |
| `!cah cards` | Show card pack stats |
| `!cah help` | Show help |

Most interactions use **buttons and dropdowns** — commands are mainly for management.

## Editing Cards

Open `cards.json`. Cards are organized into packs:

```json
{
  "packs": {
    "my_pack": {
      "name": "🎯 My Custom Pack",
      "description": "Cards I made up.",
      "white": ["A custom answer card."],
      "black": [{"text": "Why did _ cross the road?", "pick": 1}]
    }
  }
}
```

- Add new packs by adding a new key under `"packs"`
- Use `_` in black card text for blanks
- Set `"pick": 2` for cards requiring two answers
- Packs are selectable via dropdown when starting a game

## Configuration

Top of `bot.py`:

```python
COMMAND_PREFIX = "!cah "    # Command prefix
HAND_SIZE = 10              # Cards per hand
MIN_PLAYERS = 3             # Minimum to start
DEFAULT_WIN_SCORE = 7       # Default win target
```

## License

Cards Against Humanity content is used under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).
