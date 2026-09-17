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
        print(f"[캡처] 페이지 접속: {url}")

        async with async_playwright() as p:

            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage"
                ]
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
                wait_until="domcontentloaded",
                timeout=60000
            )

            print("[캡처] 페이지 로딩 완료")

            await page.wait_for_timeout(5000)

            element = await page.query_selector(
                ".view_cont"
            )

            if element:
                print("[캡처] .view_cont 발견")

                await element.screenshot(
                    path=output_path
                )

            else:
                print(
                    "[캡처] .view_cont를 찾지 못함"
                )
                print(
                    "[캡처] 전체 페이지 캡처로 전환"
                )

                await page.screenshot(
                    path=output_path,
                    full_page=True
                )

            await browser.close()

            if os.path.exists(output_path):
                print(
                    f"[캡처] 성공: {output_path}"
                )
                return output_path

            print("[캡처] 파일 생성 실패")
            return None

    except Exception as e:

        print(
            f"[캡처 에러] {type(e).__name__}: {e}"
        )

        return None




# ==========================================
# 6. Discord 봇 로그인
# ==========================================

@bot.event
async def on_ready():
    print("================================")
    print("★★★★★ ON_READY 실행됨 ★★★★★")
    print(f"봇 이름: {bot.user}")
    print(f"봇 ID: {getattr(bot.user, 'id', '없음')}")
    print(f"공지 검사 루프: {notice_checker.is_running()}")
    print("================================")

    if not notice_checker.is_running():
        notice_checker.start()
        print("★★★★★ 공지 검사 루프 START ★★★★★")


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
# 8. 테스트 공지 전송 명령어
# ==========================================

@bot.command()
async def testnotice(ctx):
    """공지 캡처 및 Discord 전송 테스트"""

    print("[테스트] !testnotice 실행")

    test_url = "https://elsword.nexon.com/News/Notice/View?n4ArticleSN=150184"
    test_title = "테스트 - 엘소드 공지사항"

    screenshot_file = "test_notice.png"

    print("[테스트] 공지 페이지 캡처 시작")

    img_path = await capture_notice_page(
        test_url,
        screenshot_file
    )

    print(f"[테스트] 캡처 결과: {img_path}")

    embed = discord.Embed(
        title="🧪 테스트 - 엘소드 공지사항",
        description=f"[{test_title}]({test_url})",
        color=discord.Color.green()
    )

    embed.set_footer(
        text="엘소드 공지 봇 테스트 전송"
    )

    if img_path and os.path.exists(img_path):
        print("[테스트] 이미지 파일 확인됨")

        file = discord.File(
            img_path,
            filename="notice.png"
        )

        embed.set_image(
            url="attachment://notice.png"
        )

        await ctx.send(
            embed=embed,
            file=file
        )

        try:
            os.remove(img_path)
        except OSError:
            pass

        print("[테스트] 이미지 포함 전송 완료")

    else:
        print("[테스트] 이미지 캡처 실패")

        await ctx.send(
            embed=embed
        )


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

print("========================================")
print("★★★★★ ELSWORD BOT 최신 코드 실행 ★★★★★")
print("★★★★★ 여기까지 실행되었습니다 ★★★★★")
print("========================================")

bot.run(TOKEN)