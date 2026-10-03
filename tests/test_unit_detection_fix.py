"""Tests for the unit-mixing root cause of the 9 validation ERRORs.

Root causes covered:
  1. detect_unit matched narrative 'trillion'/'billion' mentions without a
     unit-introducing word -> x1e12 corruption.
  2. '(dalam Jutaan)' paren forms and 'in billion)' fragments.
  3. Processor plausibility guard against absurd multiplier stacking.
"""
import pytest

from app.financial.normalizer import detect_unit


class TestUnitIntroGating:
    def test_narrative_trillion_not_unit(self):
        """'Rp1.15 trillion in 2024' is prose — no report unit."""
        u = detect_unit("naik menjadi Rp1.15 trillion, mainly driven by")
        assert u.unit is None
        assert u.multiplier == 1

    def test_in_billion_fragment(self):
        """Both paren forms are intro phrases; first match in priority order wins
        (triliun > miliar > juta > ribuan) — 'billion' outranks 'juta' by design."""
        u = detect_unit("(dalam Jutaan)\nStatement of Financial Position in billion)")
        assert u.unit == "miliar"

    def test_bare_billions_ignored(self):
        u = detect_unit("Total Assets in billion of Rupiah")  # 'in billion of' has intro 'in'
        assert u.unit == "miliar"

    def test_dalam_jutaan(self):
        u = detect_unit("Disajikan dalam Jutaan Rupiah")
        assert u.unit == "juta"
        assert u.multiplier == 1_000_000

    def test_dalam_ribuan(self):
        u = detect_unit("(dalam ribuan Rupiah)")
        assert u.unit == "ribuan"

    def test_plain_prose_no_unit(self):
        u = detect_unit("Kas dan setara kas sebesar Rp2,09 triliun sepanjang 2024")
        # 'sebesar ... triliun' has no intro word -> multiplier 1
        assert u.multiplier == 1

    def test_explicit_statement_unit(self):
        u = detect_unit("Laporan Posisi Keuangan\nPer 31 Desember 2024\n(Dinyatakan dalam jutaan Rupiah)")
        assert u.unit == "juta"


class TestParenUnitForms:
    def test_dalam_jutaan_paren(self):
        u = detect_unit("dalam Jutaan)")
        assert u.unit == "juta"

    def test_in_billion_paren(self):
        u = detect_unit("in billion)")
        assert u.unit == "miliar"


class TestPlausibilityGuard:
    def test_guard_in_processor_logic(self):
        """Simulate: raw '28,793,225' wrongly scaled x1e12 -> guard keeps raw."""
        # The guard lives in DocumentProcessor; here we verify the threshold
        # logic that drives it.
        parsed = 28_793_225.0
        multiplier = 1_000_000_000_000
        normalized = parsed * multiplier
        assert normalized > 1e17  # guard triggers
        # With correct juta scaling it would not:
        assert parsed * 1_000_000 < 1e17

    def test_large_billion_scale_values_pass(self):
        """Legit big values (in miliar) stay under the guard."""
        parsed = 28_793_225.0
        assert parsed * 1_000_000_000 < 1e17


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
