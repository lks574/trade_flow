"""KIS 해외주식 RebalanceBroker 어댑터.

읽기(account_snapshot, quote)는 구현. 주문(submit/find_by_intent/await_terminal/cancel)은
2b-2에서 구현하며 현재는 NotImplementedError. 원화 통합증거금(자동환전) 계좌를 가정하고
계좌 가치를 USD로 환산해 스냅샷을 만든다(전략·planner가 USD로 동작).

USD 환산: NAV(USD) = 총자산(KRW, tot_asst_amt) / USD 환율(frst_bltn_exrt).
보유는 inquire-balance output1(USD 평가), 현금(USD) = NAV - 보유평가합.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
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
        exchange_map_path: Path | None = None,
        default_exchange: str = "NASDAQ",
        poll_interval_seconds: float = 2.0,
    ) -> None:
        self._client = client
        # 영속 캐시(있으면) + 주입 맵. 매 실행 거래소 재탐색을 피한다.
        self._exchange_map_path = Path(exchange_map_path) if exchange_map_path else None
        self._exchange_map = self._load_exchange_map()
        self._exchange_map.update(exchange_map or {})
        self._default_exchange = default_exchange
        self._poll_interval = poll_interval_seconds
        cred = client._cred  # noqa: SLF001
        self._account_hash = f"kis-{cred.environment}-{cred.account}"
        # 자격증명 환경(mock/real). 런타임(paper/production) 결합 검증(C-1)에 쓴다.
        self.credential_environment = cred.environment
        # 제출한 주문의 컨텍스트(취소·조회에 필요). ODNO -> 주문 정보.
        # KIS는 사용자 정의 주문ID를 지원하지 않아 프로세스 내 멱등성/취소를 위해 유지한다.
        self._orders: dict[str, dict[str, object]] = {}
        self._intent_index: dict[str, str] = {}  # intent_id -> ODNO

    _CANDIDATE_EXCHANGES = ("NASDAQ", "NYSE", "AMEX")

    def _load_exchange_map(self) -> dict[str, str]:
        if self._exchange_map_path is None:
            return {}
        try:
            data = json.loads(self._exchange_map_path.read_text())
        except (OSError, ValueError):
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _save_exchange_map(self) -> None:
        if self._exchange_map_path is None:
            return
        try:
            self._exchange_map_path.parent.mkdir(parents=True, exist_ok=True)
            self._exchange_map_path.write_text(json.dumps(dict(sorted(self._exchange_map.items()))))
        except OSError:
            pass  # 캐시 저장 실패는 비치명적(다음에 재탐색)

    def _exchange(self, symbol: str) -> str:
        return self._exchange_map.get(symbol, self._default_exchange)

    def resolve_exchange(self, symbol: str) -> str:
        """심볼의 거래소를 시세 조회로 탐색해 캐시한다(NASD/NYSE/AMEX 매핑 미보유 대응)."""
        if symbol in self._exchange_map:
            return self._exchange_map[symbol]
        from trade_flow.broker.kis import KisApiError

        for exchange in self._CANDIDATE_EXCHANGES:
            try:
                data = self._client.price_raw(symbol, exchange=exchange)
            except KisApiError:
                continue
            last = _dec((data.get("output") or {}).get("last"))
            if last > 0:
                self._exchange_map[symbol] = exchange
                self._save_exchange_map()
                return exchange
        self._exchange_map[symbol] = self._default_exchange
        self._save_exchange_map()
        return self._default_exchange

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
        data = self._client.price_raw(symbol, exchange=self.resolve_exchange(symbol))
        last = _dec((data.get("output") or {}).get("last"))
        if last <= 0:
            raise KisApiError(f"{symbol} 현재가를 확인할 수 없습니다")
        # 현재가 엔드포인트는 호가(bid/ask)를 주지 않으므로 last로 대체한다.
        # planner가 지정가 허용폭(±)을 적용하므로 매수/매도 지정가는 여기서 벌어진다.
        return Quote(symbol=symbol, bid=last, ask=last, captured_at=datetime.now(UTC))

    # --- 주문 ---
    def submit(self, intent: OrderIntent) -> BrokerOrder:
        exchange = self._exchange(intent.symbol)
        data = self._client.order_raw(
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            price=format(intent.limit_price, "f"),
            exchange=exchange,
        )
        output = data.get("output") or {}
        odno = str(output.get("ODNO") or "").strip()
        if not odno:
            raise KisApiError(f"order accepted but no ODNO: {data.get('msg1')}")
        self._orders[odno] = {
            "symbol": intent.symbol,
            "exchange": exchange,
            "quantity": intent.quantity,
            "side": intent.side,
            "intent_id": intent.intent_id,
            "org_orgno": str(output.get("KRX_FWDG_ORD_ORGNO") or "").strip(),
        }
        self._intent_index[intent.intent_id] = odno
        return BrokerOrder(
            broker_order_id=odno,
            intent_id=intent.intent_id,
            status="submitted",
            filled_quantity=0,
            remaining_quantity=intent.quantity,
        )

    def find_by_intent(self, intent_id: str) -> BrokerOrder | None:
        # 프로세스 내 멱등성: 같은 실행에서 이미 제출한 intent면 현재 상태를 반환한다.
        # (프로세스 간 멱등성은 OrderRepository 연동이 필요 — 후속.)
        odno = self._intent_index.get(intent_id)
        if odno is None:
            return None
        info = self._orders[odno]
        return self._status(odno, intent_id, int(info["quantity"]), str(info["exchange"]))

    def await_terminal(self, order: BrokerOrder, timeout_seconds: int) -> BrokerOrder:
        import time

        info = self._orders.get(order.broker_order_id, {})
        exchange = str(info.get("exchange", self._default_exchange))
        quantity = int(info.get("quantity", order.remaining_quantity))
        deadline = time.monotonic() + max(0, timeout_seconds)
        current = order
        while time.monotonic() < deadline:
            current = self._status(order.broker_order_id, order.intent_id, quantity, exchange)
            if current.terminal:
                return current
            time.sleep(self._poll_interval)
        return current

    def open_orders(self) -> list[dict[str, object]]:
        """브로커의 미체결 주문 전량(거래소별 조회 후 병합). 재실행 복구/정합성 확인용(§3.5)."""
        seen: dict[str, dict[str, object]] = {}
        for exchange in self._CANDIDATE_EXCHANGES:
            data = self._client.inquire_nccs_raw(exchange=exchange)
            for row in data.get("output") or []:
                odno = str(row.get("odno") or "").strip()
                if not odno or odno in seen:
                    continue
                quantity = int(_dec(row.get("nccs_qty") or row.get("ft_ord_qty") or 0))
                seen[odno] = {
                    "odno": odno,
                    "symbol": str(row.get("pdno") or "").strip(),
                    "quantity": quantity,
                    "exchange_code": str(row.get("ovrs_excg_cd") or "").strip(),
                }
        return list(seen.values())

    def cancel_open(self, open_order: dict[str, object]) -> None:
        """미체결 주문 하나를 취소(레지스트리 없이 원시 필드로). 이전 주문 이월 방지."""
        self._client.cancel_order_raw(
            symbol=str(open_order["symbol"]),
            org_order_no=str(open_order["odno"]),
            quantity=int(open_order["quantity"]),
            exchange=str(open_order["exchange_code"]) or self._default_exchange,
        )

    def cancel(self, broker_order_id: str) -> BrokerOrder:
        info = self._orders.get(broker_order_id)
        if info is None:
            raise KisApiError(f"unknown broker order id: {broker_order_id}")
        self._client.cancel_order_raw(
            symbol=str(info["symbol"]),
            org_order_no=broker_order_id,
            quantity=int(info["quantity"]),
            exchange=str(info["exchange"]),
        )
        return BrokerOrder(
            broker_order_id=broker_order_id,
            intent_id=str(info["intent_id"]),
            status="cancelled",
            filled_quantity=0,
            remaining_quantity=int(info["quantity"]),
        )

    def _status(
        self, odno: str, intent_id: str, quantity: int, exchange: str
    ) -> BrokerOrder:
        """미체결내역에 남아있으면 pending(submitted), 없으면 체결완료로 간주한다.

        주의: 부분체결 수량 세분화는 체결내역(ccnl) 필드 확정 후 정교화한다(후속).
        """
        pending = self._client.inquire_nccs_raw(exchange=exchange)
        for row in pending.get("output") or []:
            if str(row.get("odno") or "").strip() == odno:
                remaining = int(_dec(row.get("nccs_qty") or row.get("ord_qty") or quantity))
                return BrokerOrder(
                    broker_order_id=odno,
                    intent_id=intent_id,
                    status="submitted",
                    filled_quantity=quantity - remaining,
                    remaining_quantity=remaining,
                )
        # 미체결에 없음 -> 전량 체결(또는 취소)로 간주.
        return BrokerOrder(
            broker_order_id=odno,
            intent_id=intent_id,
            status="filled",
            filled_quantity=quantity,
            remaining_quantity=0,
        )


def _usd_rate(present_balance: dict) -> Decimal:
    for row in present_balance.get("output2") or []:
        if str(row.get("crcy_cd")).upper() == "USD":
            return _dec(row.get("frst_bltn_exrt"))
    return Decimal(0)


__all__ = ["KisBroker"]
