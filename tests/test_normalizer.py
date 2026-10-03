import pytest

from app.financial.normalizer import detect_unit, normalize_value


class TestUnitDetection:
    def test_ribuan(self):
        u = detect_unit("Disajikan dalam ribuan Rupiah")
        assert u.unit == "ribuan"
        assert u.multiplier == 1_000
        assert u.currency == "IDR"

    def test_jutaan(self):
        u = detect_unit("Dalam jutaan Rupiah")
        assert u.unit == "juta"
        assert u.multiplier == 1_000_000

    def test_miliaran(self):
        u = detect_unit("dalam miliaran rupiah")
        assert u.unit == "miliar"
        assert u.multiplier == 1_000_000_000

    # The `-an` forms above are only half the vocabulary. Indonesian statements
    # use the bare word at least as often ("dalam juta", "dalam ribu",
    # "dalam miliar", "dalam triliun") and mixing them in one report is common.
    # These were written as `jutaan?` in the pattern list, which requires a
    # literal "a" and so matched only "jutaan" -- leaving the bare form
    # undetected, the multiplier at 1, and every figure on such a page
    # under-scaled by 1000x to 1e12x.

    @pytest.mark.parametrize(
        "text,unit,multiplier",
        [
            ("Disajikan dalam ribu Rupiah", "ribuan", 1_000),
            ("Dalam juta Rupiah", "juta", 1_000_000),
            ("dalam miliar rupiah", "miliar", 1_000_000_000),
            ("Dalam triliun Rupiah", "triliun", 1_000_000_000_000),
        ],
    )
    def test_bare_indianian_unit_words_are_detected(self, text, unit, multiplier):
        u = detect_unit(text)
        assert u.unit == unit
        assert u.multiplier == multiplier

    def test_bare_form_scales_the_figure_correctly(self):
        """The failure this prevents: 28.793 in juta is 28.793 trillion."""
        u = detect_unit("dalam juta")
        assert normalize_value(28_793, u) == 28_793_000_000

    def test_bare_and_suffixed_forms_agree(self):
        assert detect_unit("dalam juta").multiplier == detect_unit("dalam jutaan").multiplier
        assert detect_unit("dalam ribu").multiplier == detect_unit("dalam ribuan").multiplier

    def test_english_millions(self):
        u = detect_unit("In millions of USD")
        assert u.unit == "juta"
        assert u.currency == "USD"
        assert u.multiplier == 1_000_000

    def test_english_thousands(self):
        u = detect_unit("In thousands of Rupiah")
        assert u.unit == "ribuan"
        assert u.multiplier == 1_000

    def test_plain_rupiah(self):
        u = detect_unit("Dalam Rupiah")
        assert u.multiplier == 1
        assert u.currency == "IDR"

    def test_no_unit(self):
        u = detect_unit("Laporan Posisi Keuangan")
        assert u.unit is None
        assert u.multiplier == 1


class TestNormalization:
    def test_juta_revenue(self):
        u = detect_unit("Dalam jutaan Rupiah")
        assert normalize_value(125_000, u) == 125_000_000_000

    def test_ribuan(self):
        u = detect_unit("dalam ribuan Rupiah")
        assert normalize_value(1_234, u) == 1_234_000

    def test_base(self):
        u = detect_unit("Dalam Rupiah")
        assert normalize_value(1_500_000, u) == 1_500_000


if __name__ == "__main__":
    pytest.main([__file__])
