import re
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import json
import os
import asyncio

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID'))

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

JSONBIN_BIN_ID = os.getenv('JSONBIN_BIN_ID')
JSONBIN_API_KEY = os.getenv('JSONBIN_API_KEY')

def load_db():
    if not JSONBIN_BIN_ID or not JSONBIN_API_KEY:
        print("[WARNING] Cloud database credentials missing. Running with empty local dictionary.")
        return {}
    try:
        url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest"
        headers = {"X-Master-Key": JSONBIN_API_KEY}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            print("🚀 Successfully loaded users database from the cloud!")
            return response.json().get("record", {})
        else:
            print(f"[ERROR] Failed to load cloud DB. Status: {response.status_code}")
    except Exception as e:
        print(f"[ERROR] Could not connect to cloud DB: {e}")
    return {}

def save_db():
    if not JSONBIN_BIN_ID or not JSONBIN_API_KEY:
        print("[ERROR] Cannot save. Cloud database credentials missing.")
        return
    try:
        url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"
        headers = {
            "X-Master-Key": JSONBIN_API_KEY,
            "Content-Type": "application/json"
        }
        # Pushes your updated database up to the cloud securely
        response = requests.put(url, json=user_db, headers=headers, timeout=10)
        if response.status_code == 200:
            print("💾 Cloud database updated successfully!")
        else:
            print(f"[ERROR] Failed to save cloud DB. Status: {response.status_code}")
    except Exception as e:
        print(f"[ERROR] Could not save to cloud DB: {e}")

# Automatically initialize user_db from the cloud when the bot runs
user_db = load_db()

# --- API Fetching Functions ---
def get_codeforces_solved(username):
    try:
        # Codeforces handles are case-sensitive for API paths; clean up spacing
        username = username.strip()
        url = f"https://codeforces.com/api/user.status?handle={username}"
        
        # Add a proper browser header to prevent random 500/403 drops
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            print(f"[DEBUG Codeforces] API returned status {response.status_code} for '{username}'. Check if handle spelling is exactly correct.")
            return 0
            
        data = response.json()
        if data.get("status") == "OK":
            solved = set()
            for submission in data["result"]:
                if submission["verdict"] == "OK":
                    prob = submission["problem"]
                    solved.add(f"{prob.get('contestId')}{prob.get('index')}")
            return len(solved)
    except Exception as e:
        print(f"[DEBUG Codeforces Error]: {e}")
    return 0

def get_atcoder_solved(username):
    try:
        url = f"https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions?user={username}&from_second=0"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            submissions = response.json()
            ac_solved = set()
            for sub in submissions:
                if sub.get("result") == "AC":
                    ac_solved.add(sub.get("problem_id"))
            return len(ac_solved)
    except Exception as e:
        print(f"[DEBUG AtCoder Error]: {e}")
    return 0

def get_codechef_solved(username):
    try:
        url = f"https://www.codechef.com/users/{username}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 1. Silenced the deprecation warning by changing 'text' to 'string'
            # 2. Broader sweep: check element strings AND tag text contents directly
            for element in soup.find_all(string=re.compile(r'Problems Solved', re.IGNORECASE)):
                parent_text = element.parent.get_text()
                numbers = re.findall(r'\d+', parent_text)
                if numbers:
                    return int(numbers[-1])
            
            # Fallback fallback: look directly inside common container classes
            rating_content = soup.find(class_="rating-data-section")
            if rating_content:
                numbers = re.findall(r'\d+', rating_content.get_text())
                if numbers:
                    return int(numbers[-1])
                    
            print(f"[DEBUG CodeChef] Profile loaded for {username}, but data didn't render inside standard elements.")
        else:
            print(f"[DEBUG CodeChef] HTTP Status Error: {response.status_code}")
    except Exception as e:
        print(f"[DEBUG CodeChef Error]: {e}")
    return 0

# --- Background Task for Leaderboard ---

@tasks.loop(hours=48)
async def automatic_leaderboard():
    await bot.wait_until_ready()
    channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
    
    if not channel:
        print("Leaderboard channel not found. Check your LEADERBOARD_CHANNEL_ID.")
        return

    if not user_db:
        return 

    await channel.send("🔄 **Calculating bi-weekly competitive programming leaderboard...**")

    leaderboard_data = []

    for user_id, platforms in user_db.items():
        try:
            member = await channel.guild.fetch_member(int(user_id))
            display_name = member.display_name
        except Exception:
            display_name = f"User({user_id})"

        cf_user = platforms.get("codeforces", "")
        ac_user = platforms.get("atcoder", "")
        cc_user = platforms.get("codechef", "")

        cf_solved = get_codeforces_solved(cf_user) if cf_user else 0
        ac_solved = get_atcoder_solved(ac_user) if ac_user else 0
        cc_solved = get_codechef_solved(cc_user) if cc_user else 0
        
        total_solved = cf_solved + ac_solved + cc_solved

        leaderboard_data.append({
            "name": display_name,
            "cf": cf_solved if cf_user else "-",
            "ac": ac_solved if ac_user else "-",
            "cc": cc_solved if cc_user else "-",
            "total": total_solved
        })
        await asyncio.sleep(1)

    leaderboard_data.sort(key=lambda x: x["total"], reverse=True)

    embed = discord.Embed(
        title="🏆 Server Competitive Programming Leaderboard 🏆",
        description="Automatically updated every 2 days.",
        color=discord.Color.gold()
    )

    names_list = []
    stats_list = []
    total_list = []

    for rank, user in enumerate(leaderboard_data, start=1):
        rank_str = f"🥇 {user['name']}" if rank == 1 else f"🥈 {user['name']}" if rank == 2 else f"🥉 {user['name']}" if rank == 3 else f"{rank}. {user['name']}"
        
        names_list.append(rank_str)
        stats_list.append(f"CF: `{user['cf']}` | AC: `{user['ac']}` | CC: `{user['cc']}`")
        total_list.append(f"**{user['total']}**")

    embed.add_field(name="👤 User", value="\n".join(names_list), inline=True)
    embed.add_field(name="📊 Breakdown", value="\n".join(stats_list), inline=True)
    embed.add_field(name="✨ Total Solved", value="\n".join(total_list), inline=True)

    await channel.send(embed=embed)

# --- Bot Setup Commands ---

@bot.event
async def on_ready():
    print(f"Bot is online as {bot.user}")
    if not automatic_leaderboard.is_running():
        automatic_leaderboard.start()

@bot.command()
async def codeforces(ctx, username: str):
    user_id = str(ctx.author.id)
    if user_id not in user_db: user_db[user_id] = {}
    user_db[user_id]["codeforces"] = username
    save_db()
    await ctx.send(f"✅ Codeforces username set to `{username}`.")

@bot.command()
async def atcoder(ctx, username: str):
    user_id = str(ctx.author.id)
    if user_id not in user_db: user_db[user_id] = {}
    user_db[user_id]["atcoder"] = username
    save_db()
    await ctx.send(f"✅ AtCoder username set to `{username}`.")

@bot.command()
async def codechef(ctx, username: str):
    user_id = str(ctx.author.id)
    if user_id not in user_db: user_db[user_id] = {}
    user_db[user_id]["codechef"] = username
    save_db()
    await ctx.send(f"✅ CodeChef username set to `{username}`.")

@bot.command()
async def stats(ctx):
    user_id = str(ctx.author.id)
    
    if user_id not in user_db or not user_db[user_id]:
        await ctx.send("❌ You haven't set any usernames yet! Use `!codeforces`, `!atcoder`, or `!codechef` first.")
        return

    progress_msg = await ctx.send("🔄 Fetching your competitive programming stats... please wait...")

    cf_user = user_db[user_id].get("codeforces", "Not Set")
    ac_user = user_db[user_id].get("atcoder", "Not Set")
    cc_user = user_db[user_id].get("codechef", "Not Set")

    cf_solved = "-"
    if cf_user != "Not Set":
        cf_solved = get_codeforces_solved(cf_user)
        if cf_solved == 0: 
            print(f"[DEBUG] CF fetch returned 0 or failed for: {cf_user}")

    ac_solved = "-"
    if ac_user != "Not Set":
        ac_solved = get_atcoder_solved(ac_user)
        if ac_solved == 0:
            print(f"[DEBUG] AtCoder fetch returned 0 or failed for: {ac_user}")

    cc_solved = "-"
    if cc_user != "Not Set":
        cc_solved = get_codechef_solved(cc_user)
        if cc_solved == 0:
            print(f"[DEBUG] CodeChef fetch returned 0 or failed for: {cc_user}")

    embed = discord.Embed(
        title=f"📊 Competitive Programming Stats for {ctx.author.display_name}",
        color=discord.Color.blue()
    )
    embed.add_field(name="🚀 Platform", value="**Codeforces**\n**AtCoder**\n**CodeChef**", inline=True)
    embed.add_field(name="👤 Username", value=f"{cf_user}\n{ac_user}\n{cc_user}", inline=True)
    embed.add_field(name="✅ Solved", value=f"{cf_solved}\n{ac_solved}\n{cc_solved}", inline=True)

    await progress_msg.delete()
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def forceleaderboard(ctx):
    await ctx.send("Forcing leaderboard update...")
    await automatic_leaderboard.__wrapped__() 

@bot.command()
async def unlink(ctx, platform: str = None):
    user_id = str(ctx.author.id)
    
    # Check if the user even has anything registered
    if user_id not in user_db or not user_db[user_id]:
        await ctx.send("❌ You don't have any accounts linked to begin with!")
        return

    # If they didn't specify which platform to remove
    if platform is None:
        await ctx.send("❓ Please specify which platform to unlink. \nExample: `!unlink codeforces`, `!unlink atcoder`, or `!unlink codechef`")
        return

    # Clean up the input string to match database keys
    platform = platform.lower().strip()

    if platform in ["codeforces", "cf"]:
        target_key = "codeforces"
    elif platform in ["atcoder", "ac"]:
        target_key = "atcoder"
    elif platform in ["codechef", "cc"]:
        target_key = "codechef"
    else:
        await ctx.send("❌ Invalid platform! Choose from: `codeforces`, `atcoder`, or `codechef`.")
        return

    # Check if they actually have that specific platform linked
    if target_key in user_db[user_id]:
        removed_username = user_db[user_id].pop(target_key)
        
        # 🌟 NEW FIX: If they have NO platforms left, wipe them completely from the DB
        if not user_db[user_id]:
            del user_db[user_id]
            
        save_db()
        await ctx.send(f"🗑️ Successfully unlinked your **{target_key.capitalize()}** account (`{removed_username}`).")
    else:
        await ctx.send(f"❌ You don't have a **{target_key.capitalize()}** account linked.")
        
bot.run(TOKEN)
