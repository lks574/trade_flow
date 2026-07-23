#!/bin/zsh
# 일일 루틴 (평일 07:10 KST, cron 등록용).
#   [무음]  1) 증분 데이터 수집  2) 추천 스냅샷 저장  3) 예보 채점(문서 갱신)
#   [텔레그램] 4) 계좌 손절 점검  5) 세계 정세·큰손 동향 다이제스트(claude 헤드리스)
#   실패한 단계는 텔레그램 critical 경보로 전달한다(API 깨짐 조기 발견).
#
# crontab 예: 10 7 * * 1-5 /Users/kyungseok.lee/workspace/dev/trade_flow/scripts/daily_routine.sh

set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1

LOG="$REPO/data/daily_routine.log"
mkdir -p "$REPO/data"
exec >> "$LOG" 2>&1

echo "=== daily_routine $(date '+%Y-%m-%d %H:%M:%S %Z') ==="

if [[ -f "$REPO/.env" ]]; then
  set -a
  source "$REPO/.env"
  set +a
fi

PY="$REPO/.venv/bin/python"
CLAUDE_BIN="${CLAUDE_BIN:-$HOME/.local/bin/claude}"
run_status=0

alert() {  # alert <단계이름> <메시지>
  echo "경보: $1 — $2"
  print -r -- "$2" | "$PY" scripts/send_telegram.py --subject "일일 루틴 경보: $1" --severity critical
}

echo "--- [1/5] 데이터 수집(증분, 무음) ---"
"$PY" scripts/collect.py --period 10d || { alert "데이터 수집" "collect.py 실패(exit $?). 로그: data/daily_routine.log"; run_status=1; }

echo "--- [2/5] 추천 스냅샷 저장(무음) ---"
"$PY" scripts/recommend.py --top 10 --no-fundamentals || { alert "추천 스냅샷" "recommend.py 실패(exit $?)"; run_status=1; }

echo "--- [3/5] 예보 채점(무음) ---"
"$PY" scripts/track_recommendations.py || { alert "예보 채점" "track_recommendations.py 실패(exit $?)"; run_status=1; }

echo "--- [4/5] 계좌 손절 점검(텔레그램) ---"
"$PY" scripts/daily_check.py --telegram || run_status=1  # KIS 오류는 스크립트가 자체 경보

echo "--- [5/5] 세계 정세·큰손 동향 다이제스트(claude 헤드리스, 텔레그램) ---"
DIGEST_PROMPT="오늘($(date '+%Y-%m-%d')) 미국 증시 관점에서 다음을 한국어로 간결하게 정리해줘. 웹 검색으로 최신 정보를 확인하고, 사실만 담백하게 쓸 것(투자 권유·과장 금지):
1) 세계 정세·매크로 (3~5줄): 지정학(미-이란 등)·유가·금리·주요 경제지표 중 오늘 시장에 실제 영향 있는 것만
2) 주식 큰손 동향 (3줄 이내): 주요 기관·유명 투자자·대규모 내부자 매매 중 오늘 보도된 것. 없으면 '특이사항 없음'
각 항목에 근거(매체명)를 괄호로 표기. 전체 15줄 이내."
DIGEST="$("$CLAUDE_BIN" -p "$DIGEST_PROMPT" --allowedTools "WebSearch" 2>>"$LOG")"
if [[ -n "$DIGEST" ]]; then
  print -r -- "$DIGEST" | "$PY" scripts/send_telegram.py --subject "오늘의 정세·큰손 동향" --severity info \
    || { alert "다이제스트 전송" "텔레그램 전송 실패"; run_status=1; }
else
  alert "다이제스트 생성" "claude 헤드리스 호출이 빈 응답을 반환"
  run_status=1
fi

echo "=== 완료 run_status=$run_status $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
exit $run_status
