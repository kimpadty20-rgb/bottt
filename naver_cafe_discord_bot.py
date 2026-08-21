"""
네이버 카페(회원전용 게시판) 새 글 -> 디스코드 웹훅 알림 봇
=================================================

동작 방식
---------
1. 네이버에 "로그인된 상태의 쿠키"를 그대로 재사용해서, 회원 전용 게시판의
   글 목록 API를 주기적으로 조회합니다. (아이디/비번으로 직접 로그인하지 않습니다 -
   캡차 등으로 자동 로그인이 막혀 있어서, 브라우저에서 로그인한 쿠키를 복사해서 쓰는
   방식이 훨씬 안정적입니다.)
2. 직전에 저장해둔 "마지막으로 본 글 번호"보다 새 글 번호가 있으면
   -> 디스코드 웹훅으로 메시지를 보냅니다.
3. 마지막 글 번호를 로컬 파일(state.json)에 저장해두고, 다음 실행 때 이어서 비교합니다.

필요한 값 4가지 (아래 CONFIG 부분을 채워주세요)
------------------------------------------------
1) CLUB_ID   : 11830253
2) MENU_ID   : 39
3) COOKIE    : NID_AUT=ZaSjBzaUqMfCj75itxnOW7d4n/SQ2Opweu/FoXViJWaP8h10/Itz64nroYhAO14P; NID_SES=AAABt1noCAN6AVQNfe+1lpv5Rw4lcB3i/N5CUcU1erSDHDxesVUbNUCHROtkuJcc8MyLzzK6lpDJbT94Q4DnEqPnq0wgY/7EsBB4KqPNdBgZaVMAlOsm7rTRV87zuZXLEBaw0wYGmkwdObi3BahQkbC099f8lULt7yPHPMQ1abg0ymb038Kvd4WoHtEv3UmjhEBppmi39AQyIYSndnu/vq/8d5BWPP445bJ9HMNElM4ywUpcuAlN5Z4/yJjmgHlo54B+6gw1zno3WAJx+ULPmD2bFtsTTwqJgmYSGWv1YxhlH75B9XdDH6hLdSHVhahbMENpIAmmKoP2erm5WTBMBO+GotO872aUnxL6ndrT0WIBiw4vl6EixUSTUD5J0hVHbkCY//J3w86XzDsJYX+6fozws94XrEd2rGQSaFa44fTYPhZYhlmj9o2GfN93mS141oGVRCUAFlHYy7iETG3/tFvZdUTymjKwKIVcXYI5Mf39yIP/xxCUqMXo5RnDR/nYKaobxjPQTUBBbTWOckFDDmU7uuDEB2ecDcZSUv+plByeb32X5/w93YDUw1XHcCGV3nh+A92gKcVkv8YVVeSzZZZPHZM=
4) WEBHOOK_URL : https://discord.com/api/webhooks/1540361850758365184/W-JjbLSDtdF3CZPHTazmX38DoS_2U7_uXjtC4caVK5X6c79AZ8h4QAtUptP-ctWvA3W2

값 찾는 방법은 대화창에서 안내한 단계별 가이드를 참고하세요.

실행 방법
---------
1) 파이썬 3.9+ 설치
2) pip install requests
3) 아래 CONFIG 값 채우기
4) python naver_cafe_discord_bot.py

계속 켜두고 싶다면 (24시간 감시)
-------------------------------
- 그냥 이 스크립트를 터미널에서 실행한 채로 두면 while 루프가 계속 돌면서
  POLL_INTERVAL_SEC 마다 새 글을 확인합니다.
- 나중에 PC를 끄지 않는 서버(또는 클라우드 VM, 라즈베리파이 등)에 올려서
  똑같이 실행해두면 24시간 감시가 됩니다. (nohup, systemd, screen, tmux 등으로
  백그라운드 실행하는 걸 추천합니다.)
"""

import json
import time
from pathlib import Path

import requests

# ============ CONFIG: 여기 4가지를 채워주세요 ============

CLUB_ID = "11830253"          # 예: "12345678"
MENU_ID = "39"       # 예: "1"
COOKIE = "NID_AUT=ZaSjBzaUqMfCj75itxnOW7d4n/SQ2Opweu/FoXViJWaP8h10/Itz64nroYhAO14P; NID_SES=AAABt1noCAN6AVQNfe+1lpv5Rw4lcB3i/N5CUcU1erSDHDxesVUbNUCHROtkuJcc8MyLzzK6lpDJbT94Q4DnEqPnq0wgY/7EsBB4KqPNdBgZaVMAlOsm7rTRV87zuZXLEBaw0wYGmkwdObi3BahQkbC099f8lULt7yPHPMQ1abg0ymb038Kvd4WoHtEv3UmjhEBppmi39AQyIYSndnu/vq/8d5BWPP445bJ9HMNElM4ywUpcuAlN5Z4/yJjmgHlo54B+6gw1zno3WAJx+ULPmD2bFtsTTwqJgmYSGWv1YxhlH75B9XdDH6hLdSHVhahbMENpIAmmKoP2erm5WTBMBO+GotO872aUnxL6ndrT0WIBiw4vl6EixUSTUD5J0hVHbkCY//J3w86XzDsJYX+6fozws94XrEd2rGQSaFa44fTYPhZYhlmj9o2GfN93mS141oGVRCUAFlHYy7iETG3/tFvZdUTymjKwKIVcXYI5Mf39yIP/xxCUqMXo5RnDR/nYKaobxjPQTUBBbTWOckFDDmU7uuDEB2ecDcZSUv+plByeb32X5/w93YDUw1XHcCGV3nh+A92gKcVkv8YVVeSzZZZPHZM="     # 예: "NID_AUT=xxxx; NID_SES=yyyy"
WEBHOOK_URL = "https://discord.com/api/webhooks/1540361850758365184/W-JjbLSDtdF3CZPHTazmX38DoS_2U7_uXjtC4caVK5X6c79AZ8h4QAtUptP-ctWvA3W2"  # 예: "https://discord.com/api/webhooks/..."

POLL_INTERVAL_SEC = 300  # 몇 초마다 확인할지 (300초 = 5분)
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
    "Referer": f"https://cafe.naver.com/",
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

    # 네이버 API 응답 구조는 examples에 따라 살짝 다를 수 있어서,
    # 실제 응답을 한 번 print(data) 로 확인 후 아래 파싱 경로를 맞춰줘야 할 수 있습니다.
    articles = data.get("result", {}).get("articleList", [])

    parsed = []
    for a in articles:
        item = a.get("item", a)  # 응답 형태에 따라 item 래핑이 있을 수도/없을 수도
        parsed.append(
            {
                "id": item.get("articleId"),
                "title": item.get("subject"),
                "writer": item.get("writerNickname") or item.get("writer", {}).get("nickName", ""),
                "url": (
                    f"https://cafe.naver.com/{CLUB_URL_NAME}/{item.get('articleId')}"
                    if "CLUB_URL_NAME" in globals()
                    else f"https://cafe.naver.com/ca-fe/cafes/{CLUB_ID}/articles/{item.get('articleId')}"
                ),
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
