import os
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import cast

import discord
import requests
from bs4 import BeautifulSoup
from discord.ext import tasks, commands

from playwright.async_api import (
    async_playwright,
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    ViewportSize,
)


# ============================================================
# 1. 봇 설정
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN")

TARGET_CHANNEL_ID = 1460907216415621292


# ============================================================
# 2. Discord 설정
# ============================================================

intents = discord.Intents.default()

# PyCharm 타입 검사 우회
setattr(intents, "message_content", True)

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# ============================================================
# 3. 공지 기억
# ============================================================

seen_notice_urls: set[str] = set()

notice_checker_initialized = False


# ============================================================
# 4. 엘소드 공지 목록 가져오기
# ============================================================

def get_latest_notices() -> list[tuple[str, str]]:
    """
    엘소드 공식 홈페이지의 공지 목록을 가져옵니다.
    """

    url = "https://elsword.nexon.com/News/Notice/List"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    notices: list[tuple[str, str]] = []

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

        # 공지 게시물 링크 찾기
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

            # --------------------------------------------
            # 상대 주소
            # --------------------------------------------

            if href.startswith("/"):

                link = (
                    "https://elsword.nexon.com"
                    + href
                )

            # --------------------------------------------
            # 절대 주소
            # --------------------------------------------

            elif href.startswith("http"):

                link = href

            else:

                continue

            # --------------------------------------------
            # 제목 가져오기
            # --------------------------------------------

            title_elem = item.select_one(
                ".title"
            )

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

            # --------------------------------------------
            # 같은 링크 중복 제거
            # --------------------------------------------

            already_exists = any(
                existing_link == link
                for _, existing_link in notices
            )

            if already_exists:
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
            f"[공지 확인] 최종 "
            f"{len(notices)}개 공지 확인"
        )

        return notices

    except requests.RequestException as error:

        print(
            f"[크롤링 에러] 홈페이지 요청 실패: "
            f"{error}"
        )

        return []

    except (
        UnicodeDecodeError,
        AttributeError,
        TypeError,
        ValueError
    ) as error:

        print(
            f"[크롤링 에러] HTML 처리 실패: "
            f"{error}"
        )

        return []


# ============================================================
# 5. 공지 페이지 캡처
# ============================================================

async def capture_notice_page(
    url: str,
    output_path: str = "notice_temp.png"
) -> str | None:
    """
    엘소드 공지 페이지에서 공지 내용 영역만 캡처합니다.

    공지 영역을 찾지 못하면
    홈페이지 전체를 캡처하지 않습니다.
    """

    print(
        f"[캡처] 공지 페이지 접속: {url}"
    )

    try:

        async with async_playwright() as playwright:

            # ------------------------------------------------
            # Chromium 실행
            # ------------------------------------------------

            browser = await playwright.chromium.launch(
                headless=True
            )

            try:

                # ------------------------------------------------
                # 화면 크기
                # ------------------------------------------------

                viewport_setting = cast(
                    ViewportSize,
                    {
                        "width": 1600,
                        "height": 1000
                    }
                )

                context = await browser.new_context(
                    viewport=viewport_setting,
                    device_scale_factor=2
                )

                try:

                    page = await context.new_page()

                    # ------------------------------------------------
                    # 페이지 접속
                    # ------------------------------------------------

                    await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=30000
                    )

                    print(
                        "[캡처] 페이지 기본 로딩 완료"
                    )

                    # 광고 / 이미지 / JS 로딩 대기
                    await page.wait_for_timeout(3000)

                    # ------------------------------------------------
                    # 공지 영역 후보
                    # ------------------------------------------------

                    selectors = [
                        ".view_cont",
                        ".view_conts",
                        ".view_content",
                        ".notice_view",
                        ".noticeView",
                        ".news_view",
                        ".newsView",
                        ".board_view",
                        ".boardView"
                    ]

                    notice_element = None

                    # ------------------------------------------------
                    # 공지 영역 찾기
                    # ------------------------------------------------

                    for selector in selectors:

                        try:

                            locator = page.locator(
                                selector
                            ).first

                            count = await locator.count()

                            if count <= 0:
                                continue

                            if not await locator.is_visible():
                                continue

                            bounding_box = (
                                await locator.bounding_box()
                            )

                            if bounding_box is None:
                                continue

                            width = bounding_box["width"]
                            height = bounding_box["height"]

                            # 너무 작은 영역은 제외
                            if width < 200:
                                continue

                            if height < 100:
                                continue

                            notice_element = locator

                            print(
                                f"[캡처] 공지 영역 발견: "
                                f"{selector}"
                            )

                            print(
                                f"[캡처] 영역 크기: "
                                f"{int(width)} x "
                                f"{int(height)}"
                            )

                            break

                        except PlaywrightError:
                            continue

                    # ------------------------------------------------
                    # 공지 영역을 못 찾았을 경우
                    # ------------------------------------------------

                    if notice_element is None:

                        print(
                            "[캡처 실패] 공지 내용 영역을 "
                            "찾지 못했습니다."
                        )

                        print(
                            "[캡처] 전체 페이지 캡처는 "
                            "실행하지 않습니다."
                        )

                        return None

                    # ------------------------------------------------
                    # 공지 영역으로 이동
                    # ------------------------------------------------

                    await notice_element.scroll_into_view_if_needed()

                    await page.wait_for_timeout(1000)

                    # ------------------------------------------------
                    # 공지 영역만 캡처
                    # ------------------------------------------------

                    await notice_element.screenshot(
                        path=output_path,
                        animations="disabled"
                    )

                    print(
                        f"[캡처 성공] {output_path}"
                    )

                    return output_path

                finally:

                    try:

                        await context.close()

                    except PlaywrightError as error:

                        print(
                            f"[캡처] 브라우저 context 종료 중 "
                            f"오류: {error}"
                        )

            finally:

                try:

                    await browser.close()

                except PlaywrightError as error:

                    print(
                        f"[캡처] 브라우저 종료 중 "
                        f"오류: {error}"
                    )

    except PlaywrightTimeoutError as error:

        print(
            f"[캡처 에러] 페이지 로딩 시간 초과: "
            f"{error}"
        )

        return None

    except PlaywrightError as error:

        print(
            f"[캡처 에러] Playwright 오류: "
            f"{error}"
        )

        return None

    except OSError as error:

        print(
            f"[캡처 에러] 파일 처리 오류: "
            f"{error}"
        )

        return None


# ============================================================
# 6. !testnotice 테스트 명령
# ============================================================

@bot.command(name="testnotice")
async def test_notice(
    ctx: commands.Context
) -> None:

    print(
        "[테스트] !testnotice 실행"
    )

    # ------------------------------------------------
    # 최신 공지 가져오기
    # ------------------------------------------------

    notices = get_latest_notices()

    if not notices:

        await ctx.send(
            "❌ 테스트할 공지를 가져오지 못했습니다."
        )

        print(
            "[테스트] 공지 목록 가져오기 실패"
        )

        return

    title, link = notices[0]

    print(
        f"[테스트] 테스트 공지: {title}"
    )

    print(
        f"[테스트] 테스트 링크: {link}"
    )

    # ------------------------------------------------
    # 공지 캡처
    # ------------------------------------------------

    print(
        "[테스트] 공지 페이지 캡처 시작"
    )

    image_path = await capture_notice_page(
        link,
        "notice_test.png"
    )

    print(
        f"[테스트] 캡처 결과: {image_path}"
    )

    # ------------------------------------------------
    # Discord Embed
    # ------------------------------------------------

    embed = discord.Embed(
        title="🧪 테스트 - 엘소드 공지사항",
        description=(
            f"[{title}]({link})\n\n"
            "테스트 전송입니다."
        ),
        color=discord.Color.green()
    )

    embed.set_footer(
        text="엘소드 공식 홈페이지"
    )

    # ------------------------------------------------
    # 이미지가 정상적으로 캡처된 경우
    # ------------------------------------------------

    if (
        image_path
        and os.path.exists(image_path)
    ):

        print(
            "[테스트] 캡처 이미지 Discord 전송"
        )

        file = discord.File(
            image_path,
            filename="notice_test.png"
        )

        embed.set_image(
            url="attachment://notice_test.png"
        )

        try:

            await ctx.send(
                embed=embed,
                file=file
            )

            print(
                "[테스트] Discord 전송 성공"
            )

        except discord.DiscordException as error:

            print(
                f"[테스트 전송 오류] {error}"
            )

        finally:

            try:
                os.remove(image_path)
            except OSError:
                pass

    # ------------------------------------------------
    # 이미지 캡처 실패
    # ------------------------------------------------

    else:

        print(
            "[테스트] 이미지 캡처 실패"
        )

        await ctx.send(
            embed=embed
        )


# ============================================================
# 7. Discord 로그인 완료
# ============================================================

@bot.event
async def on_ready():

    user = bot.user

    print(
        "=========================================="
    )

    print(
        "★★★★★ ON_READY 실행됨 ★★★★★"
    )

    if user is not None:

        print(
            f"[디스코드] 봇 이름: {user.name}"
        )

        print(
            f"[디스코드] 봇 ID: {user.id}"
        )

    else:

        print(
            "[디스코드] 봇 정보를 가져오지 못했습니다."
        )

    print(
        f"[공지 확인] 공지 검사 루프: "
        f"{notice_checker.is_running()}"
    )

    if not notice_checker.is_running():

        print(
            "★★★★★ 공지 검사 루프 START ★★★★★"
        )

        notice_checker.start()

    else:

        print(
            "[공지 확인] 검사 루프가 "
            "이미 실행 중입니다."
        )

    print(
        "=========================================="
    )


# ============================================================
# 8. 공지 확인 루프
# ============================================================

@tasks.loop(minutes=5)
async def notice_checker():

    global notice_checker_initialized

    print(
        "[공지 확인] 5분 주기 검사 시작"
    )

    # ------------------------------------------------
    # Discord 채널 찾기
    # ------------------------------------------------

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

    # ------------------------------------------------
    # 공지 목록 가져오기
    # ------------------------------------------------

    notices = get_latest_notices()

    if not notices:

        print(
            "[공지 확인] 공지 목록을 "
            "가져오지 못했습니다."
        )

        return

    # ------------------------------------------------
    # 최초 실행
    # ------------------------------------------------

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

    # ------------------------------------------------
    # 새로운 공지 찾기
    # ------------------------------------------------

    new_notices: list[tuple[str, str]] = []

    for title, link in notices:

        if link not in seen_notice_urls:

            new_notices.append(
                (title, link)
            )

    # ------------------------------------------------
    # 새로운 공지가 없으면 종료
    # ------------------------------------------------

    if not new_notices:

        print(
            "[공지 확인] 새로운 공지가 없습니다."
        )

        return

    print(
        f"[공지 확인] 새로운 공지 "
        f"{len(new_notices)}개 발견!"
    )

    # ------------------------------------------------
    # 오래된 공지부터 전송
    # ------------------------------------------------

    for title, link in reversed(
        new_notices
    ):

        print(
            "------------------------------------------"
        )

        print(
            f"[공지 전송] {title}"
        )

        print(
            f"[공지 전송] {link}"
        )

        # ------------------------------------------------
        # 공지 캡처
        # ------------------------------------------------

        image_path = await capture_notice_page(
            link,
            "notice_temp.png"
        )

        # ------------------------------------------------
        # Embed 생성
        # ------------------------------------------------

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

        # ------------------------------------------------
        # 이미지가 있는 경우
        # ------------------------------------------------

        if (
            image_path
            and os.path.exists(image_path)
        ):

            print(
                "[공지 전송] 공지 영역 이미지 첨부"
            )

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
                    "[공지 전송] Discord 전송 성공"
                )

            except discord.DiscordException as error:

                print(
                    f"[Discord 전송 오류] {error}"
                )

                # 전송 실패했으므로
                # seen에 넣지 않음
                continue

            finally:

                try:
                    os.remove(image_path)
                except OSError:
                    pass

        # ------------------------------------------------
        # 이미지 캡처 실패
        # ------------------------------------------------

        else:

            print(
                "[공지 전송] 공지 영역 캡처 실패"
            )

            print(
                "[공지 전송] 이미지 없이 "
                "공지 링크만 전송합니다."
            )

            try:

                await channel.send(
                    embed=embed
                )

                print(
                    "[공지 전송] Discord 전송 성공"
                )

            except discord.DiscordException as error:

                print(
                    f"[Discord 전송 오류] {error}"
                )

                continue

        # ------------------------------------------------
        # 정상적으로 Discord 전송된 공지만 기억
        # ------------------------------------------------

        seen_notice_urls.add(
            link
        )

        print(
            f"[공지 기억] {link}"
        )


# ============================================================
# 9. 공지 검사 시작 전 대기
# ============================================================

@notice_checker.before_loop
async def before_notice_checker():

    await bot.wait_until_ready()


# ============================================================
# 10. Render Web Service HTTP 서버
# ============================================================

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

    # PyCharm 타입 검사 해결
    handler_type = cast(
        type[BaseHTTPRequestHandler],
        HealthHandler
    )

    server = HTTPServer(
        ("0.0.0.0", port),
        handler_type  # type: ignore[arg-type]
    )

    print(
        f"[웹 서버] Render 포트 "
        f"{port}에서 실행 중"
    )

    server.serve_forever()


# ============================================================
# 11. Render HTTP 서버 시작
# ============================================================

health_thread = Thread(
    target=run_health_server,
    daemon=True
)

health_thread.start()


# ============================================================
# 12. Discord 봇 실행
# ============================================================

if TOKEN is None:

    raise ValueError(
        "DISCORD_TOKEN 환경 변수가 "
        "설정되지 않았습니다."
    )


bot.run(TOKEN)