from trade_flow.research import QualityAssessment, build_gated_selection, evaluate_fundamentals


def test_evaluate_fundamentals_gates() -> None:
    # 전부 통과
    passed, fails = evaluate_fundamentals(roe=0.35, margin=0.17, debt_to_equity=110.0)
    assert passed and fails == ()
    # 저마진(정유·유통형) 탈락
    passed, fails = evaluate_fundamentals(roe=0.27, margin=0.034, debt_to_equity=150.0)
    assert not passed and fails == ("마진",)
    # 결측은 fail-closed
    passed, fails = evaluate_fundamentals(roe=None, margin=0.10, debt_to_equity=None)
    assert not passed and set(fails) == {"ROE결측", "부채결측"}
    # 경계: ROE 정확히 10%는 통과, D/E 2.0x(=200)는 통과
    passed, _ = evaluate_fundamentals(roe=0.10, margin=0.05, debt_to_equity=200.0)
    assert passed


def _assessment(symbol: str, sector: str, passed: bool) -> QualityAssessment:
    return QualityAssessment(
        symbol=symbol, roe=0.2, margin=0.1, debt_to_equity=100.0,
        sector=sector, passed=passed, fail_reasons=() if passed else ("마진",),
    )


def test_build_gated_selection_applies_gate_and_sector_cap() -> None:
    stream = [
        _assessment("A", "Energy", True),
        _assessment("B", "Energy", False),   # 게이트 탈락
        _assessment("C", "Energy", True),
        _assessment("D", "Energy", True),    # 섹터 상한(2) 초과 → 제외
        _assessment("E", "Tech", True),
        _assessment("F", "Tech", True),
        _assessment("G", "Health", True),    # limit 도달 후 → 소비 안 됨
    ]
    selected = build_gated_selection(iter(stream), limit=4, sector_cap=2)
    assert [a.symbol for a in selected] == ["A", "C", "E", "F"]


def test_build_gated_selection_lazy_consumption() -> None:
    consumed: list[str] = []

    def stream():
        for symbol in ["A", "B", "C", "D"]:
            consumed.append(symbol)
            yield _assessment(symbol, sector=symbol, passed=True)

    selected = build_gated_selection(stream(), limit=2)
    assert [a.symbol for a in selected] == ["A", "B"]
    assert consumed == ["A", "B"]  # limit 도달 후 스트림 소비 중단(지연 평가)
