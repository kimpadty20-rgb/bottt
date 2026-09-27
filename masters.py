"""
R.M.S 마스터 목록 자동 업데이트
===============================
마스터 게시판(658번)의 글 제목에서 이름을 읽어, 디스코드에 올려둔
마스터 목록 메시지 하나를 수정합니다. 최신 마스터가 맨 위에 옵니다.

제목 형식:  [마스터] 김원짱        -> 김원짱
           [마스터] 인수달, 김페드  -> 인수달, 김페드 (한 줄로 표시)
           [1대 명예회원] RAY      -> RAY · 1대 명예회원
([ ] 로 시작하지 않는 글(공지 등)은 넣지 않습니다.)

app.py가 실행합니다. (따로 실행할 필요 없음)

환경변수 (선택)
---------------
  MASTER_WEBHOOK_URL   목록을 올릴 채널 웹훅 (없으면 DISCORD_WEBHOOK_URL 사용)
  MASTER_MENU_ID       게시판 번호 (기본 658)
"""

import html
import json
import os
import re
import threading
import time
from pathlib import Path

import requests

# ================= 표시 설정 (여기서 바꾸면 됩니다) =================
EMBED_TITLE = "👑 R.M.S 마스터 👑"
EMBED_COLOR = 0x9B59B6  # 보라색
LINE_EMOJI = "👑"        # 이름 앞 이모지
MAIN_TAG = "마스터"      # 이 말머리는 따로 표시하지 않음 (다른 말머리는 이름 옆에 표시)
# ===================================================================

CLUB_ID = os.environ.get("CLUB_ID", "")
COOKIE = os.environ.get("NAVER_COOKIE", "")
MENU_ID = os.environ.get("MASTER_MENU_ID", "658")
WEBHOOK_URL = (os.environ.get("MASTER_WEBHOOK_URL", "") or os.environ.get("DISCORD_WEBHOOK_URL", "")).split("?")[0]

STARTUP_DELAY_SEC = int(os.environ.get("RANKING_STARTUP_SEC", "30"))
CHECK_INTERVAL_SEC = int(os.environ.get("RANKING_CHECK_SEC", "30"))
STATE_FILE = Path(__file__).parent / "masters_state.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://cafe.naver.com/",
    "Cookie": COOKIE,
}
LIST_API_URL = (
    "https://apis.naver.com/cafe-web/cafe-boardlist-api/v1/cafes/"
    "{club_id}/menus/{menu_id}/articles"
)
TITLE_REGEX = re.compile(r"^\s*\[([^\]]+)\]\s*(.+?)\s*$")


def log(msg):
    print(f"[마스터 목록] {msg}", flush=True)


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"message_id": None, "last_text": None}


def save_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_FILE)


# ====================== 게시판 읽기 ======================
def fetch_all_titles():
    """{글 번호: 제목} - 게시판 전체 (마스터 게시판은 글이 적어서 매번 전부 읽음)"""
    url = LIST_API_URL.format(club_id=CLUB_ID, menu_id=MENU_ID)
    titles = {}
    for page in range(1, 50):
        resp = requests.get(url, params={"page": page, "perPage": 50, "sortBy": "TIME"},
                            headers=HEADERS, timeout=10)
        resp.raise_for_status()
        items = resp.json().get("result", {}).get("articleList", [])
        new = 0
        for a in items:
            item = a.get("item", a)
            aid = item.get("articleId")
            if aid and aid not in titles:
                titles[int(aid)] = html.unescape(item.get("subject") or "")
                new += 1
        if not items or new == 0:
            break
        time.sleep(0.5)
    return titles


def parse_title(title):
    """'[마스터] 김원짱' -> '김원짱', '[1대 명예회원] RAY' -> 'RAY · 1대 명예회원'. 형식이 아니면 None."""
    m = TITLE_REGEX.match(title)
    if not m:
        return None
    tag, name = m.group(1).strip(), m.group(2).strip()
    if not name:
        return None
    return name if tag == MAIN_TAG else f"{name} · {tag}"


def render_description(titles):
    entries = []
    for aid in sorted(titles, reverse=True):  # 최신 글이 위로
        entry = parse_title(titles[aid])
        if entry:
            entries.append(entry)
    if not entries:
        return "아직 등록된 마스터가 없어요."
    return "\n\n".join(f"{LINE_EMOJI} {e}" for e in entries)


# ====================== 디스코드 ======================
def build_payload(description):
    return {
        "content": "",
        "embeds": [{"title": EMBED_TITLE, "description": description[:4000], "color": EMBED_COLOR}],
        "allowed_mentions": {"parse": []},
    }


def message_exists(msg_id):
    try:
        return requests.get(f"{WEBHOOK_URL}/messages/{msg_id}", timeout=15).status_code != 404
    except Exception:
        return True


def publish(state, payload, verify=False):
    text_key = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if verify and state.get("message_id") and not message_exists(state["message_id"]):
        log("디스코드에서 목록 메시지가 지워져 있어서 새로 보냅니다.")
        state["message_id"] = None
    if text_key == state.get("last_text") and state.get("message_id"):
        return

    msg_id = state.get("message_id")
    if msg_id:
        resp = requests.patch(f"{WEBHOOK_URL}/messages/{msg_id}", json=payload, timeout=15)
        if resp.status_code == 404:
            msg_id = None
        elif resp.status_code >= 300:
            log(f"메시지 수정 실패 ({resp.status_code}): {resp.text[:200]}")
            return
        else:
            log("목록 메시지를 수정했습니다.")
    if not msg_id:
        resp = requests.post(WEBHOOK_URL, params={"wait": "true"}, json=payload, timeout=15)
        if resp.status_code >= 300:
            log(f"메시지 전송 실패 ({resp.status_code}): {resp.text[:200]}")
            return
        state["message_id"] = resp.json().get("id")
        log("목록 메시지를 새로 보냈습니다.")
    state["last_text"] = text_key
    save_state(state)


# ====================== 실행 ======================
def tick(state, verify=False):
    titles = fetch_all_titles()
    if not titles:
        return  # 목록을 못 읽었을 때 빈 목록으로 덮어쓰지 않도록
    publish(state, build_payload(render_description(titles)), verify=verify)


def _loop():
    state = load_state()
    time.sleep(STARTUP_DELAY_SEC)
    checks = 0
    while True:
        try:
            verify = checks % max(1, 600 // CHECK_INTERVAL_SEC) == 0
            tick(state, verify=verify)
        except Exception as e:
            log(f"에러: {e}")
        checks += 1
        time.sleep(CHECK_INTERVAL_SEC)


def start_background():
    if not (CLUB_ID and COOKIE and WEBHOOK_URL):
        log("CLUB_ID / NAVER_COOKIE / 웹훅 주소가 없어서 마스터 목록 기능을 끕니다.")
        return
    threading.Thread(target=_loop, daemon=True).start()
    log(f"시작 (게시판 {MENU_ID}, {CHECK_INTERVAL_SEC}초마다 확인)")
