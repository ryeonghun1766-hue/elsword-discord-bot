import os
import discord
from discord.ext import tasks, commands
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, ViewportSize

from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread


# ==========================================
# 1. 봇 설정
# ==========================================

TOKEN = os.getenv("DISCORD_TOKEN")
TARGET_CHANNEL_ID = 1460907216415621292


# ==========================================
# 2. Discord 설정
# ==========================================

intents = discord.Intents.default()
setattr(intents, "message_content", True)

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# ==========================================
# 3. 공지 기억
# ==========================================

seen_notice_urls = set()
notice_checker_initialized = False


# ==========================================
# 4. 엘소드 공지 가져오기
# ==========================================

def get_latest_notices():
    """엘소드 공식 홈페이지 공지/점검/패치 목록 가져오기"""

    url = "https://elsword.nexon.com/News/Notice/List"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    notices = []

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=15
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        # 엘소드 공지 게시물 링크 찾기
        links = soup.select(
            'a[href*="/News/Notice/View"]'
        )

        print(
            f"[공지 확인] 페이지에서 "
            f"{len(links)}개의 게시물 링크 발견"
        )

        for item in links:

            href = item.get("href")

            if not href:
                continue

            href = str(href)

            # 상대주소 → 절대주소
            if href.startswith("/"):
                link = "https://elsword.nexon.com" + href

            elif href.startswith("http"):
                link = href

            else:
                continue

            # 제목 가져오기
            title_elem = item.select_one(".title")

            if title_elem:
                title = title_elem.get_text(
                    " ",
                    strip=True
                )
            else:
                title = item.get_text(
                    " ",
                    strip=True
                )

            if not title:
                continue

            # 같은 링크 중복 제거
            if any(
                existing_link == link
                for _, existing_link in notices
            ):
                continue

            notices.append(
                (title, link)
            )

            print(
                f"[공지 발견] {title}"
            )
            print(
                f"            {link}"
            )

        print(
            f"[공지 확인] 최종 {len(notices)}개 공지 확인"
        )

        return notices

    except Exception as e:

        print(
            f"[크롤링 에러] {e}"
        )

        return []


# ==========================================
# 5. 공지 페이지 캡처
# ==========================================

async def capture_notice_page(
    url: str,
    output_path: str = "notice_temp.png"
):
    """공지 페이지 캡처"""

    try:

        async with async_playwright() as p:

            browser = await p.chromium.launch(
                headless=True
            )

            viewport_setting: ViewportSize = {
                "width": 1280,
                "height": 1024
            }

            page = await browser.new_page(
                viewport=viewport_setting
            )

            await page.goto(
                url,
                wait_until="networkidle",
                timeout=30000
            )

            element = await page.query_selector(
                ".view_cont"
            )

            if element:

                await element.screenshot(
                    path=output_path
                )

            else:

                await page.screenshot(
                    path=output_path,
                    full_page=False
                )

            await browser.close()

            return output_path

    except Exception as e:

        print(
            f"[캡처 에러] {e}"
        )

        return None


# ==========================================
# 6. Discord 봇 로그인
# ==========================================

@bot.event
async def on_ready():
    user = bot.user

    print("================================")
    print("[디스코드] on_ready 실행됨")

    if user:
        print(f"[디스코드] 로그인 성공: {user.name}")

    print(f"[공지 확인] 현재 실행 상태: {notice_checker.is_running()}")

    if not notice_checker.is_running():
        print("[공지 확인] 검사 루프 시작!")
        notice_checker.start()
    else:
        print("[공지 확인] 검사 루프가 이미 실행 중입니다.")

    print("================================")


# ==========================================
# 7. 공지 확인
# ==========================================

@tasks.loop(minutes=5)
async def notice_checker():
    print("[공지 확인] 5분 주기 검사 시작")
    global notice_checker_initialized

    channel = bot.get_channel(
        TARGET_CHANNEL_ID
    )

    if not isinstance(
        channel,
        (discord.TextChannel, discord.Thread)
    ):

        print(
            "[오류] 지정된 Discord 채널을 "
            "찾을 수 없습니다."
        )

        return

    # 공지 목록 가져오기
    notices = get_latest_notices()

    if not notices:

        print(
            "[공지 확인] 공지 목록을 "
            "가져오지 못했습니다."
        )

        return


    # ======================================
    # 처음 실행
    # ======================================

    if not notice_checker_initialized:

        seen_notice_urls.update(
            link
            for _, link in notices
        )

        notice_checker_initialized = True

        print(
            f"[공지 확인] 초기화 완료 - "
            f"{len(seen_notice_urls)}개의 "
            f"기존 공지를 기억했습니다."
        )

        return


    # ======================================
    # 새로운 공지 찾기
    # ======================================

    new_notices = []

    for title, link in notices:

        if link not in seen_notice_urls:

            new_notices.append(
                (title, link)
            )


    # 새 공지가 없는 경우

    if not new_notices:

        print(
            "[공지 확인] 새로운 공지가 없습니다."
        )

        return


    print(
        f"[공지 확인] 새로운 공지 "
        f"{len(new_notices)}개 발견!"
    )


    # ======================================
    # Discord 전송
    # ======================================

    for title, link in reversed(
        new_notices
    ):

        screenshot_file = "notice_temp.png"

        print(
            f"[공지 전송] {title}"
        )

        # 스크린샷
        img_path = await capture_notice_page(
            link,
            screenshot_file
        )


        # Embed
        embed = discord.Embed(

            title="📢 엘소드 새로운 공지사항",

            description=(
                f"[{title}]({link})"
            ),

            color=discord.Color.blue()
        )

        embed.set_footer(
            text="엘소드 공식 홈페이지"
        )


        # 스크린샷이 있는 경우

        if (
            img_path
            and os.path.exists(img_path)
        ):

            file = discord.File(
                img_path,
                filename="notice.png"
            )

            embed.set_image(
                url="attachment://notice.png"
            )

            await channel.send(
                embed=embed,
                file=file
            )

            try:

                os.remove(
                    img_path
                )

            except OSError:

                pass


        # 스크린샷이 없는 경우

        else:

            await channel.send(
                embed=embed
            )


        # 전송한 공지 기억

        seen_notice_urls.add(
            link
        )


# ==========================================
# 8. 봇 시작 전 대기
# ==========================================

@notice_checker.before_loop
async def before_notice_checker():

    await bot.wait_until_ready()


# ==========================================
# 9. Render Web Service용 HTTP 서버
# ==========================================

class HealthHandler(BaseHTTPRequestHandler):

    # noinspection PyPep8Naming
    def do_GET(self):

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/plain; charset=utf-8"
        )

        self.end_headers()

        self.wfile.write(
            b"Elsword Bot is running!"
        )


    # noinspection PyPep8Naming
    def do_HEAD(self):

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/plain; charset=utf-8"
        )

        self.end_headers()


def run_health_server():

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    server = HTTPServer(

        ("0.0.0.0", port),

        HealthHandler  # type: ignore[arg-type]
    )

    print(
        f"[웹 서버] Render 포트 "
        f"{port}에서 실행 중"
    )

    server.serve_forever()


Thread(
    target=run_health_server,
    daemon=True
).start()


# ==========================================
# 10. Discord 봇 실행
# ==========================================

if TOKEN is None:

    raise ValueError(
        "DISCORD_TOKEN 환경 변수가 "
        "설정되지 않았습니다."
    )


bot.run(TOKEN)