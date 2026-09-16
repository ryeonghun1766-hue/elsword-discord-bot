import os
import discord
from discord.ext import tasks, commands
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, ViewportSize

# 1. 봇 설정
TOKEN = 'MTU0OTc3MjUxMDE5MzY0NzY3Ng.GO5q4N.e094suehI1cHwhwctfqhgZXJbgfoNB9ogLml1M'
TARGET_CHANNEL_ID = 1460907216415621292  # 본인의 디스코드 채널 ID

# 2. Intents 설정 (type: ignore 구문으로 PyCharm 경고 무시 처리)
intents = discord.Intents.default()
setattr(intents, "message_content", True)  # PyCharm 타입 검사기 우회

bot = commands.Bot(command_prefix='!', intents=intents)
last_notice_url = ""


def get_latest_notice():
    """엘소드 공식 홈페이지 최신 공지 제목과 링크 가져오기"""
    url = "https://elsword.nexon.com/News/Notice/List"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            first_notice = soup.select_one('.board_list ul li a')

            if first_notice:
                title_elem = first_notice.select_one('.title')
                title = title_elem.text.strip() if title_elem else first_notice.text.strip()
                href = str(first_notice.get('href', ''))
                link = "https://elsword.nexon.com" + href
                return title, link
    except Exception as e:
        print(f"[크롤링 에러] {e}")

    return None, None


async def capture_notice_page(url: str, output_path: str = "notice_temp.png"):
    """웹 페이지 캡처"""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            # ViewportSize 전용 객체를 전달하여 PyCharm 타입 경고 완벽 해결
            viewport_setting: ViewportSize = {"width": 1280, "height": 1024}
            page = await browser.new_page(viewport=viewport_setting)

            await page.goto(url, wait_until="networkidle", timeout=30000)

            element = await page.query_selector('.view_cont')
            if element:
                await element.screenshot(path=output_path)
            else:
                await page.screenshot(path=output_path, full_page=False)

            await browser.close()
            return output_path
    except Exception as e:
        print(f"[캡처 에러] {e}")
        return None


@bot.event
async def on_ready():
    user = bot.user
    if user:
        print(f'성공적으로 로그인했습니다: {user.name}')

    if not notice_checker.is_running():
        notice_checker.start()


@tasks.loop(minutes=5)
async def notice_checker():
    global last_notice_url

    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return

    title, link = get_latest_notice()

    if link and link != last_notice_url:
        if last_notice_url != "":
            screenshot_file = "notice_temp.png"
            img_path = await capture_notice_page(link, screenshot_file)

            embed = discord.Embed(
                title="📢 엘소드 새로운 공지사항",
                description=f"[{title}]({link})",
                color=discord.Color.blue()
            )
            embed.set_footer(text="엘소드 공식 홈페이지")

            if img_path and os.path.exists(img_path):
                file = discord.File(img_path, filename="notice.png")
                embed.set_image(url="attachment://notice.png")
                await channel.send(embed=embed, file=file)

                try:
                    os.remove(img_path)
                except OSError:
                    pass
            else:
                await channel.send(embed=embed)

        last_notice_url = link


@notice_checker.before_loop
async def before_notice_checker():
    await bot.wait_until_ready()


bot.run(TOKEN)