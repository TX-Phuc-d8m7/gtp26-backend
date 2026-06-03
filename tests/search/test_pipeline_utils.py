from app.modules.search.pipeline._utils import (
    dedupe,
    normalize_text,
    normalized_overlap,
    phrase_matches,
)


def test_normalize_text_strips_diacritics_and_case():
    assert normalize_text("Hải Sản") == "hai san"
    assert normalize_text("  Đậm   đà!! ") == "dam da"


def test_dedupe_keeps_first_casing():
    assert dedupe(["Phở", "phở", " PHỞ ", "Bún"]) == ["Phở", "Bún"]


def test_normalized_overlap_matches_across_diacritics():
    assert normalized_overlap(["hải sản", "Chiên"], ["Hải Sản"]) == ["hải sản"]


def test_phrase_matches_requires_word_boundary():
    assert phrase_matches(["pho bo"], "Pho bo tai chin") == ["pho bo"]
    assert phrase_matches(["pho"], "phong cach") == []


def test_dish_phrase_matches_is_diacritic_aware():
    from app.modules.search.pipeline._utils import dish_phrase_matches

    assert dish_phrase_matches(["phở"], "Bánh mì phô mai") == []
    assert dish_phrase_matches(["phở"], "Phở bò tái") == ["phở"]
    assert dish_phrase_matches(["pho bo"], "Phở bò tái") == ["pho bo"]
