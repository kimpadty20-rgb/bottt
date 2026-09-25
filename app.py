"""
네이버 카페(회원전용 게시판) 새 글 -> 디스코드 웹훅 알림 봇
=================================================

동작 방식
---------
1. 네이버에 "로그인된 상태의 쿠키"를 그대로 재사용해서, 회원 전용 게시판의
   글 목록 API를 주기적으로 조회합니다.
2. 직전에 저장해둔 "마지막으로 본 글 번호"보다 새 글 번호가 있으면
   -> 글 상세 API를 한 번 더 호출해서 본문 안에 있는 링크(유튜브 등)를 찾고
   -> 디스코드 웹훅으로 메시지를 보냅니다. 이때 링크는 메시지 본문(content)에
      그대로 넣어서, 디스코드가 자동으로 미리보기(임베드)를 만들어주게 합니다.
3. 마지막 글 번호를 로컬 파일(state.json)에 저장해두고, 다음 실행 때 이어서 비교합니다.

설정값은 코드에 직접 쓰지 않고 "환경변수"로 넣습니다 (보안 때문).
호스팅 패널에서 아래 4개의 환경변수를 등록해주세요:

  CLUB_ID
  MENU_ID
  NAVER_COOKIE
  DISCORD_WEBHOOK_URL

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
    python app.py

  (Mac/Linux)
    export CLUB_ID=11830253
    export MENU_ID=39
    export NAVER_COOKIE="NID_AUT=...; NID_SES=..."
    export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
    python3 app.py

실행 방법
---------
1) 파이썬 3.9+ 설치
2) pip install -r requirements.txt   (requests 필요)
3) 위 4가지 환경변수 설정 (또는 이 파일과 같은 폴더에 .env 파일 작성)
4) python app.py
"""

import html
import json
import os
import re
import sys
import time
from pathlib import Path

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
STATE_FILE = Path(__file__).parent / "state.json"

# ==========================================================

LIST_API_URL = (
    "https://apis.naver.com/cafe-web/cafe-boardlist-api/v1/cafes/"
    "{club_id}/menus/{menu_id}/articles"
)

# 게시글 "본문"을 가져오는 상세 API (본문 안의 링크/이미지를 찾기 위해 필요)
# 네이버가 한쪽 주소에서 에러(500 등)를 내는 경우가 있어, 여러 주소/파라미터 조합을
# 순서대로 시도합니다. 하나라도 성공하면 그 결과를 사용합니다.
DETAIL_API_CANDIDATES = [
    (
        "https://apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/{club_id}/articles/{article_id}",
        {"query": "", "useCafeId": "true", "requestFrom": "A"},
    ),
    (
        "https://apis.naver.com/cafe-web/cafe-articleapi/v3/cafes/{club_id}/articles/{article_id}",
        {"query": "", "useCafeId": "true", "requestFrom": "A"},
    ),
    (
        "https://apis.naver.com/cafe-web/cafe-articleapi/v3/cafes/{club_id}/articles/{article_id}",
        {"query": "", "menuId": "{menu_id}", "boardType": "L", "useCafeId": "true", "requestFrom": "A"},
    ),
]
DETAIL_RETRY_ROUNDS = 2      # 전체 후보를 몇 바퀴 시도할지
DETAIL_RETRY_WAIT_SEC = 5    # 바퀴 사이 대기 시간 (글 등록 직후 일시적 에러 대비)

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


def load_last_seen_id() -> int:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8")).get("last_id", 0)
        except Exception:
            return 0
    return 0


def save_last_seen_id(article_id: int) -> None:
    STATE_FILE.write_text(json.dumps({"last_id": article_id}), encoding="utf-8")


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


# 이 문구 뒤에 오는 링크만 가져옵니다 (띄어쓰기/대소문자 차이는 허용)
LABEL_REGEX = re.compile(r"영상\s*링크\s*or\s*영상", re.IGNORECASE)
IGNORE_DOMAINS = ("pstatic.net", "naver.com", "naver.net")
SEARCH_RANGE = 300  # 문구 뒤 몇 글자 안에서 링크를 찾을지


def _extract_first_youtube_link(content_html: str):
    """
    본문에서 '영상 링크 or 영상-' 문구 바로 뒤에 있는 유튜브 링크를 반환한다.
    문구가 없거나, 문구 뒤 첫 링크가 유튜브가 아니면 None.
    """
    if not content_html:
        return None

    text = html.unescape(content_html).replace("\\/", "/")
    # <a href="링크"> 의 링크 주소는 살리고, 나머지 HTML 태그는 제거
    text = re.sub(r'<a\b[^>]*?href="([^"]+)"[^>]*>', r" \1 ", text)
    text = re.sub(r"<[^>]+>", " ", text)

    match = LABEL_REGEX.search(text)
    if not match:
        return None

    after_label = text[match.end(): match.end() + SEARCH_RANGE]
    for raw in URL_REGEX.findall(after_label):
        link = raw.rstrip(").,'\"")
        if any(d in link for d in IGNORE_DOMAINS):
            continue  # 네이버 내부 링크는 건너뜀
        if any(d in link for d in YOUTUBE_DOMAINS):
            return link
        return None  # 문구 뒤 첫 링크가 유튜브가 아니면 무시
    return None


def _request_article_json(article_id: int):
    """상세 API 후보들을 순서대로 시도해서, 처음 성공한 JSON 응답을 반환. 전부 실패하면 None."""
    headers = dict(HEADERS)
    headers["Cookie"] = COOKIE

    for round_no in range(1, DETAIL_RETRY_ROUNDS + 1):
        for url_tpl, params_tpl in DETAIL_API_CANDIDATES:
            url = url_tpl.format(club_id=CLUB_ID, article_id=article_id)
            params = {k: v.format(menu_id=MENU_ID) for k, v in params_tpl.items()}
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=10)
                if resp.status_code == 200:
                    return resp.json()
                print(
                    f"[경고] 상세 조회 실패 (id={article_id}, {resp.status_code}) "
                    f"{url.split('/cafe-articleapi/')[1].split('/')[0]}: {resp.text[:200]}"
                )
            except Exception as e:
                print(f"[경고] 상세 조회 에러 (id={article_id}): {e}")
        if round_no < DETAIL_RETRY_ROUNDS:
            time.sleep(DETAIL_RETRY_WAIT_SEC)
    return None


def fetch_article_detail(article_id: int):
    """
    게시글 본문을 가져와서, '영상 링크 or 영상-' 문구 뒤의 유튜브 링크를 찾아낸다.
    실패하더라도 (예외를 삼키고) 링크 없이 진행하도록 만들어져 있습니다.
    """
    data = _request_article_json(article_id)
    if data is None:
        print(f"[경고] 게시글 상세 조회 최종 실패 (id={article_id}) -> 링크 없이 전송합니다.")
        return {"link": None}

    result = data.get("result", data)
    article = result.get("article", {}) if isinstance(result, dict) else {}

    # 버전/카페마다 본문 필드명이 다를 수 있어 여러 후보를 시도합니다.
    content_html = (
        article.get("contentHtml")
        or article.get("content")
        or result.get("contentHtml")
        or ""
    )
    if not content_html:
        print(f"[경고] 본문을 찾지 못했습니다 (id={article_id}). 응답 키: {list(result.keys())[:15]}")

    return {"link": _extract_first_youtube_link(content_html)}


def send_to_discord(article: dict, extra_link: str | None) -> None:
    # 카드(embed)와 유튜브 링크를 한 메시지에 같이 보내면(embeds + content 동시),
    # 디스코드가 링크 미리보기를 잘 안 만들어주는 경우가 많습니다(디스코드 자체의
    # 알려진 버그성 동작). 그래서 아래처럼 메시지 2개로 나눠서 보냅니다:
    #   1) 카페 글 카드(embed)
    #   2) 유튜브 링크만 담긴 "일반 메시지" -> 사람이 링크를 직접 붙여넣은 것과
    #      동일하게 취급되어 디스코드가 훨씬 안정적으로 미리보기를 만들어줍니다.

    card_payload = {
        "embeds": [
            {
                "title": article["title"] or "(제목 없음)",
                "url": article["url"],
                "description": f"작성자: {article['writer']}" if article["writer"] else None,
                "color": 3447003,
            }
        ]
    }
    resp = requests.post(WEBHOOK_URL, json=card_payload, timeout=10)
    if resp.status_code >= 300:
        print(f"[경고] 디스코드 전송 실패 ({resp.status_code}): {resp.text}")

    if extra_link:
        # 앞 메시지와 순서가 뒤섞이지 않도록 살짝 텀을 둡니다.
        time.sleep(1)
        link_resp = requests.post(WEBHOOK_URL, json={"content": extra_link}, timeout=10)
        if link_resp.status_code >= 300:
            print(f"[경고] 디스코드 링크 전송 실패 ({link_resp.status_code}): {link_resp.text}")


def run_once():
    last_id = load_last_seen_id()
    articles = fetch_latest_articles()

    if not articles:
        print("[정보] 가져온 글이 없습니다. CLUB_ID/MENU_ID/쿠키를 확인해주세요.")
        return

    # 최신순 목록 -> 마지막으로 본 id보다 큰 것만 골라서, 오래된 순으로 전송
    new_articles = [a for a in articles if a["id"] and a["id"] > last_id]
    new_articles.sort(key=lambda a: a["id"])

    if not new_articles:
        print("[정보] 새 글 없음.")
        return

    for a in new_articles:
        print(f"[알림] 새 글 발견: {a['title']}")
        detail = fetch_article_detail(a["id"])
        send_to_discord(a, detail.get("link"))

    save_last_seen_id(max(a["id"] for a in new_articles))


def main():
    print("네이버 카페 -> 디스코드 알림 봇 시작")
    # 첫 실행 시 과거 글이 한꺼번에 전송되는 걸 막기 위해,
    # state.json이 없으면 "현재 최신 글까지는 이미 확인한 것"으로 초기화합니다.
    if not STATE_FILE.exists():
        articles = fetch_latest_articles()
        if articles:
            save_last_seen_id(max(a["id"] for a in articles if a["id"]))
            print("[초기화] 현재 최신 글까지는 이미 읽은 것으로 설정했습니다.")

    while True:
        try:
            run_once()
        except Exception as e:
            print(f"[에러] {e}")
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
