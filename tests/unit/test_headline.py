from trade_flow.sentiment.headline import score_headline, score_headlines


def test_score_headline_direction() -> None:
    assert score_headline("Marathon beats earnings, raises dividend") > 0
    assert score_headline("Best Buy plunges after weak guidance, layoffs announced") < 0
    assert score_headline("Marathon Petroleum vs. HF Sinclair: comparison") == 0.0


def test_score_headlines_aggregates_and_flags_macro() -> None:
    result = score_headlines([
        "Oil surges as Iran war intensifies near Strait of Hormuz",
        "Refiners rally on strong margins",
        "Analysts warn of recession risk from tariffs",
    ])
    assert result.article_count == 3
    assert -1.0 <= result.score <= 1.0
    # 지정학·매크로 플래그 수집(한글 라벨).
    assert "이란" in result.macro_flags
    assert "전쟁" in result.macro_flags
    assert "호르무즈" in result.macro_flags
    assert "관세" in result.macro_flags
    assert "침체" in result.macro_flags


def test_empty_headlines_are_neutral() -> None:
    result = score_headlines([])
    assert result.score == 0.0 and result.article_count == 0 and result.macro_flags == ()
