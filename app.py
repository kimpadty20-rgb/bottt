"""
네이버 카페(회원전용 게시판) 새 글 -> 디스코드 웹훅 알림 봇  (+ 수정 감지)
=================================================================

동작 방식
---------
1. 네이버에 "로그인된 상태의 쿠키"를 그대로 재사용해서, 회원 전용 게시판의
   글 목록 API를 주기적으로 조회합니다.
2. 직전에 저장해둔 "마지막으로 본 글 번호"보다 새 글 번호가 있으면
   -> 글 상세 API를 한 번 더 호출해서 본문 안에 있는 링크(유튜브 등)를 찾고
   -> 디스코드 웹훅으로 메시지를 보냅니다(카드 임베드 1개 + 링크 미리보기용 1개).
      이때 각 메시지는 "?wait=true" 옵션으로 보내서, 디스코드가 응답으로 돌려주는
      "메시지 ID"를 저장해둡니다. 이 ID가 있어야 나중에 그 메시지를 "수정"할 수 있습니다.
3. 최근 글(기본 5개, EDIT_CHECK_COUNT로 조절)에 대해서는 매 폴링마다 상세 API를
   다시 조회해서 제목/링크가 바뀌었는지 비교합니다.
   -> 바뀌었으면 새 메시지를 또 보내는 게 아니라, 저장해둔 메시지 ID로
      디스코드 메시지를 "수정(PATCH)"합니다.
   -> 링크가 있다가 없어졌으면 링크 메시지를 삭제합니다.
   -> 링크가 없다가 새로 생겼으면 링크 메시지를 새로 보냅니다.
4. 글 번호 / 메시지 ID / 마지막으로 확인한 제목·링크를 로컬 파일(state.json)에
   저장해두고, 다음 실행 때 이어서 비교합니다. (state.json은 최근 목록에 있는
   글들만 남기고 자동으로 정리됩니다.)

설정값은 코드에 직접 쓰지 않고 "환경변수"로 넣습니다 (보안 때문).
호스팅 패널에서 아래 4개의 환경변수를 등록해주세요:

  CLUB_ID
  MENU_ID
  NAVER_COOKIE
  DISCORD_WEBHOOK_URL

  (선택) EDIT_CHECK_COUNT   -> 매 폴링마다 수정 여부를 재확인할 "최근 글 개수" (기본 5)
  (선택) POLL_INTERVAL_SEC  -> 몇 초마다 확인할지 (기본 60)

  ※ 참고: 원래 파일 주석에 실제 쿠키 값/웹훅 URL이 예시로 그대로 적혀 있었습니다.
    둘 다 "그 자체로 로그인/전송 권한"이 되는 민감한 값이라, 이 코드를 다른 사람과
    공유하거나 깃허브 등에 올릴 계획이라면 디스코드 웹훅은 재발급, 네이버 쿠키는
    재로그인(재발급)해서 값을 바꿔주시는 걸 권장합니다. 아래부터는 .env 파일이나
    호스팅 패널의 환경변수에만 넣고, 코드/주석에는 실제 값을 쓰지 않도록 했습니다.

로컬 PC에서 테스트할 때는 터미널에서 아래처럼 실행하면 됩니다:

  (Windows, PowerShell)
    $env:CLUB_ID="11830253"
    $env:MENU_ID="39"
    $env:NAVER_COOKIE="NID_AUT=...; NID_SES=..."
    $env:DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
    python naver_cafe_discord_bot.py

  (Mac/Linux)
    export CLUB_ID=11830253
    export MENU_ID=39
    export NAVER_COOKIE="NID_AUT=...; NID_SES=..."
    export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
    python3 naver_cafe_discord_bot.py

실행 방법
---------
1) 파이썬 3.9+ 설치
2) pip install -r requirements.txt   (requests 필요)
3) 위 환경변수 설정 (또는 이 파일과 같은 폴더에 .env 파일 작성)
4) python naver_cafe_discord_bot.py
"""

import html
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

import requests


# ============ .env 파일 로드 ============
# 외부 라이브러리 없이 간단한 .env 형식을 읽습니다.
ENV_FILE = Path(__file__).parent / ".env"

if ENV_FILE.exists():
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        # 빈 줄 / 주석 무시
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        # 양쪽 따옴표 제거
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]

        # 이미 시스템 환경변수가 있으면 시스템 값을 우선 사용
        os.environ.setdefault(key, value)

# ============ CONFIG: 환경변수에서 읽어옵니다 (코드에 직접 쓰지 마세요) ============

CLUB_ID = os.environ.get("CLUB_ID", "")
MENU_ID = os.environ.get("MENU_ID", "")
COOKIE = os.environ.get("NAVER_COOKIE", "")
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# 필수값이 비어있으면 바로 알려주고 종료 (설정 실수를 빨리 알아채기 위함)
_missing = [
    name
    for name, val in [
        ("CLUB_ID", CLUB_ID),
        ("MENU_ID", MENU_ID),
        ("NAVER_COOKIE", COOKIE),
        ("DISCORD_WEBHOOK_URL", WEBHOOK_URL),
    ]
    if not val
]
if _missing:
    print(f"[에러] 환경변수가 설정되지 않았습니다: {', '.join(_missing)}")
    print("호스팅 패널의 '환경변수(Environment Variables)' 설정에서 위 값들을 등록해주세요.")
    sys.exit(1)

POLL_INTERVAL_SEC = int(os.environ.get("POLL_INTERVAL_SEC", "60"))  # 몇 초마다 확인할지
# 매 폴링마다 "수정됐는지" 다시 확인할 최근 글 개수. 너무 크게 잡으면 상세 API 호출이
# 그만큼 늘어나니(=네이버에 부담), 적당한 값을 권장합니다.
EDIT_CHECK_COUNT = int(os.environ.get("EDIT_CHECK_COUNT", "5"))
STATE_FILE = Path(__file__).parent / "state.json"

# 웹훅 URL에서 webhook_id / webhook_token을 뽑아둡니다 (메시지 수정·삭제 API에 필요).
_webhook_match = re.match(r"https://discord\.com/api/webhooks/(\d+)/([^/?]+)", WEBHOOK_URL)
if not _webhook_match:
    print("[에러] DISCORD_WEBHOOK_URL 형식이 올바르지 않습니다.")
    sys.exit(1)
WEBHOOK_ID, WEBHOOK_TOKEN = _webhook_match.group(1), _webhook_match.group(2)

# ==========================================================

LIST_API_URL = (
    "https://apis.naver.com/cafe-web/cafe-boardlist-api/v1/cafes/"
    "{club_id}/menus/{menu_id}/articles"
)

# 게시글 "본문"을 가져오는 상세 API (본문 안의 링크/이미지를 찾기 위해 필요)
DETAIL_API_URL = (
    "https://apis.naver.com/cafe-web/cafe-articleapi/v3/cafes/"
    "{club_id}/articles/{article_id}"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://cafe.naver.com/",
}

# 본문 안에서 "이 도메인의 링크만" 임베드용으로 찾아냅니다 (유튜브만).
YOUTUBE_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "m.youtube.com",
    "music.youtube.com",
)

URL_REGEX = re.compile(r'https?://[^\s"\'<>]+')


# ============ state.json 로드/저장 ============
# 구조:
# {
#   "last_id": 12345,
#   "articles": {
#       "12345": {
#           "title": "...", "writer": "...", "url": "...",
#           "card_message_id": "111...", "link_message_id": "222..." or null,
#           "link": "https://youtu.be/..." or null
#       },
#       ...
#   }
# }

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}
    data.setdefault("last_id", 0)
    data.setdefault("articles", {})
    return data


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def fetch_latest_articles(page_size: int = 20):
    """게시판의 최신 글 목록을 가져온다. 최신순으로 정렬된 리스트를 반환."""
    url = LIST_API_URL.format(club_id=CLUB_ID, menu_id=MENU_ID)
    params = {"page": 1, "perPage": page_size, "sortBy": "TIME"}
    headers = dict(HEADERS)
    headers["Cookie"] = COOKIE

    resp = requests.get(url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    # 네이버 API 응답 구조는 카페마다 살짝 다를 수 있어서,
    # 실제 응답을 한 번 print(data) 로 확인 후 아래 파싱 경로를 맞춰줘야 할 수 있습니다.
    articles = data.get("result", {}).get("articleList", [])

    parsed = []
    for a in articles:
        item = a.get("item", a)  # 응답 형태에 따라 item 래핑이 있을 수도/없을 수도
        writer = item.get("writerNickname") or item.get("writer", {}).get("nickName", "")
        parsed.append(
            {
                "id": item.get("articleId"),
                "title": item.get("subject"),
                "writer": writer,
                "url": f"https://cafe.naver.com/ca-fe/cafes/{CLUB_ID}/articles/{item.get('articleId')}",
            }
        )
    return parsed


def _extract_first_youtube_link(content_html: str):
    """
    본문에서 '가장 처음 나오는 링크'가 유튜브일 때만 그 링크를 반환한다.
    (첫 링크가 유튜브가 아니면, 그 아래에 유튜브 링크가 더 있어도 무시)
    """
    if not content_html:
        return None

    raw_links = URL_REGEX.findall(html.unescape(content_html))
    if not raw_links:
        return None

    first_link = raw_links[0].rstrip(').,\'"')  # 문장부호가 링크 끝에 붙어 딸려오는 경우 정리

    if any(domain in first_link for domain in YOUTUBE_DOMAINS):
        return first_link
    return None


def fetch_article_detail(article_id: int):
    """
    게시글 본문을 가져와서, 본문 안에 있는 첫 번째 외부 링크(유튜브 등)를 찾아낸다.
    카페 설정/네이버 응답 구조에 따라 필드 경로가 다를 수 있으므로,
    실패하더라도 (예외를 삼키고) 링크 없이 진행하도록 만들어져 있습니다.
    """
    url = DETAIL_API_URL.format(club_id=CLUB_ID, article_id=article_id)
    params = {
        "query": "",
        "menuId": MENU_ID,
        "boardType": "L",
        "useCafeId": "true",
        "requestFrom": "A",
    }
    headers = dict(HEADERS)
    headers["Cookie"] = COOKIE

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[경고] 게시글 상세 조회 실패 (id={article_id}): {e}")
        return {"link": None}

    article = data.get("result", {}).get("article", {})

    # 카페마다 본문 필드명이 다를 수 있어 여러 후보를 시도합니다.
    content_html = (
        article.get("contentHtml")
        or article.get("content")
        or data.get("result", {}).get("contentHtml")
        or ""
    )

    return {"link": _extract_first_youtube_link(content_html)}


# ============ 디스코드 전송/수정/삭제 ============

def _card_embed_payload(article: dict) -> dict:
    return {
        "embeds": [
            {
                "title": article["title"] or "(제목 없음)",
                "url": article["url"],
                "description": f"작성자: {article['writer']}" if article["writer"] else None,
                "color": 3447003,
            }
        ]
    }


def send_new_article(article: dict, link: Optional[str]) -> dict:
    """
    새 글을 디스코드에 보낸다. 카드(embed)와 유튜브 링크를 한 메시지에 같이 보내면
    (embeds + content 동시), 디스코드가 링크 미리보기를 잘 안 만들어주는 경우가
    많아서(디스코드 자체의 알려진 버그성 동작) 메시지 2개로 나눠서 보냅니다:
      1) 카페 글 카드(embed)
      2) 유튜브 링크만 담긴 "일반 메시지" -> 사람이 링크를 직접 붙여넣은 것과
         동일하게 취급되어 디스코드가 훨씬 안정적으로 미리보기를 만들어줍니다.

    나중에 "수정 감지"를 위해 각 메시지를 ?wait=true 로 보내서 메시지 ID를 받아둔다.
    """
    card_message_id = None
    link_message_id = None

    resp = requests.post(
        WEBHOOK_URL, params={"wait": "true"}, json=_card_embed_payload(article), timeout=10
    )
    if resp.status_code >= 300:
        print(f"[경고] 디스코드 전송 실패 ({resp.status_code}): {resp.text}")
    else:
        card_message_id = resp.json().get("id")

    if link:
        # 앞 메시지와 순서가 뒤섞이지 않도록 살짝 텀을 둡니다.
        time.sleep(1)
        link_resp = requests.post(
            WEBHOOK_URL, params={"wait": "true"}, json={"content": link}, timeout=10
        )
        if link_resp.status_code >= 300:
            print(f"[경고] 디스코드 링크 전송 실패 ({link_resp.status_code}): {link_resp.text}")
        else:
            link_message_id = link_resp.json().get("id")

    return {"card_message_id": card_message_id, "link_message_id": link_message_id}


def edit_card_message(message_id: str, article: dict) -> None:
    url = f"https://discord.com/api/webhooks/{WEBHOOK_ID}/{WEBHOOK_TOKEN}/messages/{message_id}"
    resp = requests.patch(url, json=_card_embed_payload(article), timeout=10)
    if resp.status_code >= 300:
        print(f"[경고] 디스코드 카드 수정 실패 ({resp.status_code}): {resp.text}")


def edit_link_message(message_id: str, new_link: str) -> None:
    url = f"https://discord.com/api/webhooks/{WEBHOOK_ID}/{WEBHOOK_TOKEN}/messages/{message_id}"
    resp = requests.patch(url, json={"content": new_link}, timeout=10)
    if resp.status_code >= 300:
        print(f"[경고] 디스코드 링크 메시지 수정 실패 ({resp.status_code}): {resp.text}")


def delete_message(message_id: str) -> None:
    url = f"https://discord.com/api/webhooks/{WEBHOOK_ID}/{WEBHOOK_TOKEN}/messages/{message_id}"
    resp = requests.delete(url, timeout=10)
    if resp.status_code >= 300 and resp.status_code != 404:
        print(f"[경고] 디스코드 메시지 삭제 실패 ({resp.status_code}): {resp.text}")


# ============ 메인 로직 ============

def run_once():
    state = load_state()
    last_id = state["last_id"]
    articles_state = state["articles"]

    articles = fetch_latest_articles()
    if not articles:
        print("[정보] 가져온 글이 없습니다. CLUB_ID/MENU_ID/쿠키를 확인해주세요.")
        return

    # ---- 1) 새 글 처리: 최신순 목록 -> 마지막으로 본 id보다 큰 것만, 오래된 순으로 전송 ----
    new_articles = [a for a in articles if a["id"] and a["id"] > last_id]
    new_articles.sort(key=lambda a: a["id"])

    for a in new_articles:
        print(f"[알림] 새 글 발견: {a['title']}")
        detail = fetch_article_detail(a["id"])
        link = detail.get("link")
        ids = send_new_article(a, link)
        articles_state[str(a["id"])] = {
            "title": a["title"],
            "writer": a["writer"],
            "url": a["url"],
            "card_message_id": ids["card_message_id"],
            "link_message_id": ids["link_message_id"],
            "link": link,
        }

    if new_articles:
        last_id = max(a["id"] for a in new_articles)

    # ---- 2) 제목/작성자 수정 감지 (목록 API만으로 확인 가능, 추가 호출 없음) ----
    for a in articles:
        key = str(a["id"])
        tracked = articles_state.get(key)
        if not tracked or not tracked.get("card_message_id"):
            continue
        if tracked["title"] != a["title"] or tracked["writer"] != a["writer"]:
            print(f"[알림] 제목/작성자 수정 감지: {a['title']}")
            tracked["title"] = a["title"]
            tracked["writer"] = a["writer"]
            edit_card_message(tracked["card_message_id"], a)

    # ---- 3) 최근 N개 글의 "링크(본문) 수정" 감지: 상세 API 재조회가 필요해서 개수를 제한 ----
    recent_tracked_ids = sorted(
        (a["id"] for a in articles if str(a["id"]) in articles_state),
        reverse=True,
    )[:EDIT_CHECK_COUNT]

    articles_by_id = {a["id"]: a for a in articles}

    for article_id in recent_tracked_ids:
        key = str(article_id)
        tracked = articles_state[key]
        detail = fetch_article_detail(article_id)
        new_link = detail.get("link")

        if new_link == tracked.get("link"):
            continue  # 변화 없음

        print(f"[알림] 링크 수정 감지: {tracked['title']}")
        old_link_message_id = tracked.get("link_message_id")

        if old_link_message_id and new_link:
            # 링크가 링크로 바뀜 -> 기존 링크 메시지를 수정
            edit_link_message(old_link_message_id, new_link)
        elif old_link_message_id and not new_link:
            # 링크가 사라짐 -> 기존 링크 메시지를 삭제
            delete_message(old_link_message_id)
            tracked["link_message_id"] = None
        elif not old_link_message_id and new_link:
            # 원래 링크가 없었는데 새로 생김 -> 링크 메시지를 새로 보냄
            time.sleep(1)
            link_resp = requests.post(
                WEBHOOK_URL, params={"wait": "true"}, json={"content": new_link}, timeout=10
            )
            if link_resp.status_code < 300:
                tracked["link_message_id"] = link_resp.json().get("id")
            else:
                print(f"[경고] 디스코드 링크 전송 실패 ({link_resp.status_code}): {link_resp.text}")

        tracked["link"] = new_link

    # ---- 4) state.json 정리: 지금 목록에 없는(=너무 오래된) 글 정보는 지워서 파일 크기를 유지 ----
    current_ids = {str(a["id"]) for a in articles}
    articles_state = {k: v for k, v in articles_state.items() if k in current_ids}

    state["last_id"] = last_id
    state["articles"] = articles_state
    save_state(state)

    if not new_articles:
        print("[정보] 새 글 없음. (수정 여부만 확인함)")


def main():
    print("네이버 카페 -> 디스코드 알림 봇 시작 (새 글 + 수정 감지)")
    # 첫 실행 시 과거 글이 한꺼번에 전송되는 걸 막기 위해,
    # state.json이 없으면 "현재 최신 글까지는 이미 확인한 것"으로 초기화합니다.
    # (이때는 메시지를 보낸 적이 없으니 message_id 없이 "이미 읽음" 상태로만 기록합니다.)
    if not STATE_FILE.exists():
        articles = fetch_latest_articles()
        if articles:
            state = {
                "last_id": max(a["id"] for a in articles if a["id"]),
                "articles": {
                    str(a["id"]): {
                        "title": a["title"],
                        "writer": a["writer"],
                        "url": a["url"],
                        "card_message_id": None,
                        "link_message_id": None,
                        "link": None,
                    }
                    for a in articles
                    if a["id"]
                },
            }
            save_state(state)
            print("[초기화] 현재 최신 글까지는 이미 읽은 것으로 설정했습니다.")

    while True:
        try:
            run_once()
        except Exception as e:
            print(f"[에러] {e}")
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
