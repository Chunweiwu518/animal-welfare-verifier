from app.services.scrapers.ptt_scraper import _build_search_keywords, _matches_entity


def test_ptt_keyword_builder_expands_entity_variants() -> None:
    keywords = _build_search_keywords("董旺旺")

    assert "董旺旺" in keywords
    assert "董旺旺狗園" in keywords
    assert "董旺旺協會" in keywords


def test_ptt_entity_match_accepts_full_name_and_tokens() -> None:
    assert _matches_entity("董旺旺狗園志工心得", "董旺旺") is True
    assert _matches_entity("這篇文章在討論董旺旺協會的近況", "董旺旺") is True
    assert _matches_entity("完全無關的別人文章", "董旺旺") is False
