#!/bin/zsh
# 주간 추천·추적 루틴 (cron 등록용).
#   1) 증분 데이터 수집(가격 10d + VIX/WTI) — 분할 감지 시 자동 전체 재수집
#   2) 주간 추천 + 목표가 예보 → 텔레그램
#   3) 지난 예보 채점(추적 리포트 갱신) → 텔레그램
# 로그: data/weekly_report.log (append). 실패해도 다음 단계는 계속 진행하되
# 종료 코드로 실패를 남긴다.
#
# crontab 예(매주 수요일 07:30 KST — 미국 화요일 장 마감 데이터 반영):
#   30 7 * * 3 /Users/kyungseok.lee/workspace/dev/trade_flow/scripts/weekly_report.sh

set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1

LOG="$REPO/data/weekly_report.log"
mkdir -p "$REPO/data"
exec >> "$LOG" 2>&1

echo "=== weekly_report $(date '+%Y-%m-%d %H:%M:%S %Z') ==="

# .env 로드(텔레그램/KIS 자격증명)
if [[ -f "$REPO/.env" ]]; then
  set -a
  source "$REPO/.env"
  set +a
fi

PY="$REPO/.venv/bin/python"
run_status=0

echo "--- [1/3] 데이터 수집(증분) ---"
"$PY" scripts/collect.py --period 10d || { echo "수집 실패(exit $?)"; run_status=1; }

echo "--- [2/3] 주간 추천 + 목표가 예보 ---"
"$PY" scripts/recommend.py --top 10 --telegram || { echo "추천 실패(exit $?)"; run_status=1; }

echo "--- [3/3] 예보 채점(추적 리포트) ---"
"$PY" scripts/track_recommendations.py --telegram || { echo "추적 실패(exit $?)"; run_status=1; }

echo "=== 완료 run_status=$run_status $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
exit $run_status
