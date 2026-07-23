"""KIS 해외주식 RebalanceBroker 어댑터.

읽기(account_snapshot, quote)는 구현. 주문(submit/find_by_intent/await_terminal/cancel)은
2b-2에서 구현하며 현재는 NotImplementedError. 원화 통합증거금(자동환전) 계좌를 가정하고
계좌 가치를 USD로 환산해 스냅샷을 만든다(전략·planner가 USD로 동작).

USD 환산: NAV(USD) = 총자산(KRW, tot_asst_amt) / USD 환율(frst_bltn_exrt).
보유는 inquire-balance output1(USD 평가), 현금(USD) = NAV - 보유평가합.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType

from trade_flow.broker.kis import KisApiError, KisClient
from trade_flow.execution.models import (
    AccountSnapshot,
    BrokerOrder,
    OrderIntent,
    PositionSnapshot,
    Quote,
)

# inquire-balance output1(보유종목) 필드(문서 기준; 실보유 발생 시 재확인).
HOLDING_SYMBOL = "ovrs_pdno"
HOLDING_QTY = "ovrs_cblc_qty"
HOLDING_AVG = "pchs_avg_pric"
HOLDING_PRICE = "now_pric2"


def _dec(value: object, default: str = "0") -> Decimal:
    if value in (None, ""):
        return Decimal(default)
    return Decimal(str(value))


class KisBroker:
    """RebalanceBroker 프로토콜 구현(KIS 해외주식)."""

    def __init__(
        self,
        client: KisClient,
        *,
        exchange_map: dict[str, str] | None = None,
        default_exchange: str = "NASDAQ",
    ) -> None:
        self._client = client
        self._exchange_map = exchange_map or {}
        self._default_exchange = default_exchange
        cred = client._cred  # noqa: SLF001
        self._account_hash = f"kis-{cred.environment}-{cred.account}"

    def _exchange(self, symbol: str) -> str:
        return self._exchange_map.get(symbol, self._default_exchange)

    # --- 읽기 ---
    def account_snapshot(self) -> AccountSnapshot:
        present = self._client.inquire_present_balance_raw(nation="840")
        usd_rate = _usd_rate(present)
        if usd_rate <= 0:
            raise KisApiError("USD 환율(frst_bltn_exrt)을 확인할 수 없습니다")
        summary = present.get("output3") or {}
        total_assets_krw = _dec(summary.get("tot_asst_amt"))
        nav_usd = total_assets_krw / usd_rate

        holdings = self._client.inquire_balance_raw(exchange="NASDAQ")
        positions: dict[str, PositionSnapshot] = {}
        held_value = Decimal(0)
        for row in holdings.get("output1") or []:
            symbol = str(row.get(HOLDING_SYMBOL) or "").strip()
            quantity = int(_dec(row.get(HOLDING_QTY)))
            price = _dec(row.get(HOLDING_PRICE))
            if not symbol or quantity <= 0 or price <= 0:
                continue
            positions[symbol] = PositionSnapshot(
                symbol=symbol,
                quantity=quantity,
                average_price=_dec(row.get(HOLDING_AVG)),
                market_price=price,
            )
            held_value += Decimal(quantity) * price

        cash_usd = nav_usd - held_value
        if cash_usd < 0:
            cash_usd = Decimal(0)
        return AccountSnapshot(
            account_hash=self._account_hash,
            captured_at=datetime.now(UTC),
            nav=nav_usd,
            cash=cash_usd,
            positions=MappingProxyType(dict(sorted(positions.items()))),
        )

    def quote(self, symbol: str) -> Quote:
        data = self._client.price_raw(symbol, exchange=self._exchange(symbol))
        last = _dec((data.get("output") or {}).get("last"))
        if last <= 0:
            raise KisApiError(f"{symbol} 현재가를 확인할 수 없습니다")
        # 현재가 엔드포인트는 호가(bid/ask)를 주지 않으므로 last로 대체한다.
        # planner가 지정가 허용폭(±)을 적용하므로 매수/매도 지정가는 여기서 벌어진다.
        return Quote(symbol=symbol, bid=last, ask=last, captured_at=datetime.now(UTC))

    # --- 주문 (2b-2) ---
    def find_by_intent(self, intent_id: str) -> BrokerOrder | None:
        raise NotImplementedError("주문 조회는 2b-2에서 구현")

    def submit(self, intent: OrderIntent) -> BrokerOrder:
        raise NotImplementedError("주문 제출은 2b-2에서 구현")

    def await_terminal(self, order: BrokerOrder, timeout_seconds: int) -> BrokerOrder:
        raise NotImplementedError("체결 대기는 2b-2에서 구현")

    def cancel(self, broker_order_id: str) -> BrokerOrder:
        raise NotImplementedError("주문 취소는 2b-2에서 구현")


def _usd_rate(present_balance: dict) -> Decimal:
    for row in present_balance.get("output2") or []:
        if str(row.get("crcy_cd")).upper() == "USD":
            return _dec(row.get("frst_bltn_exrt"))
    return Decimal(0)


__all__ = ["KisBroker"]
