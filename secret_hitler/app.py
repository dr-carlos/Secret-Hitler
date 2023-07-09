import asyncio
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from secret_hitler import config
from secret_hitler.game import Game, GameStates, Player


class DiscordChannelHandler(logging.Handler):
    def __init__(self, channel=None):
        logging.Handler.__init__(self)
        self._channel = channel

    def setChannel(self, channel=None):
        self._channel = channel

    def emit(self, record):
        if self._channel is not None:
            try:
                msg = self.format(record)
                if record.levelno == logging.INFO:
                    msg = f"```\n{msg}\n```"
                elif record.levelno == logging.WARNING:
                    msg = f"```fix\n{msg}\n```"
                elif record.levelno == logging.ERROR:
                    msg = f"```diff\n-{msg}\n```"
                asyncio.create_task(self._channel.send(msg))
            except Exception:
                self.handleError(record)


discordFormatter = logging.Formatter(
    "[%(asctime)s][%(levelname)s][%(name)s] %(message)s"
)

# log discord API messages to discord.log file
discordLogger = logging.getLogger("discord")
discordLogger.setLevel(logging.DEBUG)
discordHandler = logging.FileHandler(filename="discord.log", encoding="utf-8", mode="w")
discordHandler.setFormatter(discordFormatter)
discordLogger.addHandler(discordHandler)

# logger for this application
formatter = logging.Formatter("[%(asctime)s][%(levelname)s][%(name)s] %(message)s")
logger = logging.getLogger("secret_hitler")
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger.addHandler(handler)

channelFormatter = logging.Formatter("%(levelname)s -- %(message)s")
channelHandler = DiscordChannelHandler()
channelHandler.setLevel(logging.INFO)
channelHandler.setFormatter(channelFormatter)
logger.addHandler(channelHandler)

# constants for ja or nein voting
for e in config.configuration["emoji"]:
    if "ja" in e:
        JA = e
    elif "nein" in e:
        NEIN = e

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.reactions = True

c_prefix = "/sh "
client = commands.Bot(command_prefix=c_prefix, intents=intents)
client.remove_command("help")

running_games = {}


# Events
@client.event
async def on_ready():
    logger.info("We have logged in as {0.user}".format(client))
    act = discord.Game(name="with Democracy")
    await client.change_presence(status=discord.Status.online, activity=act)


@client.event
async def on_guild_available(guild):
    await setup(guild)


@client.event
async def on_reaction_add(reaction, user):
    if user.id == client.user.id:
        return

    if not reaction.is_custom_emoji():
        return

    game = get_game_with_player(user.id)
    if not game:
        return

    if game.state == GameStates.ELECTION:
        emoji = reaction.emoji

        # If we've currently voted, don't let us vote again
        if JA in emoji.name or NEIN in emoji.name:
            for msg_reaction in reaction.message.reactions:
                if user in [user async for user in msg_reaction.users()]:
                    if (
                        JA in msg_reaction.emoji.name or NEIN in msg_reaction.emoji.name
                    ) and msg_reaction.emoji.name != emoji.name:
                        await reaction.remove(user)
                        return

        vote = False
        if JA in emoji.name:
            vote = game.vote(user.id, "y")
        elif NEIN in emoji.name:
            vote = game.vote(user.id, "n")

        if not vote:
            return

        if len(game.votes) == len(game.players):
            if game.calculate_votes():
                # Start Legislative Session
                embed = discord.Embed(
                    title="New Chancellor",
                    description=client.get_user(game.chancellor.player_id).display_name
                    + " is the new chancellor. Legislative Session starts now",
                    color=discord.Color.dark_red(),
                )
                embed.set_thumbnail(
                    url=client.get_user(game.chancellor.player_id).display_avatar.url
                )
                await client.get_channel(game.channel_id).send(embed=embed)
                await start_president_legislative(game)
                return

            if game.state == GameStates.GAME_OVER:
                embed = discord.Embed(
                    title="Game over!",
                    description=game.winner
                    + f"s won the game. Use {c_prefix}restart to restart the game",
                    color=discord.Color.dark_red(),
                )
                for player in game.players:
                    embed.add_field(
                        name=client.get_user(player.player_id),
                        value=player.role,
                        inline=False,
                    )
                await client.get_channel(game.channel_id).send(embed=embed)
                return

            if game.failed_votes > 3:
                embed = discord.Embed(
                    title="Election Failed three times in a row",
                    description="The election failed three times in a row. The top policy will be revealed",
                    color=discord.Color.dark_red(),
                )
                await client.get_channel(game.channel_id).send(embed=embed)
                await sendBoard(game)
                game.failed_votes = 0
                if game.state == GameStates.NOMINATION:
                    game.set_presidnet()
                    game.nominated = None
                    await start_nomination(game)
                    return

                if game.state == GameStates.GAME_OVER:
                    embed = discord.Embed(
                        title="Game over!",
                        description=game.winner
                        + f"s won the game. Use {c_prefix}restart to restart the game.",
                        color=discord.Color.dark_red(),
                    )
                    for player in game.players:
                        embed.add_field(
                            name=client.get_user(player.player_id),
                            value=player.role,
                            inline=False,
                        )
                    await client.get_channel(game.channel_id).send(embed=embed)
                    return

                if game.state == GameStates.INVESTIGATION:
                    embed = discord.Embed(
                        title="Investigation",
                        description=f"The current president can now investigate a players party. Please use {c_prefix}investigate <playername> to do that",
                        color=discord.Color.dark_red(),
                    )
                    await client.get_channel(game.channel_id).send(embed=embed)
                    return

                if game.state == GameStates.POLICY_PEEK:
                    game.policy_peek()
                    file = discord.File(
                        "secret_hitler/img/policypeek_" + str(game.game_id) + ".png",
                        filename="president.png",
                    )
                    embed = discord.Embed(
                        title="Policy Peek",
                        description="These are the next three policies.",
                        color=discord.Color.dark_red(),
                    )
                    embed.set_image(url="attachment://president.png")
                    msg = await client.get_user(game.president.player_id).send(
                        embed=embed, file=file
                    )
                    embed = discord.Embed(
                        title="Policy Peek",
                        description="The current president sees the top three policies. Please check your Direct Message!",
                        color=discord.Color.dark_red(),
                    )
                    await client.get_channel(game.channel_id).send(embed=embed)
                    game.set_president()
                    game.state = GameStates.NOMINATION
                    await start_nomination(game)
                    return

                if game.state == GameStates.EXECUTION:
                    embed = discord.Embed(
                        title="Execution",
                        description=f"The current president can execute a player. Please use {c_prefix}execute <playername>",
                        color=discord.Color.dark_red(),
                    )
                    await client.get_channel(game.channel_id).send(embed=embed)
                    return
            else:
                embed = discord.Embed(
                    title="Election Failed",
                    description="The vote failed. After 3 failed votes the top policy will be revealed",
                    color=discord.Color.dark_red(),
                )
                embed.add_field(
                    name="Failed Votes", value=str(game.failed_votes) + "/3"
                )
            await client.get_channel(game.channel_id).send(embed=embed)
            await start_nomination(game)


@client.event
async def on_reaction_remove(reaction, user):
    if user.id == client.user.id:
        return

    if not reaction.is_custom_emoji():
        return

    if not (game := get_game_with_player(user.id)):
        return

    if game.state == GameStates.ELECTION:
        try:
            if JA in reaction.emoji.name:
                game.unvote(user.id, "y")
            elif NEIN in reaction.emoji.name:
                game.unvote(user.id, "n")
        except KeyError:
            logging.debug(f"Couldn't remove {user.id}'s vote")


# Commands
@client.command(name="setup")
@commands.has_permissions(administrator=True)
async def setup(ctx):
    await setup(ctx.guild)


@client.command(name="cleanup")
@commands.has_permissions(administrator=True)
async def cleanup(ctx):
    await cleanup(ctx.guild)


@client.command(name="rules")
async def rules(ctx):
    await printRules(ctx.message.channel)


@client.command(name="license")
async def license_command(ctx):
    await printLicense(ctx.message.channel)


@client.command(name="help")
async def help(ctx):
    await printHelp(ctx.message.channel)


@client.command(name="roletest")
async def roletest(ctx):
    file = discord.File("secret_hitler/img/hitler_role.png", filename="role.png")
    embed = discord.Embed(
        title="Hitler",
        description="Hitler is your secret role.",
        color=discord.Color.dark_red(),
    )
    embed.set_image(url="attachment://role.png")
    await ctx.send(file=file, embed=embed)

    file = discord.File("secret_hitler/img/fascist_role.png", filename="role.png")
    embed = discord.Embed(
        title="Fascist",
        description="Fascist is your secret role.",
        color=discord.Color.orange(),
    )
    embed.set_image(url="attachment://role.png")
    await ctx.send(file=file, embed=embed)

    file = discord.File("secret_hitler/img/liberal_role.png", filename="role.png")
    embed = discord.Embed(
        title="Liberal",
        description="Liberal is your secret role.",
        color=discord.Color.blue(),
    )
    embed.set_image(url="attachment://role.png")
    await ctx.send(file=file, embed=embed)


@client.command(name="startgame")
async def start_game(ctx, players: int):
    category = get_category(ctx.guild)
    if category is None:
        await ctx.send(
            f"Secret Hitler is not enabled on this server. Please execute {c_prefix}setup to enable it"
        )
        return

    is_in_game = get_game_with_player(ctx.message.author.id)
    if is_in_game:
        await ctx.send("You can't create a game, because you already joined one!")
        return

    if players > 10 or players < 5:
        await ctx.send("You have to choose between 5-10 players!")
        return

    k = 0
    for i in running_games.keys():
        k = i

    game_id = k + 1

    role = await ctx.guild.create_role(name="game_" + str(game_id) + "_member")
    admin_role = await ctx.guild.create_role(
        name="game_" + str(game_id) + "_administrator"
    )
    await ctx.message.author.add_roles(role)
    await ctx.message.author.add_roles(admin_role)

    channel = await category.create_text_channel("game_" + str(game_id))
    await channel.set_permissions(
        ctx.guild.default_role,
        overwrite=discord.PermissionOverwrite(
            read_messages=False, read_message_history=True
        ),
    )
    await channel.set_permissions(
        ctx.guild.me,
        overwrite=discord.PermissionOverwrite(
            read_messages=True,
            manage_channels=True,
            add_reactions=True,
            send_messages=True,
        ),
    )
    await channel.set_permissions(
        role, overwrite=discord.PermissionOverwrite(read_messages=True)
    )

    voice_channel = await category.create_voice_channel("game_" + str(game_id))
    await voice_channel.set_permissions(
        ctx.guild.default_role,
        overwrite=discord.PermissionOverwrite(view_channel=False),
    )
    await voice_channel.set_permissions(
        ctx.guild.me,
        overwrite=discord.PermissionOverwrite(manage_channels=True),
    )
    await voice_channel.set_permissions(
        role, overwrite=discord.PermissionOverwrite(view_channel=True)
    )

    running_games[game_id] = Game(channel.id, game_id, players, ctx.message.author.id)

    embed = discord.Embed(
        title="Starting SecretHitler...", description="Waiting for other players"
    )
    embed.add_field(name="Slots", value="1/" + str(players))
    embed.add_field(
        name="Private Game",
        value=f"This is a private game. Invite other players by using {c_prefix}invite <playername>. Ensure the player is ready to play and on the server",
        inline=False,
    )

    message = await channel.send(embed=embed)


@client.command(name="invite")
async def invite(ctx, player: commands.MemberConverter):
    game = get_game_with_player(ctx.message.author.id)
    if game is None:
        await ctx.send("You can't invite someone because you are not in a game")
        return

    is_in_game = get_game_with_player(player.id)
    if is_in_game:
        await ctx.send(
            "You can't invite this player because they've already joined a game!"
        )
        return

    role = discord.utils.get(
        ctx.guild.roles, name="game_" + str(game.get_id()) + "_member"
    )
    if not game.add_player(player.id):
        await ctx.send("This game is already full")
        return
    await player.add_roles(role)
    embed = discord.Embed(
        title="Secret Hitler",
        description="You have been added to a SecretHitler game. The round will start as soon enough players have joined",
    )
    embed.add_field(
        name="Game channel",
        value="Visit the channel #game_"
        + str(game.get_id())
        + ". The game will be processed in there. You will receive important information like your role as a Direct Message",
    )
    await player.send(embed=embed)

    if game.start_game():
        await client.get_channel(game.channel_id).send(
            "All players joined the game. Let's get it started. Ha."
        )
        await send_players_info(game)
        await sendRoles(game)
        await sendBoard(game)
        await start_nomination(game)
    else:
        embed = discord.Embed(
            title="Player joined the game",
            description="The player "
            + str(player.display_name)
            + " joined the game! Waiting for more players",
            color=discord.Color.dark_red(),
        )
        embed.add_field(
            name="Slots", value=str(len(game.players)) + "/" + str(game.max_players)
        )
        await client.get_channel(game.channel_id).send(embed=embed)


@client.command(name="stopgame")
async def stop_game(ctx, id: int):
    user = ctx.message.author
    if discord.utils.get(user.roles, name="game_" + str(id) + "_administrator") is None:
        await ctx.send("You don't have the permission to stop this game")
        return

    game = running_games[id]
    if not game:
        await ctx.send("This game does not exist")
        return
    guild = ctx.guild
    role = discord.utils.get(guild.roles, name="game_" + str(id) + "_administrator")
    if role:
        await role.delete()

    member_role = discord.utils.get(guild.roles, name="game_" + str(id) + "_member")
    if role:
        await member_role.delete()
    channel = client.get_channel(game.channel_id)
    if channel:
        await channel.delete()
    voice = discord.utils.get(guild.voice_channels, name="game_" + str(id))
    if voice:
        await voice.delete()

    running_games.pop(id)
    try:
        await ctx.send("The Game with the id: " + str(id) + " has been deleted")
    except discord.errors.NotFound:
        logger.debug("The Game with the id: " + str(id) + " has been deleted")


@client.command(name="nominate")
async def nominate(ctx, player: commands.MemberConverter):
    game = get_game_with_player(ctx.message.author.id)
    if not game:
        await ctx.send("You are not in a game")
        return

    if game.president.player_id is not ctx.message.author.id:
        await ctx.send("You are not the president")
        return

    if not game.has_player(player.id):
        await ctx.send("This player is not in the same game as you")
        return

    if game.state is not GameStates.NOMINATION:
        await ctx.message.delete()
        return

    if not game.nominate(player.id):
        await ctx.send(
            "This player could not be nominated. They were chancellor or president in the last round"
        )
        return

    await ctx.message.delete()

    next_president_id: int = (
        0 if game.president_id >= (len(game.players) - 1) else game.president_id + 1
    )
    embed = discord.Embed(
        title="Player " + player.display_name + " was nominated for chancellor",
        description="Please react to this message with Ja or Nein to vote.\nVote wisely - "
        + client.get_user(game.players[next_president_id].player_id).display_name
        + " will be President next round!",
        color=discord.Color.dark_red(),
    )

    embed.set_thumbnail(url=player.display_avatar.url)
    msg = await client.get_channel(game.channel_id).send(embed=embed)
    await msg.add_reaction(discord.utils.get(ctx.guild.emojis, name=JA))
    await msg.add_reaction(discord.utils.get(ctx.guild.emojis, name=NEIN))


@client.command(name="discard")
async def discard(ctx, card):
    game = get_game_with_player(ctx.message.author.id)
    if not game:
        await ctx.send("You are not in a game")
        return

    if (
        game.president.player_id is not ctx.message.author.id
        and game.chancellor.player_id is not ctx.message.author.id
    ):
        await ctx.send("You are not the president or the chancellor")
        return

    if (
        game.state is not GameStates.LEGISLATIVE_PRESIDENT
        and game.state is not GameStates.LEGISLATIVE_CHANCELLOR
    ):
        await ctx.send("You can't discard a policy now")
        return

    if not game.discard_policy(ctx.message.author.id, card):
        await ctx.send(
            f"Policy can't be discarded. You either don't have the permission to do it or you cant discard this policy. Use {c_prefix}discard <f/l>"
        )
        return

    await ctx.send("You successfully discarded a policy")

    if game.state == GameStates.LEGISLATIVE_CHANCELLOR:
        embed = discord.Embed(
            title="The President discarded a policy",
            description="Waiting for the chancellor to discard a policy",
            color=discord.Color.dark_red(),
        )
        await client.get_channel(game.channel_id).send(embed=embed)
        await start_chancellor_legislative(game)
        return

    await sendBoard(game)

    if game.state == GameStates.NOMINATION:
        game.set_president()
        await start_nomination(game)
        return

    if game.fascist_board == 5:
        embed = discord.Embed(
            title="Veto right",
            description=f"Five fascist policies are enacted. The chancellor can now veto an agenda. Use {c_prefix}veto to do that",
            color=discord.Color.dark_red(),
        )
        await client.get_channel(game.channel_id).send(embed=embed)

    if game.state == GameStates.GAME_OVER:
        embed = discord.Embed(
            title="Game over!",
            description=game.winner
            + f"s won the game. Use {c_prefix}restart to restart the game.",
            color=discord.Color.dark_red(),
        )
        for player in game.players:
            embed.add_field(
                name=client.get_user(player.player_id), value=player.role, inline=False
            )
        await client.get_channel(game.channel_id).send(embed=embed)
        return

    if game.state == GameStates.INVESTIGATION:
        embed = discord.Embed(
            title="Investigation",
            description=f"The current president can now investigate a players party. Please use {c_prefix}investigate <playername> to do that",
            color=discord.Color.dark_red(),
        )
        await client.get_channel(game.channel_id).send(embed=embed)
        return

    if game.state == GameStates.POLICY_PEEK:
        game.policy_peek()
        file = discord.File(
            "secret_hitler/img/policypeek_" + str(game.game_id) + ".png",
            filename="president.png",
        )
        embed = discord.Embed(
            title="Policy Peek",
            description="These are the next three policies.",
            color=discord.Color.dark_red(),
        )
        embed.set_image(url="attachment://president.png")
        msg = await client.get_user(game.president.player_id).send(
            embed=embed, file=file
        )
        embed = discord.Embed(
            title="Policy Peek",
            description="The current president sees the top three policies. Please check your Direct Message!",
            color=discord.Color.dark_red(),
        )
        await client.get_channel(game.channel_id).send(embed=embed)
        game.set_president()
        game.state = GameStates.NOMINATION
        await start_nomination(game)
        return

    if game.state == GameStates.EXECUTION:
        embed = discord.Embed(
            title="Execution",
            description=f"The current president can execute a player. Please use {c_prefix}execute <playername>",
            color=discord.Color.dark_red(),
        )
        await client.get_channel(game.channel_id).send(embed=embed)
        return

    if game.state == GameStates.SPECIAL_ELECTION:
        embed = discord.Embed(
            title="Special Election",
            description=f"The current president picks the next President. Please use {c_prefix}president <playername>",
            color=discord.Color.dark_red(),
        )
        await client.get_channel(game.channel_id).send(embed=embed)
        return


@client.command(name="president")
async def president(ctx, player: commands.UserConverter):
    game = get_game_with_player(ctx.message.author.id)
    if not game:
        await ctx.send("You are not in a game")
        return

    if game.state is not GameStates.SPECIAL_ELECTION:
        await ctx.send("You can't pick a president now")
        return

    if game.president.player_id is not ctx.message.author.id:
        await ctx.send("You are not the president")
        return

    if not game.has_player(player.id):
        await ctx.send("This player is not in the same game as you")
        return

    player = game.get_player(player.id)

    game.peeked = True

    game.prev_president_id = game.president.player_id
    game.president = player

    await start_nomination(game)


@client.command(name="investigate")
async def investigate(ctx, player: commands.UserConverter):
    game = get_game_with_player(ctx.message.author.id)
    if not game:
        await ctx.send("You are not in a game")
        return

    if game.state is not GameStates.INVESTIGATION:
        await ctx.send("You can't investigate somebodys role at the moment")
        return

    if game.president.player_id is not ctx.message.author.id:
        await ctx.send("You are not the president")
        return

    if not game.has_player(player.id):
        await ctx.send("This player is not in the same game as you")
        return

    party = game.get_player(player.id).get_party()

    if game.fascist_board == 1:
        game.investigated_one = True
    else:
        game.investigated = True

    embed = discord.Embed(
        title="Investigation",
        description="Player "
        + client.get_user(player.id).display_name
        + " is a "
        + party,
        color=discord.Color.dark_red(),
    )
    embed.set_thumbnail(url=client.get_user(player.id).display_avatar.url)

    await ctx.message.delete()

    await ctx.message.author.send(embed=embed)

    game.set_president()

    await start_nomination(game)


@client.command(name="veto")
async def veto(ctx):
    game = get_game_with_player(ctx.message.author.id)
    if not game:
        await ctx.send("You are not in a game")
        return

    if game.fascist_board < 5:
        await ctx.send("The veto right is not enabled yet")
        return

    if game.state is not GameStates.LEGISLATIVE_CHANCELLOR:
        await ctx.send("You can't veto at the moment")
        return

    if (
        game.chancellor is not None
        and game.chancellor.player_id is not ctx.message.author.id
    ):
        await ctx.send("You are not the chancellor")
        return

    game.state = GameStates.VETO

    embed = discord.Embed(
        title="Veto",
        description=f"The current chancellor requested veto for this agenda. The president needs to accept ({c_prefix}accept) or decline ({c_prefix}decline) the veto",
        color=discord.Color.dark_red(),
    )
    await client.get_channel(game.channel_id).send(embed=embed)


@client.command(name="accept")
async def accept(ctx):
    game = get_game_with_player(ctx.message.author.id)
    if not game:
        await ctx.send("You are not in a game")
        return

    if game.state is not GameStates.VETO:
        await ctx.send("You can't accept a veto at the moment")
        return

    if game.president.player_id is not ctx.message.author.id:
        await ctx.send("You are not the president")
        return

    embed = discord.Embed(
        title="Veto accepted",
        description="All three policies will be discarded",
        color=discord.Color.dark_red(),
    )
    await client.get_channel(game.channel_id).send(embed=embed)

    for i in range(len(game.policies)):
        game.discard.append(game.policies[i])
    game.policies.clear()

    game.set_president()

    await start_nomination(game)


@client.command(name="decline")
async def decline(ctx):
    game = get_game_with_player(ctx.message.author.id)
    if not game:
        await ctx.send("You are not in a game")
        return

    if game.state is not GameStates.VETO:
        await ctx.send("You can't accept a veto at the moment")
        return

    if game.president.player_id is not ctx.message.author.id:
        await ctx.send("You are not the president")
        return

    embed = discord.Embed(
        title="Veto declined",
        description="The chancellor has to discard a policy",
        color=discord.Color.dark_red(),
    )
    await client.get_channel(game.channel_id).send(embed=embed)

    game.state = GameStates.LEGISLATIVE_CHANCELLOR


@client.command(name="execute")
async def execute(ctx, player: commands.UserConverter):
    game = get_game_with_player(ctx.message.author.id)
    if not game:
        await ctx.send("You are not in a game")
        return

    if game.state is not GameStates.EXECUTION:
        await ctx.send("You can't execute somebody at the moment")
        return

    if game.president.player_id is not ctx.message.author.id:
        await ctx.send("You are not the president")
        return

    if not game.has_player(player.id):
        await ctx.send("This player is not in the same game as you")
        return

    executed = game.execute_player(player.id)
    if executed is None:
        await ctx.send("This player could not be executed")
        return

    fascists = []
    liberal = []

    for player in game.players:
        if player.get_party() == "Fascist":
            fascists.append(player)
        elif player.get_party() == "Liberal":
            liberal.append(player)

    if executed.role == "Hitler":
        game.state = GameStates.GAME_OVER
        game.winner = "Liberal"
        embed = discord.Embed(
            title="Game over!",
            description=game.winner
            + f"s won the game. Use {c_prefix}restart to restart the game.",
            color=discord.Color.dark_red(),
        )
        for player in game.players:
            embed.add_field(
                name=client.get_user(player.player_id).display_name,
                value=player.role,
                inline=False,
            )
        for player in game.dead:
            embed.add_field(
                name=client.get_user(executed.player_id).display_name,
                value=player.role,
                inline=False,
            )
        await client.get_channel(game.channel_id).send(embed=embed)
    elif len(game.players) <= 1:
        game.state = GameStates.GAME_OVER
        game.winner = game.players[0].get_party()
        embed = discord.Embed(
            title="Game over!",
            description=game.winner
            + f"s won the game. Use {c_prefix}restart to restart the game.",
            color=discord.Color.dark_red(),
        )
        for player in game.players:
            embed.add_field(
                name=client.get_user(player.player_id).display_name,
                value=player.role,
                inline=False,
            )
        for player in game.dead:
            embed.add_field(
                name=client.get_user(executed.player_id).display_name,
                value=player.role,
                inline=False,
            )
        await client.get_channel(game.channel_id).send(embed=embed)
    elif len(liberal) == 0:
        game.state = GameStates.GAME_OVER
        game.winner = game.players[0].get_party()
        embed = discord.Embed(
            title="Game over!",
            description=f"Liberals won the game. Use {c_prefix}restart to restart the game.",
            color=discord.Color.dark_red(),
        )
        await client.get_channel(game.channel_id).send(embed=embed)
    elif len(fascists) == 0:
        game.state = GameStates.GAME_OVER
        game.winner = game.players[0].get_party()
        embed = discord.Embed(
            title="Game over!",
            description=f"Fascists won the game. Use {c_prefix}restart to restart the game.",
            color=discord.Color.dark_red(),
        )
        await client.get_channel(game.channel_id).send(embed=embed)
    else:
        embed = discord.Embed(
            title="Player executed",
            description=client.get_user(executed.player_id).display_name
            + " was executed.",
        )
        embed.set_thumbnail(url=client.get_user(executed.player_id).display_avatar.url)
        await client.get_channel(game.channel_id).send(embed=embed)
        game.state = GameStates.NOMINATION
        game.set_president()
        await start_nomination(game)


@client.command(name="restart")
async def restart(ctx):
    game = get_game_with_player(ctx.message.author.id)
    if not game:
        await ctx.send("You are not in a game")
        return

    if game.state is not GameStates.GAME_OVER:
        await ctx.send("Game is not over yet")
        return

    channel = client.get_channel(game.channel_id)

    await channel.purge(limit=100)

    game.restart_game()

    if game.start_game():
        await client.get_channel(game.channel_id).send(
            "All players joined the game. Let's get it started. Ha."
        )
        await send_players_info(game)
        await sendRoles(game)
        await sendBoard(game)
        await start_nomination(game)


# Game Handling


async def start_chancellor_legislative(game: Game):
    game.chancellor_legislative()
    file = discord.File(
        "secret_hitler/img/chancellor_" + str(game.game_id) + ".png",
        filename="chancellor.png",
    )
    embed = discord.Embed(
        title="Policies",
        description=f"These are the three new policies. Use {c_prefix}discard <f/l> to discard a policy",
        color=discord.Color.dark_red(),
    )
    embed.set_image(url="attachment://chancellor.png")
    msg = await client.get_user(game.chancellor.player_id).send(embed=embed, file=file)


async def start_president_legislative(game: Game):
    game.president_legislative()
    file = discord.File(
        "secret_hitler/img/president_" + str(game.game_id) + ".png",
        filename="president.png",
    )
    embed = discord.Embed(
        title="Policies",
        description=f"These are the three new policies. Use {c_prefix}discard <f/l> to discard a policy",
        color=discord.Color.dark_red(),
    )
    embed.set_image(url="attachment://president.png")
    msg = await client.get_user(game.president.player_id).send(embed=embed, file=file)


async def cleanup(guild):
    # Removes everything created by the setup function
    channelHandler.setChannel(None)
    category = get_category(guild)
    if category is not None:
        for c in category.channels:
            logger.debug("Deleting channel: " + c.name)
            await c.delete()
            logger.debug("Deleted channel: " + c.name)
        logger.debug("Deleting category: " + category.name)
        await category.delete()
        logger.debug("Deleted category: " + category.name)

    for e in await guild.fetch_emojis():
        if e.user.id == client.user.id:
            logger.debug("Deleting emoji: " + e.name)
            await e.delete()
            logger.debug("Deleted emoji: " + e.name)

    logger.info("Completed cleanup of emojis and channels")


async def get_channel(name, category):
    # Returns the requested channel, creating it if it doesn't already exist

    c = next((c for c in category.channels if c.name == name), None)
    if c is not None:
        return c

    logger.debug("Creating channel: " + name)
    channel = await category.create_text_channel(name=name)
    logger.debug("Created channel: " + name)

    return channel


async def setup(guild):
    # Makes the guild ready to handle Games

    # create a new category for the guild channels if it doesn't exist
    category = get_category(guild)
    if category is None:
        logger.debug("Creating category: " + config.configuration["category"])
        category = await guild.create_category(name=config.configuration["category"])
        logger.debug("Created category: " + category.name)
    else:
        logger.debug("Found existing category: " + category.name)

    # Add custom emojis if they aren't already added
    emojis = dict(config.configuration["emoji"])
    for e in guild.emojis:
        if e.name in emojis:
            logger.debug("Found existing emoji: " + e.name)
            del emojis[e.name]

    for ename, efile in emojis.items():
        logger.debug("Adding custom emoji: " + ename)
        with open(efile, "rb") as image:
            f = image.read()
            b = bytearray(f)
        await guild.create_custom_emoji(name=ename, image=b)
        logger.debug("Added custom emoji: " + ename)

    logger.info("Setup completed")


async def init_channel_rules(channel):
    if channel.topic is None:
        logger.debug("Setting rules channel topic and overwrites")
        await channel.edit(
            topic="The Rules of Secret Hitler",
            overwrites={
                channel.guild.default_role: discord.PermissionOverwrite(
                    send_messages=False
                ),
                channel.guild.me: discord.PermissionOverwrite(send_messages=True),
            },
        )
        await printRules(channel)


async def init_channel_lobby(channel):
    if channel.topic is None:
        await channel.edit(
            topic="A place to hangout while waiting for your Secret Hitler game to start"
        )


async def start_nomination(game: Game):
    embed = discord.Embed(
        title="Starting election",
        description=client.get_user(game.president.player_id).display_name
        + f" is president. Please nominate your chancellor candidate! Use {c_prefix}nominate username",
        color=discord.Color.dark_red(),
    )
    embed.set_thumbnail(
        url=client.get_user(game.president.player_id).display_avatar.url
    )
    game.start_nomination()
    await client.get_channel(game.channel_id).send(embed=embed)


def get_category(guild):
    categories = guild.categories
    for category in categories:
        if category.name == config.configuration["category"]:
            return category
    return None


def get_game_with_player(player):
    for k, game in running_games.items():
        if game.has_player(player):
            return game
    return None


async def send_players_info(game: Game):
    embed = discord.Embed(
        title="Player Information",
        description="Player IDs of all players in this Game!",
        color=discord.Color.dark_red(),
    )
    for i in range(len(game.players)):
        embed.add_field(
            name="Player " + str(i + 1),
            value=str(client.get_user(game.players[i].player_id).display_name),
        )
    await client.get_channel(game.channel_id).send(embed=embed)


async def sendBoard(game: Game):
    game.printBoard()
    liberal = discord.File(game.return_path_to_liberal_board())
    fascist = discord.File(game.return_path_to_fascist_board())
    await client.get_channel(game.channel_id).send(file=liberal)
    await client.get_channel(game.channel_id).send(file=fascist)


async def sendRoles(game: Game):
    hitler = None
    fascists = []
    for player in game.players:
        if player.role is None:
            return
        if player.role == "Hitler":
            hitler = player
        elif player.role == "Fascist":
            fascists.append(player)
        elif player.role == "Liberal":
            file = discord.File(
                "secret_hitler/img/liberal_role.png", filename="role.png"
            )
            embed = discord.Embed(
                title="Liberal",
                description="Liberal is your secret role.",
                color=discord.Color.blue(),
            )
            embed.set_image(url="attachment://role.png")
            await client.get_user(player.player_id).send(file=file, embed=embed)

    file = discord.File("secret_hitler/img/hitler_role.png", filename="role.png")
    embed = discord.Embed(
        title="Hitler",
        description="Hitler is your secret role.",
        color=discord.Color.dark_red(),
    )
    # We play without this rule
    # if len(game.players) <= 6 and len(fascists) > 0:
    #    embed.add_field(name="Fascist", value="The fascist is "+client.get_user(fascists[0].player_id).display_name)

    embed.set_image(url="attachment://role.png")
    await client.get_user(hitler.player_id).send(file=file, embed=embed)

    for player in fascists:
        file = discord.File("secret_hitler/img/fascist_role.png", filename="role.png")
        embed = discord.Embed(
            title="Fascist",
            description="Fascist is your secret role.",
            color=discord.Color.orange(),
        )
        embed.add_field(
            name="Hitler",
            value=client.get_user(hitler.player_id).display_name + " is hitler",
            inline=False,
        )
        if len(game.players) > 6:
            for fas in fascists:
                embed.add_field(
                    name="Fascist",
                    value=client.get_user(fas.player_id).display_name,
                    inline=False,
                )
        embed.set_image(url="attachment://role.png")
        await client.get_user(player.player_id).send(file=file, embed=embed)


# Tasks

# Rules and other stuff (Long and boring shit)


async def printRules(channel):
    embed = discord.Embed(
        title="Rules",
        url="https://cdn.vapid.site/sites/a67e0c72-4902-4365-a899-3386df73c2c4/assets/Secret_Hitler_Rules-023bc755617986cb2276a3b6920e43e0.pdf",
        description="A brief summary of the secret hitler rules",
        color=discord.Color.dark_red(),
    )
    embed.add_field(
        name="Overview",
        value="At the beginning of the game, each player is secretly assigned to one of three roles: Liberal, Fascist, or Hitler. The Liberals have a majority, but they don’t know for sure who anyone is; Fascists must resort to secrecy and sabotage to accomplish their goals. Hitler plays for the Fascist team, and the Fascists know Hitler’s identity from the outset, but Hitler doesn’t know the Fascists and must work to figure them out.The Liberals win by enacting five Liberal Policies or killing Hitler. The Fascists win by enacting six Fascist Policies, or if Hitler is elected Chancellor after three Fascist Policies have been enacted. Whenever a Fascist Policy is enacted, the government becomes more powerful, and the President is granted a single-use power which must be used before the next round can begin. It doesn’t matter what team the President is on; in fact, even Liberal players might be tempted to enact a Fascist Policy to gain new powers.",
        inline=False,
    )
    embed.add_field(
        name="Object",
        value="Every player has a secret identity as a member of either the Liberal team or the Fascist team. Players on the Liberal team win if either: Five Liberal Policies are enacted OR Hitler is assassinated. Players on the Fascist team win if either: Six Fascist Policies are enacted OR Hitler is elected Chancellor any time after the third Fascist Policy has been enacted.",
        inline=False,
    )
    embed.set_footer(
        text="Licensed under Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License"
    )
    await channel.send(embed=embed)


async def printLicense(channel):
    embed = discord.Embed(
        title="Licenses",
        description="Information about the license of this game.",
        url="https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode",
        color=discord.Color.dark_red(),
    )
    embed.add_field(
        name="Creative Commons BY-NC-SA 4.0",
        value="This project is licensed under Creative Commons BY-NC-SA 4.0. You are free to adapt and share the game in any form or format under following conditions. You have to credit us if you use this game. You are not allowed to use the game for commercial use. You have to use the same license as we do (CC BY-NC-SA 4.0). You are not allowed to restrict others from doing anything our license allows. That means you can't submit the app to an app store without approval",
        inline=False,
    )
    embed.add_field(
        name="Credits",
        value="Secret Hitler was created by Mike Boxleiter, Tommy Maranges, Max Temkin, and Mac Schubert (see secrethitler.com). The graphics used for this project are from secrethitlerfree.de and made by Flatimalsstudios. The code used for this game is made by Nergon and also licensed under CC BY-NC-SA 4.0",
        inline=False,
    )
    embed.add_field(
        name="Source Code",
        value="You can find the source code for this project on https://github.com/dr-carlos/Secret-Hitler",
        inline=False,
    )
    await channel.send(embed=embed)


async def printHelp(channel):
    embed = discord.Embed(
        title="Help",
        description="Overview of the commands for the SecretHitler bot",
        color=discord.Color.dark_red(),
    )
    embed.set_thumbnail(url=client.user.display_avatar.url)
    embed.add_field(name=f"{c_prefix}help", value="Displays the help")
    embed.add_field(
        name=f"{c_prefix}rules",
        value="Shows a short summary of the rules",
        inline=False,
    )
    embed.add_field(
        name=f"{c_prefix}license",
        value="Shows information about the license of this bot and SecretHitler",
        inline=False,
    )
    embed.add_field(
        name=f"{c_prefix}startgame <players>",
        value="Starts a private game.",
        inline=False,
    )
    embed.add_field(
        name=f"{c_prefix}stopgame <id>",
        value="Stops the game with the given id",
        inline=False,
    )
    embed.add_field(
        name=f"{c_prefix}invite <username>",
        value="Invites a player to a private game",
        inline=False,
    )
    embed.add_field(
        name=f"{c_prefix}veto", value="Veto the current agenda", inline=False
    )
    embed.add_field(
        name=f"{c_prefix}accept", value="Accept the current veto", inline=False
    )
    embed.add_field(
        name=f"{c_prefix}decline", value="Decline the current veto", inline=False
    )
    embed.add_field(name=f"{c_prefix}restart", value="Restarts a game", inline=False)
    embed.add_field(
        name=f"{c_prefix}investigate <playername>",
        value="Investigates a players party",
        inline=False,
    )
    embed.add_field(
        name=f"{c_prefix}discard <l/f>",
        value="Discards a fascist or a liberal policy",
        inline=False,
    )
    embed.add_field(
        name=f"{c_prefix}execute <playername>", value="Executes a player", inline=False
    )
    embed.add_field(
        name=f"{c_prefix}setup",
        value="Creates a Secret Hitler section in the discord and configures it for running games",
        inline=False,
    )
    embed.set_footer(
        text="Please note that some commands are only available during a special event in a game"
    )
    await channel.send(embed=embed)


load_dotenv()
token = os.getenv("SECRET_HITLER_DISCORD_TOKEN")

if token is None:
    raise RuntimeError("SECRET_HITLER_DISCORD_TOKEN environment variable not set")

client.run(token)
