"""
네이버 카페(회원전용 게시판) 새 글 -> 디스코드 웹훅 알림 봇
=================================================

동작 방식
---------
1. 네이버에 "로그인된 상태의 쿠키"를 그대로 재사용해서, 회원 전용 게시판의
   글 목록 API를 주기적으로 조회합니다.
2. 직전에 저장해둔 "마지막으로 본 글 번호"보다 새 글 번호가 있으면
   -> 디스코드 웹훅으로 메시지를 보냅니다.
3. 마지막 글 번호를 로컬 파일(state.json)에 저장해두고, 다음 실행 때 이어서 비교합니다.

설정값은 코드에 직접 쓰지 않고 "환경변수"로 넣습니다 (보안 때문).
호스팅 패널에서 아래 4개의 환경변수를 등록해주세요:

  CLUB_ID: 11830253
  MENU_ID: 39
  NAVER_COOKIE: NID_AUT=ZaSjBzaUqMfCj75itxnOW7d4n/SQ2Opweu/FoXViJWaP8h10/Itz64nroYhAO14P; NID_SES=AAABt1noCAN6AVQNfe+1lpv5Rw4lcB3i/N5CUcU1erSDHDxesVUbNUCHROtkuJcc8MyLzzK6lpDJbT94Q4DnEqPnq0wgY/7EsBB4KqPNdBgZaVMAlOsm7rTRV87zuZXLEBaw0wYGmkwdObi3BahQkbC099f8lULt7yPHPMQ1abg0ymb038Kvd4WoHtEv3UmjhEBppmi39AQyIYSndnu/vq/8d5BWPP445bJ9HMNElM4ywUpcuAlN5Z4/yJjmgHlo54B+6gw1zno3WAJx+ULPmD2bFtsTTwqJgmYSGWv1YxhlH75B9XdDH6hLdSHVhahbMENpIAmmKoP2erm5WTBMBO+GotO872aUnxL6ndrT0WIBiw4vl6EixUSTUD5J0hVHbkCY//J3w86XzDsJYX+6fozws94XrEd2rGQSaFa44fTYPhZYhlmj9o2GfN93mS141oGVRCUAFlHYy7iETG3/tFvZdUTymjKwKIVcXYI5Mf39yIP/xxCUqMXo5RnDR/nYKaobxjPQTUBBbTWOckFDDmU7uuDEB2ecDcZSUv+plByeb32X5/w93YDUw1XHcCGV3nh+A92gKcVkv8YVVeSzZZZPHZM=
  DISCORD_WEBHOOK_URL: https://discord.com/api/webhooks/1540361850758365184/W-JjbLSDtdF3CZPHTazmX38DoS_2U7_uXjtC4caVK5X6c79AZ8h4QAtUptP-ctWvA3W2

로컬 PC에서 테스트할 때는 터미널에서 아래처럼 실행하면 됩니다:

  (Windows, PowerShell)
    $env:CLUB_ID="11830253"
    $env:MENU_ID="39"
    $env:NAVER_COOKIE="NID_AUT=ZaSjBzaUqMfCj75itxnOW7d4n/SQ2Opweu/FoXViJWaP8h10/Itz64nroYhAO14P; NID_SES=AAABt1noCAN6AVQNfe+1lpv5Rw4lcB3i/N5CUcU1erSDHDxesVUbNUCHROtkuJcc8MyLzzK6lpDJbT94Q4DnEqPnq0wgY/7EsBB4KqPNdBgZaVMAlOsm7rTRV87zuZXLEBaw0wYGmkwdObi3BahQkbC099f8lULt7yPHPMQ1abg0ymb038Kvd4WoHtEv3UmjhEBppmi39AQyIYSndnu/vq/8d5BWPP445bJ9HMNElM4ywUpcuAlN5Z4/yJjmgHlo54B+6gw1zno3WAJx+ULPmD2bFtsTTwqJgmYSGWv1YxhlH75B9XdDH6hLdSHVhahbMENpIAmmKoP2erm5WTBMBO+GotO872aUnxL6ndrT0WIBiw4vl6EixUSTUD5J0hVHbkCY//J3w86XzDsJYX+6fozws94XrEd2rGQSaFa44fTYPhZYhlmj9o2GfN93mS141oGVRCUAFlHYy7iETG3/tFvZdUTymjKwKIVcXYI5Mf39yIP/xxCUqMXo5RnDR/nYKaobxjPQTUBBbTWOckFDDmU7uuDEB2ecDcZSUv+plByeb32X5/w93YDUw1XHcCGV3nh+A92gKcVkv8YVVeSzZZZPHZM="
    $env:DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/1540361850758365184/W-JjbLSDtdF3CZPHTazmX38DoS_2U7_uXjtC4caVK5X6c79AZ8h4QAtUptP-ctWvA3W2"
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
2) pip install -r requirements.txt
3) 위 4가지 환경변수 설정
4) python naver_cafe_discord_bot.py
"""

import json
import os
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

POLL_INTERVAL_SEC = int(os.environ.get("POLL_INTERVAL_SEC", "300"))  # 몇 초마다 확인할지
STATE_FILE = Path(__file__).parent / "state.json"

# ==========================================================

API_URL = (
    "https://apis.naver.com/cafe-web/cafe-boardlist-api/v1/cafes/"
    "{club_id}/menus/{menu_id}/articles"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://cafe.naver.com/",
}


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
    url = API_URL.format(club_id=CLUB_ID, menu_id=MENU_ID)
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


def send_to_discord(article: dict) -> None:
    payload = {
        "embeds": [
            {
                "title": article["title"] or "(제목 없음)",
                "url": article["url"],
                "description": f"작성자: {article['writer']}" if article["writer"] else None,
                "color": 3447003,
            }
        ]
    }
    resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
    if resp.status_code >= 300:
        print(f"[경고] 디스코드 전송 실패 ({resp.status_code}): {resp.text}")


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
        send_to_discord(a)

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
