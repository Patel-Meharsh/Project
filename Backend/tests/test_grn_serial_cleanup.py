from types import SimpleNamespace

from app.api.grn_serial_cleanup import (
    glued_serial_variant,
    resolve_description,
    strip_leading_serial,
    suggest_master_items,
)


def test_bare_serial_before_numeric_product_is_removed():
    assert strip_leading_serial("2 36W CFL", expected_serial=2) == "36W CFL"


def test_serial_column_text_is_preferred_over_expected_sequence():
    assert strip_leading_serial("7 Chowk PL", expected_serial=3, serial_text="7") == "Chowk PL"


def test_product_size_is_not_mistaken_for_serial():
    assert strip_leading_serial("2 Ltr White Phenyl", expected_serial=2) == "2 Ltr White Phenyl"
    assert strip_leading_serial("15 W LED fitting", expected_serial=15) == "15 W LED fitting"
    assert strip_leading_serial("3 Pin Plug", expected_serial=3) == "3 Pin Plug"


def test_number_that_is_not_the_serial_is_kept():
    assert strip_leading_serial("36W CFL", expected_serial=2) == "36W CFL"
    assert strip_leading_serial("5 36W CFL", expected_serial=2) == "5 36W CFL"


def test_glued_serial_variant():
    assert glued_serial_variant("236W CFL", 2) == "36W CFL"
    assert glued_serial_variant("36W CFL", 2) is None
    assert glued_serial_variant("236W CFL", None) is None


def test_glued_serial_used_only_when_master_evidence_supports_it():
    masters = [SimpleNamespace(code="C1", name="36W CFL")]

    def score(text):
        hits = suggest_master_items(text, masters)
        return hits[0]["score"] if hits else 0.0

    name, warning = resolve_description("236W CFL", expected_serial=2, score_fn=score)
    assert name == "36W CFL" and warning is None


def test_glued_serial_without_evidence_is_flagged_not_changed():
    name, warning = resolve_description("236W CFL", expected_serial=2)
    assert name == "236W CFL"
    assert warning and "36W CFL" in warning


def test_suggestions_recover_ocr_misread():
    masters = [
        SimpleNamespace(code="A1", name="CHOWK PL"),
        SimpleNamespace(code="B2", name="Floor Cleaner"),
    ]
    hits = suggest_master_items("CHOWNK PL", masters)
    assert hits and hits[0]["code"] == "A1" and hits[0]["score"] > 0.8
    assert all(hit["code"] != "B2" for hit in hits)
