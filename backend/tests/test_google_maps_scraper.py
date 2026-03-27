from app.services.scrapers.google_maps_scraper import _normalize_rating, _parse_relative_date


def test_parse_relative_date_returns_none_for_now() -> None:
    assert _parse_relative_date("2 個月前") is None


def test_normalize_rating_handles_float_values() -> None:
    assert _normalize_rating(4.6) == 5
    assert _normalize_rating("3.2") == 3
    assert _normalize_rating(None) == 0
