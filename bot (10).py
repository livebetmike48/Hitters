import os
import logging
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

import mlb_api
import stats_hitting as sh
import storage

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
ROSTER_REFRESH_HOURS = float(os.getenv("ROSTER_REFRESH_HOURS", "6"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("hitters_bot")

intents = discord.Intents.default()


def et_date_str(offset_days: int = 0) -> str:
    et = datetime.now(timezone.utc) - timedelta(hours=4)
    et += timedelta(days=offset_days)
    return et.strftime("%Y-%m-%d")


def build_batter_embed(name: str, team: str, splits: list[dict]) -> discord.Embed:
    if not splits:
        return discord.Embed(title=name, description="No game log found for this season yet.",
                              color=discord.Color.light_grey())

    last = splits[-1]
    last10 = sh.summarize_batting(splits, 10)
    tag = sh.hot_cold_tag(last10)

    title = f"{name} ({team})"
    if tag:
        title += f"  {tag}"

    embed = discord.Embed(
        title=title,
        description=(
            f"{last['date']} vs {last['opponent']}\n"
            f"{last['hits']}-for-{last['ab']}, {last['hr']} HR, {last['rbi']} RBI, {last['bb']} BB, {last['so']} K"
        ),
        color=discord.Color.blue(),
    )

    streaks = sh.get_active_streaks(splits)
    notable = sh.notable_streak_labels(streaks)
    if notable:
        embed.add_field(name="Active streaks", value="\n".join(notable), inline=False)

    for n, label in ((5, "Last 5"), (10, "Last 10"), (20, "Last 20")):
        summary = sh.summarize_batting(splits, n)
        if summary:
            embed.add_field(
                name=label,
                value=(
                    f"AVG **{summary['avg']}** / OBP {summary['obp']} / SLG {summary['slg']} / OPS {summary['ops']}\n"
                    f"{summary['hr']} HR, {summary['rbi']} RBI over {summary['count']} games"
                ),
                inline=False,
            )

    season = sh.summarize_batting(splits, len(splits))
    if season:
        embed.add_field(
            name="Season",
            value=(
                f"AVG **{season['avg']}** / OBP {season['obp']} / SLG {season['slg']} / OPS {season['ops']}\n"
                f"{season['hr']} HR, {season['rbi']} RBI over {season['count']} games"
            ),
            inline=False,
        )

    embed.set_footer(text="Data: MLB Stats API")
    return embed


class HittersBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.teams: list[dict] = []
        self.player_directory: list[dict] = []  # [{"id":, "name":, "team":}]

    async def setup_hook(self):
        storage.init_db()
        try:
            self.teams = mlb_api.get_all_teams()
        except Exception as e:
            log.error("Failed to fetch teams at startup: %s", e)
            self.teams = []
        await self.refresh_player_directory()

        batter_cmd = app_commands.Command(
            name="batter",
            description="Recent stats, streaks, and hot/cold status for any hitter",
            callback=self._batter_callback,
        )
        self.tree.add_command(batter_cmd)
        batter_cmd.autocomplete("name")(self._name_autocomplete)

        hot_cmd = app_commands.Command(
            name="hothitters",
            description="League-wide scan: who's hot right now (last 10 games). Takes a few minutes.",
            callback=self._hothitters_callback,
        )
        self.tree.add_command(hot_cmd)

        cold_cmd = app_commands.Command(
            name="coldhitters",
            description="League-wide scan: who's cold right now (last 10 games). Takes a few minutes.",
            callback=self._coldhitters_callback,
        )
        self.tree.add_command(cold_cmd)

        streaks_cmd = app_commands.Command(
            name="streaks",
            description="League-wide scan: active hit/walk/HR streaks. Takes a few minutes.",
            callback=self._streaks_callback,
        )
        self.tree.add_command(streaks_cmd)

        setchannel_cmd = app_commands.Command(
            name="setchannel",
            description="Set this channel for this bot's output",
            callback=self._setchannel_callback,
        )
        self.tree.add_command(setchannel_cmd)

        try:
            synced = await self.tree.sync()
            log.info("Synced %d slash commands", len(synced))
        except Exception as e:
            log.error("Slash command sync failed: %s", e)

    async def refresh_player_directory(self):
        directory = []
        for team in self.teams:
            try:
                hitters = mlb_api.get_active_roster_hitters(team["id"])
            except Exception as e:
                log.error("Failed to fetch roster for team %s: %s", team["id"], e)
                continue
            for p in hitters:
                directory.append({"id": p["id"], "name": p["name"], "team": team["abbreviation"]})
        self.player_directory = directory
        log.info("Player directory refreshed: %d hitters", len(directory))

    async def _name_autocomplete(self, interaction: discord.Interaction, current: str):
        current_lower = current.lower()
        matches = [p for p in self.player_directory if current_lower in p["name"].lower()][:25]
        return [app_commands.Choice(name=f"{p['name']} ({p['team']})", value=str(p["id"])) for p in matches]

    def _resolve_player(self, name: str):
        if name.isdigit():
            pid = int(name)
            match = next((p for p in self.player_directory if p["id"] == pid), None)
            return (pid, match) if match else (pid, None)
        match = next((p for p in self.player_directory if name.lower() in p["name"].lower()), None)
        return (match["id"], match) if match else (None, None)

    async def _batter_callback(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        person_id, match = self._resolve_player(name)
        if person_id is None:
            await interaction.followup.send(f"Couldn't find a hitter matching '{name}'.")
            return
        try:
            splits = mlb_api.get_batting_game_log(person_id)
        except Exception as e:
            await interaction.followup.send(f"Couldn't reach the MLB API right now: {e}")
            return
        display_name = match["name"] if match else name
        team = match["team"] if match else "?"
        await interaction.followup.send(embed=build_batter_embed(display_name, team, splits))

    async def _scan_all_hitters(self, interaction: discord.Interaction):
        """Shared scan used by /hothitters, /coldhitters, /streaks -- one pass over every
        active roster hitter's game log, since all three need the same underlying data."""
        await interaction.followup.send(
            f"Scanning {len(self.player_directory)} active hitters league-wide, this'll take a few minutes..."
        )
        results = []
        for p in self.player_directory:
            try:
                splits = mlb_api.get_batting_game_log(p["id"])
            except Exception as e:
                log.error("Batting log lookup failed for %s: %s", p["name"], e)
                continue
            if not splits:
                continue
            last10 = sh.summarize_batting(splits, 10)
            tag = sh.hot_cold_tag(last10)
            streaks = sh.get_active_streaks(splits)
            notable = sh.notable_streak_labels(streaks)
            results.append({"player": p, "last10": last10, "tag": tag, "notable": notable})
        return results

    async def _hothitters_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        results = await self._scan_all_hitters(interaction)
        lines = [
            f"**{r['player']['name']}** ({r['player']['team']}) — {r['last10']['ops']} OPS last {r['last10']['count']} games\n"
            for r in results if r["tag"] == "🔥 Hot"
        ]
        await self._send_chunked(interaction, "__**🔥 Hot Hitters (last 10 games)**__\n\n", lines)

    async def _coldhitters_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        results = await self._scan_all_hitters(interaction)
        lines = [
            f"**{r['player']['name']}** ({r['player']['team']}) — {r['last10']['ops']} OPS last {r['last10']['count']} games\n"
            for r in results if r["tag"] == "🥶 Cold"
        ]
        await self._send_chunked(interaction, "__**🥶 Cold Hitters (last 10 games)**__\n\n", lines)

    async def _streaks_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        results = await self._scan_all_hitters(interaction)
        lines = []
        for r in results:
            if not r["notable"]:
                continue
            lines.append(f"**{r['player']['name']}** ({r['player']['team']}): {', '.join(r['notable'])}\n")
        await self._send_chunked(interaction, "__**Active Notable Streaks**__\n\n", lines)

    async def _send_chunked(self, interaction: discord.Interaction, header: str, lines: list[str], limit: int = 1900):
        if not lines:
            await interaction.channel.send(header + "Nobody qualifies right now.")
            return
        chunk = header
        for line in lines:
            if len(chunk) + len(line) > limit:
                await interaction.channel.send(chunk)
                chunk = ""
            chunk += line
        if chunk.strip():
            await interaction.channel.send(chunk)

    async def _setchannel_callback(self, interaction: discord.Interaction):
        storage.set_config("announce_channel_id", str(interaction.channel_id))
        await interaction.response.send_message(f"✅ Set to post in {interaction.channel.mention}.")

    async def on_ready(self):
        log.info("Logged in as %s", self.user)
        if not refresh_directory_loop.is_running():
            refresh_directory_loop.start(self)


client = HittersBot()


@tasks.loop(hours=ROSTER_REFRESH_HOURS)
async def refresh_directory_loop(bot: HittersBot):
    await bot.refresh_player_directory()


@refresh_directory_loop.before_loop
async def before_refresh():
    await client.wait_until_ready()


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Set DISCORD_TOKEN in your .env file (see .env.example).")
    client.run(TOKEN)
