"""
R.M.S 베스트 매드무비 순위 봇
============================
네이버 카페 '월간 Best OF Best' 게시판을 확인해서, 디스코드에 올려둔
순위 메시지 하나를 자동으로 수정합니다. (실제 동작은 best_ranking.py)

필요한 환경변수 (호스팅 패널 또는 .env)
  CLUB_ID               카페 번호
  NAVER_COOKIE          네이버 로그인 쿠키
  DISCORD_WEBHOOK_URL   순위를 올릴 채널의 웹훅 주소
                        (RANKING_WEBHOOK_URL 이 있으면 그걸 우선 사용)
"""

import os
import sys
from pathlib import Path

# ============ .env 파일 로드 ============
ENV_FILE = Path(__file__).parent / ".env"
if ENV_FILE.exists():
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)

# ============ 필수값 확인 ============
_missing = [name for name in ("CLUB_ID", "NAVER_COOKIE") if not os.environ.get(name)]
if not (os.environ.get("RANKING_WEBHOOK_URL") or os.environ.get("DISCORD_WEBHOOK_URL")):
    _missing.append("DISCORD_WEBHOOK_URL")
if _missing:
    print(f"[에러] 환경변수가 설정되지 않았습니다: {', '.join(_missing)}")
    sys.exit(1)

import best_ranking  # noqa: E402  (.env를 먼저 읽은 뒤에 불러와야 함)

if __name__ == "__main__":
    print("R.M.S 베스트 순위 봇 시작", flush=True)
    best_ranking.run_forever()
