"""
R.M.S 베스트 매드무비 순위 자동 업데이트
========================================
'월간 Best OF Best' 게시판을 주기적으로 확인해서, 글 본문의 '제작자 : 이름'을 세고
디스코드에 올려둔 순위 메시지(임베드)를 "수정"합니다. (새 메시지를 계속 보내지 않음)

- 처음 실행할 때: 시작 글부터 전체를 한 번 집계해서 순위 메시지를 보냅니다.
- 그다음부터: 새 베스트 글이 올라오면 그 글만 읽어서 순위를 다시 계산하고,
  순위가 바뀌었으면 같은 메시지를 수정합니다.
- 서버 폴더에 count.txt 파일을 만들면 처음부터 전부 다시 집계합니다.
  (예전 글 내용이 수정됐을 때 등)

app.py가 자동으로 불러서 알림 봇과 함께 돌아갑니다. (따로 실행할 필요 없음)

환경변수 (선택)
---------------
  RANKING_WEBHOOK_URL   순위를 올릴 채널 웹훅 (없으면 DISCORD_WEBHOOK_URL 사용)
  RANKING_MENU_ID       게시판 번호 (기본 244 = 월간 Best OF Best)
  RANKING_START_ID      이 글 번호부터 셈 (기본 82625 = 2025년 01월 베스트)
"""

import html
import json
import os
import re
import threading
import time
from collections import Counter
from pathlib import Path

import requests

# ================= 표시 설정 (여기서 바꾸면 됩니다) =================
CONTENT_TEXT = ""  # 임베드 밖 텍스트 (비워두면 없음)
EMBED_TITLE = "🏆 R.M.S 베스트 매드무비 순위 🏆"
EMBED_COLOR = 0xF1C40F  # 금색
TOP_RANKS = 5
RANK_EMOJI = {1: "🥇", 2: "🥈", 3: "🥉", 4: "🏅", 5: "🎖️"}

# 같은 사람 묶기: "다른 표기": "대표 이름"  (줄을 추가하면 됩니다)
# 대소문자만 다른 이름(OKYU / okyu, Vi / VI)은 자동으로 같은 사람으로 셉니다.
ALIASES = {
    "윳": "윳멜",
}
# ===================================================================

CLUB_ID = os.environ.get("CLUB_ID", "")
COOKIE = os.environ.get("NAVER_COOKIE", "")
MENU_ID = os.environ.get("RANKING_MENU_ID", "244")
START_ID = int(os.environ.get("RANKING_START_ID", "82625"))
WEBHOOK_URL = (os.environ.get("RANKING_WEBHOOK_URL", "") or os.environ.get("DISCORD_WEBHOOK_URL", "")).split("?")[0]

CHECK_INTERVAL_SEC = 300          # 새 글 확인 주기 (5분)
REQUEST_DELAY_SEC = 0.5
EMPTY_RECHECK_SEC = 3 * 24 * 3600  # 제작자가 아직 안 적힌 새 글은 3일 동안 다시 확인

BASE_DIR = Path(__file__).parent
STATE_FILE = BASE_DIR / "best_ranking_state.json"
REBUILD_TRIGGER = BASE_DIR / "count.txt"

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


def log(msg):
    print(f"[베스트 순위] {msg}", flush=True)


# ====================== 저장 상태 ======================
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            log("상태 파일을 읽지 못해 새로 시작합니다.")
    return {}


def save_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE_FILE)


def empty_state(message_id=None):
    return {
        "posts": {},          # 글 번호 -> 그 글의 제작자 이름 목록
        "pending": {},        # 아직 못 읽은 글 번호 -> 처음 본 시각
        "last_seen_id": 0,
        "message_id": message_id,
        "last_text": None,
    }


# ====================== 네이버 조회 ======================
def fetch_list_page(page):
    url = LIST_API_URL.format(club_id=CLUB_ID, menu_id=MENU_ID)
    resp = requests.get(url, params={"page": page, "perPage": 50, "sortBy": "TIME"},
                        headers=HEADERS, timeout=10)
    resp.raise_for_status()
    ids = []
    for a in resp.json().get("result", {}).get("articleList", []):
        aid = a.get("item", a).get("articleId")
        if aid:
            ids.append(int(aid))
    return ids


def fetch_all_ids():
    """시작 글 번호 이후의 모든 글 번호."""
    found = set()
    for page in range(1, 500):
        ids = fetch_list_page(page)
        new = {i for i in ids if i >= START_ID} - found
        found |= new
        if not ids or not new or min(ids) < START_ID:
            break
        time.sleep(REQUEST_DELAY_SEC)
    return found


def fetch_content_html(article_id):
    for url_tpl, params_tpl in DETAIL_API_CANDIDATES:
        url = url_tpl.format(club_id=CLUB_ID, article_id=article_id)
        params = {k: v.format(menu_id=MENU_ID) for k, v in params_tpl.items()}
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                continue
            data = resp.json()
        except Exception:
            continue
        result = data.get("result", data)
        article = result.get("article", {}) if isinstance(result, dict) else {}
        content = article.get("contentHtml") or article.get("content") or result.get("contentHtml")
        if content:
            return content
    return None


# ====================== 제작자 파싱 ======================
# '제작자 : 이름' 을 전부 찾음 (한 글에 여러 개면 각각). 이름이 여러 개 적힌 칸은 제외.
MAKER_REGEX = re.compile(r"제작자\s*[:：]\s*(.*?)(?=제작자\s*[:：]|$)")
MULTI_NAME = re.compile(r"[,/&、·]|\s[xX×]\s")


def extract_makers(content_html):
    text = content_html.replace("\\/", "/")
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\u200b", "").replace("\xa0", " ")
    names = []
    for line in text.split("\n"):
        for raw in MAKER_REGEX.findall(line.strip()):
            name = raw.strip()
            if name and not MULTI_NAME.search(name):
                names.append(name)
    return names


# ====================== 순위 계산 ======================
def build_ranking(posts):
    """[(등수, [이름들], 작품 수), ...] - 같은 횟수면 같은 등수로 묶음."""
    lookup = {k.strip().casefold(): v.strip() for k, v in ALIASES.items()}
    count, spellings = Counter(), {}
    for makers in posts.values():
        seen = {}
        for name in makers:
            display = lookup.get(name.casefold(), name)
            seen[display.casefold()] = display
        for key, display in seen.items():
            count[key] += 1
            spellings.setdefault(key, Counter())[display] += 1

    by_count = {}
    for key, n in count.items():
        by_count.setdefault(n, []).append(spellings[key].most_common(1)[0][0])

    ranking = []
    for rank, n in enumerate(sorted(by_count, reverse=True)[:TOP_RANKS], start=1):
        ranking.append((rank, sorted(by_count[n], key=str.casefold), n))
    return ranking


def render_description(posts):
    ranking = build_ranking(posts)
    if not ranking:
        return "아직 집계된 제작자가 없어요."
    lines = []
    for rank, names, n in ranking:
        emoji = RANK_EMOJI.get(rank, "▫️")
        lines.append(f"{emoji} **{rank}등**  {', '.join(names)}  `🎬 {n}회`")
    return "\n\n".join(lines)


# ====================== 디스코드 ======================
def build_payload(description):
    return {
        "content": CONTENT_TEXT,
        "embeds": [{
            "title": EMBED_TITLE,
            "description": description,
            "color": EMBED_COLOR,
        }],
        "allowed_mentions": {"parse": []},
    }


def publish(state):
    """순위 메시지가 없으면 새로 보내고, 있으면 수정한다. 내용이 같으면 아무것도 안 함."""
    payload = build_payload(render_description(state["posts"]))
    # 보낼 내용 전체를 비교 -> 순위든 제목/이모지 설정이든 바뀌면 수정
    text_key = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if text_key == state.get("last_text") and state.get("message_id"):
        return

    msg_id = state.get("message_id")
    if msg_id:
        resp = requests.patch(f"{WEBHOOK_URL}/messages/{msg_id}", json=payload, timeout=15)
        if resp.status_code == 404:
            log("기존 순위 메시지가 삭제돼서 새로 보냅니다.")
            msg_id = None
        elif resp.status_code >= 300:
            log(f"메시지 수정 실패 ({resp.status_code}): {resp.text[:200]}")
            return
        else:
            log("순위 메시지를 수정했습니다.")

    if not msg_id:
        resp = requests.post(WEBHOOK_URL, params={"wait": "true"}, json=payload, timeout=15)
        if resp.status_code >= 300:
            log(f"메시지 전송 실패 ({resp.status_code}): {resp.text[:200]}")
            return
        state["message_id"] = resp.json().get("id")
        log("순위 메시지를 새로 보냈습니다.")

    state["last_text"] = text_key
    save_state(state)


# ====================== 집계 ======================
def process_pending(state):
    """pending에 있는 글들을 읽어서 posts에 반영. 반영된 게 있으면 True."""
    changed = False
    now = time.time()
    for aid in sorted(state["pending"], key=int):
        first_seen = state["pending"][aid]
        content = fetch_content_html(int(aid))
        time.sleep(REQUEST_DELAY_SEC)
        if content is None:
            continue  # 네이버 에러 -> 다음에 다시
        makers = extract_makers(content)
        if not makers and first_seen and now - first_seen < EMPTY_RECHECK_SEC:
            continue  # 새 글인데 제작자가 아직 안 적혔을 수 있음 -> 다음에 다시
        state["posts"][aid] = makers
        del state["pending"][aid]
        changed = True
        if makers:
            log(f"{aid}번 글 반영: {', '.join(makers)}")
    return changed


def full_rebuild(state):
    log(f"전체 집계를 시작합니다. (게시판 {MENU_ID}, 글 번호 {START_ID}부터)")
    fresh = empty_state(state.get("message_id"))
    ids = fetch_all_ids()
    fresh["last_seen_id"] = max(ids) if ids else 0
    fresh["pending"] = {str(i): 0 for i in ids}  # 0 = 예전 글 (제작자 없어도 다시 확인 안 함)
    process_pending(fresh)
    log(f"전체 집계 완료: 글 {len(fresh['posts'])}개 (못 읽은 글 {len(fresh['pending'])}개는 나중에 다시 시도)")
    return fresh


def check_new_posts(state):
    ids = [i for i in fetch_list_page(1) if i >= START_ID]
    for i in ids:
        if i > state["last_seen_id"]:
            state["pending"].setdefault(str(i), time.time())
    if ids:
        state["last_seen_id"] = max(state["last_seen_id"], max(ids))
    return process_pending(state) if state["pending"] else False


def tick(state):
    if REBUILD_TRIGGER.exists():
        try:
            REBUILD_TRIGGER.unlink()
        except Exception:
            pass
        state = full_rebuild(state)
    elif not state.get("posts") and not state.get("last_seen_id"):
        state = full_rebuild(state)
    else:
        check_new_posts(state)
    save_state(state)
    publish(state)
    return state


def _loop():
    state = load_state() or empty_state()
    for k, v in empty_state().items():
        state.setdefault(k, v)
    while True:
        try:
            state = tick(state)
        except Exception as e:
            log(f"에러: {e}")
        time.sleep(CHECK_INTERVAL_SEC)


def start_background():
    if not (CLUB_ID and COOKIE and WEBHOOK_URL):
        log("CLUB_ID / NAVER_COOKIE / 웹훅 주소가 없어서 순위 기능을 끕니다.")
        return
    threading.Thread(target=_loop, daemon=True).start()
    log(f"시작 (게시판 {MENU_ID}, {CHECK_INTERVAL_SEC // 60}분마다 확인)")
