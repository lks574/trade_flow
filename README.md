# trade_flow

미국주식 일봉 스윙 전략을 동일한 전략 계약으로 백테스트하고 이후 모의·실계좌로 확장하는 프로젝트다.

현재 범위는 Phase 1 백테스터와 전략 검증이다. KIS 주문 연동은 Phase 2에서 진행한다.

핵심 전략·백테스터·검증·shadow 감정·멱등 주문·출시 안전 게이트의 내부 구현은
완료되어 있다. 실데이터 adapter와 KIS adapter는 외부 데이터 및 공식 paper API 확인 뒤
연결한다. 미결·승인 항목은 `docs/superpowers/IMPLEMENTATION_NOTES.md`에서 관리한다.

## 개발 환경

- Python 3.12
- SQLite
- pytest
- Ruff

## 시작

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check .
```

## 명령

```bash
trade-flow show-config --config configs/strategy.toml
trade-flow init-db --db data/trade_flow.db
trade-flow manifest \
  --config configs/strategy.toml \
  --data-hash DATA_HASH \
  --universe-hash UNIVERSE_HASH
```

## 기준 문서

- [문서 운영 규칙](docs/superpowers/README.md)
- [Tech Spec](docs/superpowers/specs/2026-07-21-trade-flow-tech-spec.md)
