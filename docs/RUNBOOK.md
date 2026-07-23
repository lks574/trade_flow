# trade_flow 운영 런북

언제든 각 구성요소를 수동으로 실행·테스트할 수 있는 명령어 모음.
모든 명령은 리포 루트(`~/workspace/dev/trade_flow`)에서 실행한다.

## 0. 사전 준비 (모든 명령의 공통 전제)

```bash
cd ~/workspace/dev/trade_flow
set -a && source .env && set +a     # KIS·텔레그램 자격증명 로드
```

`.env` 필수 키: `KIS_ENV`(mock/real), `KIS_MOCK_*`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

---

## 1. 자동 루틴 (cron)

| 루틴 | 시각 | 스크립트 | 내용 |
|---|---|---|---|
| 일일 | 평일 10:10 KST | `scripts/daily_routine.sh` | 수집→추천 스냅샷→채점(무음) + 계좌 손절 점검·정세 다이제스트(텔레그램) |
| 주간 | 수요일 10:30 KST | `scripts/weekly_report.sh` | 수집→추천+목표가 예보(텔레그램)→예보 채점(텔레그램) |

### cron 등록 (전체 교체, 한 줄)

```bash
printf '%s\n' \
  "30 10 * * 3 $HOME/workspace/dev/trade_flow/scripts/weekly_report.sh" \
  "10 10 * * 1-5 $HOME/workspace/dev/trade_flow/scripts/daily_routine.sh" | crontab -
crontab -l   # 확인
```

- 해제: `crontab -e`에서 해당 줄 삭제 (또는 `crontab -r`로 전체 삭제)
- **주의**: 실행 시각에 Mac이 잠자기면 건너뜀. 자동 기상 등록:
  `sudo pmset repeat wakeorpoweron MTWRF 10:05:00`
- 루틴은 멱등 — 놓친 주는 수동 실행으로 보충 가능

### 루틴 수동 실행 (cron과 동일 동작)

```bash
scripts/daily_routine.sh    # 로그: data/daily_routine.log
scripts/weekly_report.sh    # 로그: data/weekly_report.log
```

---

## 2. 구성요소별 수동 테스트

### 2.1 텔레그램 연결 테스트

```bash
echo "연결 테스트" | .venv/bin/python scripts/send_telegram.py --subject "테스트"
# DeliveryResult(delivered=True, ...) 가 나오면 정상
```

### 2.2 주간 추천 + 목표가 예보

```bash
.venv/bin/python scripts/recommend.py --top 10                    # 콘솔만 (DB 저장 포함)
.venv/bin/python scripts/recommend.py --top 10 --telegram         # + 텔레그램 발송
.venv/bin/python scripts/recommend.py --top 10 --no-fundamentals  # 빠름(PER·섹터 생략)
.venv/bin/python scripts/recommend.py --as-of 2026-07-15 --top 10 # 과거 백필(감정 생략)
.venv/bin/python scripts/recommend.py --top 10 --no-save          # 실험(DB 저장 안 함)
```

출력물: 모멘텀 top-N(✅/❌ 퀄리티 딱지) + 🛡 퀄리티 게이트 top-N + 종목별 1주/1개월
확률 예보(기대가·68% 구간·손절) + VIX/WTI 컨텍스트·뉴스 플래그.
저장: `recommendations`(variant별)·`price_targets` 테이블.

### 2.3 사후 추적·채점 리포트

```bash
.venv/bin/python scripts/track_recommendations.py             # 문서 갱신만
.venv/bin/python scripts/track_recommendations.py --telegram  # + 요약 발송
```

산출: `docs/reports/recommendation-tracking.md`
— +1/+3/+5일 수익률, 적중률, **모멘텀 vs 퀄리티게이트 대조**, 예보 캘리브레이션(명목 68% 대비).

### 2.4 계좌 손절 점검 (KIS)

```bash
.venv/bin/python scripts/daily_check.py             # 콘솔만
.venv/bin/python scripts/daily_check.py --telegram  # + 발송 (API 실패 시 critical 경보)
```

판정: 평단 대비 -10%(`stop_loss_fraction`) 또는 최신 예보의 ATR 손절선 하회 → 🔴.

### 2.5 정세·큰손 다이제스트 (claude 헤드리스)

```bash
~/.local/bin/claude -p "오늘($(date '+%Y-%m-%d')) 미국 증시 관점의 세계 정세 3~5줄과 주식 큰손 동향 3줄을 한국어로, 출처와 함께 간결히." --allowedTools "WebSearch" \
  | .venv/bin/python scripts/send_telegram.py --subject "정세 다이제스트 테스트"
```

### 2.6 데이터 수집

```bash
.venv/bin/python scripts/collect.py --period 10d   # 일일 증분(분할 감지 시 자동 전체 재수집)
.venv/bin/python scripts/collect.py                # 전체 10년 재수집(20~40분)
.venv/bin/python scripts/collect.py --skip-prices  # VIX/WTI만
```

수집 후 무결성 검증(분할 이중조정 잔재 확인 — 0이어야 정상):

```bash
sqlite3 data/trade_flow.db "
WITH seq AS (SELECT symbol, CAST(split_adjusted_close AS REAL) adj, CAST(close AS REAL) raw,
  LAG(CAST(split_adjusted_close AS REAL)) OVER (PARTITION BY symbol ORDER BY session_date) pa,
  LAG(CAST(close AS REAL)) OVER (PARTITION BY symbol ORDER BY session_date) pr FROM prices)
SELECT COUNT(*) FROM seq WHERE pa>0 AND (adj/pa>1.5 OR adj/pa<0.667) AND raw/pr BETWEEN 0.667 AND 1.5;"
```

### 2.7 백테스트

```bash
# 전체 평가(6개 시나리오 + walk-forward/holdout, ~1시간)
.venv/bin/python scripts/backtest.py --out backtests/gradeC_full_evaluate_v2.json

# quick 단일 시나리오 + 리서치 토글
.venv/bin/python scripts/backtest.py --quick --cost-bps 15 --rebalance-every 21 \
  --hysteresis 5 --rebalance-band 0.02 --out backtests/my_experiment.json
# --rebalance-every: 1=일일, 5≈주간, 21≈월간
```

**유효 기준선**: `backtests/gradeC_full_evaluate_v2.json` (분할 버그 수정 후).
그 이전 산출물(`gradeC_full_evaluate.json` 등)은 오염 데이터 기반 — 인용 금지.

### 2.8 단위 테스트·린트 (코드 변경 후 항상)

```bash
.venv/bin/python -m pytest -q && .venv/bin/ruff check .
```

### 2.9 일일 리밸런스 dry-run (자동매매 — 현재 보류 상태)

```bash
.venv/bin/python scripts/daily_run.py --max-symbols 600          # dry-run(주문 없음)
# --execute는 §7.1 재승인 전 사용 금지. 안전장치:
#   - KIS_ENV=real + runtime=paper 조합은 실행 즉시 차단(C-1 수정)
#   - 킬스위치: 리포 루트에 KILL_SWITCH 파일 생성 시 모든 주문 차단
touch KILL_SWITCH   # 비상 정지 / rm KILL_SWITCH 로 해제
```

---

## 3. 문제 해결

| 증상 | 확인 |
|---|---|
| 텔레그램 안 옴 | `echo t \| python scripts/send_telegram.py --subject t` → error_code 확인. `.env` 로드 여부 |
| 루틴이 안 돌았다 | `tail -50 data/daily_routine.log` / `data/weekly_report.log`. Mac 잠자기 여부 |
| KIS API 오류 | `.env`의 `KIS_ENV`·키 확인. 토큰 캐시 삭제: `rm data/kis_token.json` |
| 추천이 이상함 | 2.6 무결성 쿼리(0 확인) → `--refresh-data` 후 재실행 |
| 펀더멘털 딱지가 낡음 | 캐시 TTL 7일. 강제 갱신: `rm data/fundamentals_cache.json` |
| DB 복구 | 백업: `data/trade_flow.db.bak-doubleadjust` (2026-07-23, 버그 수정 직전) |

## 4. 핵심 문서 지도

| 문서 | 내용 |
|---|---|
| `docs/reviews/2026-07-23-split-bug-backtest-rerun.md` | 분할 버그 전말 + 유효 기준선(월간 +8%, SPY 열위) |
| `docs/reviews/2026-07-23-cadence-sweep.md` | 일일/주간/월간 스윕 — 회전율·비용 분석 |
| `docs/reviews/2026-07-23-value-team-crosscheck.md` | 4대 거장 가치팀 판정(SOLV>MPC>BBY) + 섹터상한 근거 |
| `docs/reports/recommendation-tracking.md` | 살아있는 채점표(주간 자동 갱신) |
| `docs/reviews/2026-07-23-fable-full-review-{codex,claude}.md` | 전체 파이프라인 교차 리뷰(수익 추정은 무효 — 버그 이전) |

## 5. 현재 상태 요약 (2026-07-23 기준)

- **자동매매: 보류** — 깨끗한 데이터에서 최선 구성(월간 +8.0%)도 SPY(+15.0%) 열위
- **운영 중**: 추천 리포트(모멘텀+퀄리티게이트 이중) + 목표가 예보 + 사후 추적 채점
- **진행 중인 실험**: 모멘텀군 vs 퀄리티게이트군 전향적 대조 — 주간 자동 채점, 수 주 후 승격/폐기 판정
- 다음 마일스톤: 월간 cadence walk-forward 검증, grade-B(PIT) 데이터, SPY 벤치마크 내장
