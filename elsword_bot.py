import os
import discord
from discord.ext import tasks, commands
import requests
from bs4 import BeautifulSoup

from playwright.async_api import async_playwright

from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread


# =========================================================
# 1. 기본 설정
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")

TARGET_CHANNEL_ID = 1460907216415621292

NOTICE_LIST_URL = "https://elsword.nexon.com/News/Notice/List"
NOTICE_BASE_URL = "https://elsword.nexon.com"


# =========================================================
# 2. Discord 설정
# =========================================================

intents = discord.Intents.default()

setattr(
    intents,
    "message_content",
    True
)

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================================================
# 3. 공지 기억
# =========================================================

seen_notice_urls = set()

notice_checker_initialized = False


# =========================================================
# 4. 엘소드 공지 목록 가져오기
# =========================================================

def get_latest_notices():
    """
    엘소드 공식 홈페이지의 최신 공지 목록을 가져옵니다.
    """

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    notices = []

    try:

        response = requests.get(
            NOTICE_LIST_URL,
            headers=headers,
            timeout=15
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

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

            # ---------------------------------------------
            # 상대주소 → 절대주소
            # ---------------------------------------------

            if href.startswith("/"):

                link = (
                    NOTICE_BASE_URL
                    + href
                )

            elif href.startswith("http"):

                link = href

            else:

                continue

            # ---------------------------------------------
            # 제목 가져오기
            # ---------------------------------------------

            title_element = item.select_one(
                ".title"
            )

            if title_element:

                title = title_element.get_text(
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

            # ---------------------------------------------
            # 같은 링크 중복 제거
            # ---------------------------------------------

            if any(
                existing_link == link
                for _, existing_link in notices
            ):

                continue

            notices.append(
                (
                    title,
                    link
                )
            )

            print(
                f"[공지 발견] {title}"
            )

            print(
                f"            {link}"
            )

            # 최신 공지 10개까지만 사용
            if len(notices) >= 10:

                break

        print(
            f"[공지 확인] 최종 "
            f"{len(notices)}개 공지 확인"
        )

        return notices

    # requests 관련 오류
    except requests.RequestException as error:

        print(
            f"[크롤링 에러] "
            f"웹사이트 요청 실패: {error}"
        )

        return []

    # HTML 처리 관련 오류
    except (
        UnicodeDecodeError,
        AttributeError,
        TypeError,
        ValueError
    ) as error:

        print(
            f"[크롤링 에러] "
            f"HTML 처리 실패: {error}"
        )

        return []


# =========================================================
# 5. 공지 페이지 캡처
# =========================================================

async def capture_notice_page(
    url: str,
    output_path: str = "notice_temp.png"
):
    """엘소드 공지 본문 영역만 캡처"""

    try:
        print(f"[캡처] 페이지 접속: {url}")

        async with async_playwright() as p:

            browser = await p.chromium.launch(
                headless=True
            )

            # viewport 설정을 아예 생략
            # PyCharm의 ViewportSize 타입 경고 방지
            page = await browser.new_page()

            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000
            )

            # 페이지가 로딩될 시간을 조금 줌
            await page.wait_for_timeout(3000)

            # --------------------------------------
            # 엘소드 공지 본문 영역 찾기
            # --------------------------------------

            selectors = [
                ".view_cont",
                ".view-cont",
                ".notice_view",
                ".noticeView",
                ".board_view",
                ".boardView",
                ".view_content",
                ".viewContent"
            ]

            notice_element = None

            for selector in selectors:

                try:
                    element = await page.query_selector(
                        selector
                    )

                    if element is None:
                        continue

                    box = await element.bounding_box()

                    if box is None:
                        continue

                    if (
                        box["width"] > 300
                        and box["height"] > 100
                    ):
                        notice_element = element

                        print(
                            f"[캡처] 공지 본문 발견: "
                            f"{selector}"
                        )

                        break

                except Exception as e:
                    print(
                        f"[캡처] 선택자 확인 실패 "
                        f"{selector}: {e}"
                    )
                    continue

            # --------------------------------------
            # 공지 본문을 못 찾았으면
            # 전체 페이지 캡처하지 않음
            # --------------------------------------

            if notice_element is None:

                print(
                    "[캡처 실패] "
                    "공지 본문 영역을 찾지 못했습니다."
                )

                await browser.close()

                return None

            # --------------------------------------
            # 공지 본문 캡처
            # --------------------------------------

            print(
                "[캡처] 공지 본문 캡처 시작"
            )

            await notice_element.screenshot(
                path=output_path
            )

            print(
                f"[캡처 완료] {output_path}"
            )

            await browser.close()

            return output_path

    except Exception as e:

        print(
            f"[캡처 에러] "
            f"{type(e).__name__}: {e}"
        )

        return None


# =========================================================
# 6. Discord 로그인 완료
# =========================================================

@bot.event
async def on_ready():

    print(
        "================================"
    )

    print(
        "★★★★★ ON_READY 실행됨 ★★★★★"
    )

    user = bot.user

    if user is not None:

        print(
            f"봇 이름: {user.name}"
        )

        print(
            f"봇 ID: {user.id}"
        )

    print(
        f"공지 검사 루프: "
        f"{notice_checker.is_running()}"
    )

    # ---------------------------------------------
    # 공지 검사 시작
    # ---------------------------------------------

    if not notice_checker.is_running():

        print(
            "★★★★★ 공지 검사 루프 START ★★★★★"
        )

        notice_checker.start()

    else:

        print(
            "공지 검사 루프가 이미 실행 중입니다."
        )

    print(
        "================================"
    )


# =========================================================
# 7. 공지 검사
# =========================================================

@tasks.loop(minutes=5)
async def notice_checker():

    global notice_checker_initialized

    print(
        "[공지 확인] 5분 주기 검사 시작"
    )

    # ---------------------------------------------
    # Discord 채널 확인
    # ---------------------------------------------

    channel = bot.get_channel(
        TARGET_CHANNEL_ID
    )

    if not isinstance(
        channel,
        (
            discord.TextChannel,
            discord.Thread
        )
    ):

        print(
            "[오류] 지정된 Discord 채널을 "
            "찾을 수 없습니다."
        )

        return

    # ---------------------------------------------
    # 공지 목록 가져오기
    # ---------------------------------------------

    notices = get_latest_notices()

    if not notices:

        print(
            "[공지 확인] 공지 목록을 "
            "가져오지 못했습니다."
        )

        return

    # ---------------------------------------------
    # 최초 실행
    # ---------------------------------------------

    if not notice_checker_initialized:

        seen_notice_urls.update(
            link
            for _, link in notices
        )

        notice_checker_initialized = True

        print(
            "[공지 확인] 초기화 완료 - "
            f"{len(seen_notice_urls)}개의 "
            "기존 공지를 기억했습니다."
        )

        return

    # ---------------------------------------------
    # 새로운 공지 찾기
    # ---------------------------------------------

    new_notices = []

    for title, link in notices:

        if link not in seen_notice_urls:

            new_notices.append(
                (
                    title,
                    link
                )
            )

    # ---------------------------------------------
    # 새 공지가 없음
    # ---------------------------------------------

    if not new_notices:

        print(
            "[공지 확인] 새로운 공지가 없습니다."
        )

        return

    print(
        f"[공지 확인] 새로운 공지 "
        f"{len(new_notices)}개 발견!"
    )

    # ---------------------------------------------
    # 오래된 공지부터 전송
    # ---------------------------------------------

    for title, link in reversed(
        new_notices
    ):

        print(
            f"[공지 전송] {title}"
        )

        screenshot_file = (
            "notice_temp.png"
        )

        # ---------------------------------------------
        # 공지 캡처
        # ---------------------------------------------

        image_path = await capture_notice_page(
            link,
            screenshot_file
        )

        # ---------------------------------------------
        # Embed 생성
        # ---------------------------------------------

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

        # ---------------------------------------------
        # 이미지 캡처 성공
        # ---------------------------------------------

        if (
            image_path
            and os.path.exists(image_path)
        ):

            file = discord.File(
                image_path,
                filename="notice.png"
            )

            embed.set_image(
                url="attachment://notice.png"
            )

            try:

                await channel.send(
                    embed=embed,
                    file=file
                )

                print(
                    "[공지 전송] "
                    "Discord 이미지 전송 성공"
                )

            except discord.HTTPException as error:

                print(
                    f"[Discord 전송 에러] "
                    f"{error}"
                )

            # 임시 이미지 삭제
            try:

                os.remove(
                    image_path
                )

            except OSError:

                pass

        # ---------------------------------------------
        # 이미지 캡처 실패
        # ---------------------------------------------

        else:

            print(
                "[공지 전송] "
                "캡처 실패 → 텍스트 공지만 전송"
            )

            try:

                await channel.send(
                    embed=embed
                )

            except discord.HTTPException as error:

                print(
                    f"[Discord 전송 에러] "
                    f"{error}"
                )

        # ---------------------------------------------
        # 공지 기억
        # ---------------------------------------------

        seen_notice_urls.add(
            link
        )


# =========================================================
# 8. 공지 검사 시작 전 대기
# =========================================================

@notice_checker.before_loop
async def before_notice_checker():

    await bot.wait_until_ready()


# =========================================================
# 9. !testnotice 명령어
# =========================================================

@bot.command(
    name="testnotice"
)
async def test_notice_command(ctx):
    """
    !testnotice

    최신 공지 하나를 가져와서
    공지 본문만 캡처하여 Discord에 전송합니다.
    """

    print(
        "[테스트] !testnotice 실행"
    )

    # ---------------------------------------------
    # 채널 확인
    # ---------------------------------------------

    if not isinstance(
        ctx.channel,
        (
            discord.TextChannel,
            discord.Thread
        )
    ):

        await ctx.send(
            "❌ 이 명령어를 사용할 수 없는 채널입니다."
        )

        return

    # ---------------------------------------------
    # 공지 목록 가져오기
    # ---------------------------------------------

    notices = get_latest_notices()

    if not notices:

        await ctx.send(
            "❌ 엘소드 공지 목록을 가져오지 못했습니다."
        )

        return

    # 가장 최신 공지
    title, link = notices[0]

    print(
        f"[테스트] 테스트 공지: {title}"
    )

    # ---------------------------------------------
    # 공지 캡처
    # ---------------------------------------------

    print(
        "[테스트] 공지 페이지 캡처 시작"
    )

    screenshot_file = (
        "test_notice_temp.png"
    )

    image_path = await capture_notice_page(
        link,
        screenshot_file
    )

    # ---------------------------------------------
    # Embed
    # ---------------------------------------------

    embed = discord.Embed(

        title="🧪 테스트 - 엘소드 공지사항",

        description=(
            f"[{title}]({link})"
        ),

        color=discord.Color.green()
    )

    embed.set_footer(
        text="테스트 전송입니다."
    )

    # ---------------------------------------------
    # 캡처 성공
    # ---------------------------------------------

    if (
        image_path
        and os.path.exists(image_path)
    ):

        file = discord.File(
            image_path,
            filename="test_notice.png"
        )

        embed.set_image(
            url="attachment://test_notice.png"
        )

        try:

            await ctx.send(
                embed=embed,
                file=file
            )

            print(
                "[테스트] 이미지 전송 성공"
            )

        except discord.HTTPException as error:

            print(
                f"[테스트 Discord 전송 에러] "
                f"{error}"
            )

        # 임시파일 삭제
        try:

            os.remove(
                image_path
            )

        except OSError:

            pass

    # ---------------------------------------------
    # 캡처 실패
    # ---------------------------------------------

    else:

        embed.description = (
            f"[{title}]({link})\n\n"
            "⚠️ 공지 본문 캡처에 실패했습니다."
        )

        try:

            await ctx.send(
                embed=embed
            )

        except discord.HTTPException as error:

            print(
                f"[테스트 Discord 전송 에러] "
                f"{error}"
            )

        print(
            "[테스트] 이미지 캡처 실패"
        )


# =========================================================
# 10. Render Web Service용 HTTP 서버
# =========================================================

class HealthHandler(
    BaseHTTPRequestHandler
):

    # noinspection PyPep8Naming
    def do_GET(self):

        self.send_response(
            200
        )

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

        self.send_response(
            200
        )

        self.send_header(
            "Content-Type",
            "text/plain; charset=utf-8"
        )

        self.end_headers()


# =========================================================
# 11. Render 서버 실행
# =========================================================

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


# =========================================================
# 12. TOKEN 확인
# =========================================================

if TOKEN is None:

    raise ValueError(
        "DISCORD_TOKEN 환경 변수가 "
        "설정되지 않았습니다."
    )


# =========================================================
# 13. 봇 실행
# =========================================================

print(
    "[봇] Discord 로그인 시작..."
)

bot.run(
    TOKEN
)