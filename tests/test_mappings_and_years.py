import pytest

from app.financial.mappings import map_label
from app.ingestion.metadata import year_from_filename, year_from_text


class TestLabelMapping:
    def test_indonesian_cash(self):
        field, conf = map_label("Kas dan Setara Kas", "balance_sheet")
        assert field == "cash_and_cash_equivalents"
        assert conf >= 0.9

    def test_english_cash(self):
        field, _ = map_label("Cash and cash equivalents", "balance_sheet")
        assert field == "cash_and_cash_equivalents"

    def test_revenue_field_is_gone(self):
        """'Pendapatan' no longer maps anywhere.

        The field it used to fill was deleted rather than kept as a fallback:
        a bare 'Pendapatan' line is not the statement's exact top line, and
        mapping it is how a figure ended up under a heading it never carried.
        """
        for label in ("Pendapatan", "Pendapatan usaha", "Revenue", "Net revenue"):
            field, conf = map_label(label, "income_statement")
            assert field is None, label
            assert conf == 0.0, label

    def test_sales_variants(self):
        """'Penjualan' labels are sales, and sales is NOT revenue.

        These were collapsed into `revenue` until a report's sales figure was
        being presented as its revenue. They are distinct lines in different
        reports, so they must stay distinct fields.
        """
        for label in ("Penjualan", "Penjualan bersih", "Penjualan neto",
                      "Hasil penjualan", "Sales", "Net sales"):
            field, _ = map_label(label, "income_statement")
            assert field == "sales", label

    def test_expense_labels_containing_penjualan_are_not_sales(self):
        """'Beban penjualan' and 'Beban pokok penjualan' both contain
        'penjualan'. Substring matching must not capture them as sales."""
        field, _ = map_label("Beban penjualan", "income_statement")
        assert field == "operating_expenses"
        field, _ = map_label("Beban pokok penjualan", "income_statement")
        assert field == "cost_of_revenue"

    def test_total_assets_variants(self):
        for label in ("TOTAL ASET", "Jumlah aset", "Total Assets", "Jumlah aktiva"):
            field, _ = map_label(label, "balance_sheet")
            assert field == "total_assets", label

    def test_retained_earnings(self):
        field, _ = map_label("Saldo Laba", "balance_sheet")
        assert field == "retained_earnings"

    def test_with_footnote_markers(self):
        field, _ = map_label("Jumlah aset (1)", "balance_sheet")
        assert field == "total_assets"

    def test_unknown_label(self):
        field, conf = map_label("Biaya peluang aneh sekali", "income_statement")
        assert field is None
        assert conf == 0.0

    def test_unit_annotation_stripped(self):
        field, _ = map_label("Jumlah aset (dalam jutaan Rupiah)", "balance_sheet")
        assert field == "total_assets"


class TestSplitWordLabels:
    """Table extraction can break a word across two cells.

    'Total aset tidak lan car' previously fell through to a substring hit on
    'total aset' and recorded the non-current total as total_assets.
    """

    def test_split_non_current_assets(self):
        field, _ = map_label("Total aset tidak lan car", "balance_sheet")
        assert field == "non_current_assets"

    def test_split_current_assets(self):
        field, _ = map_label("Total aset lanca r", "balance_sheet")
        assert field == "current_assets"

    def test_split_jumlah_aset_lancar(self):
        field, _ = map_label("Jumlah Aset Lanc ar", "balance_sheet")
        assert field == "current_assets"

    def test_split_current_liabilities(self):
        field, _ = map_label("Jumlah Liabilitas Ja ngka Pendek", "balance_sheet")
        assert field == "current_liabilities"

    def test_clean_label_outranks_split_label(self):
        """Both resolve to the same field, and at the same confidence.

        A word split across table cells is still that line item, so it is as
        certain a mapping as the clean spelling. Scoring it lower used to look
        like a hedge but bought nothing: the label either is the registered
        wording or it is not, and which figure wins between competing readings
        is settled by the page it came from, not by how the label was chopped
        up in the source table.
        """
        field, conf = map_label("Total aset tidak lancar", "balance_sheet")
        assert field == "non_current_assets"
        assert conf == 1.0

        split_field, split_conf = map_label("Total aset tidak lan car", "balance_sheet")
        assert split_field == "non_current_assets"
        assert split_conf == 1.0

    def test_genuinely_unknown_label_still_unmapped(self):
        """Collapsing spaces must not invent a match."""
        field, conf = map_label("Biaya peluang aneh sekali", "income_statement")
        assert field is None
        assert conf == 0.0


class TestYearDetection:
    def test_filename(self):
        assert year_from_filename("laporan_keuangan_2023.pdf") == 2023
        assert year_from_filename("Annual-Report-2022.pdf") == 2022
        assert year_from_filename("report.pdf") is None

    def test_tahun_buku(self):
        text = "PT Example\nLaporan Keuangan\nUntuk Tahun Buku Yang Berakhir Pada Tanggal 31 Desember 2023"
        assert year_from_text(text) == 2023

    def test_english_period(self):
        text = "For the year ended December 31, 2022 and 2021"
        assert year_from_text(text) == 2022

    def test_bare_year_fallback(self):
        text = "Laporan tahun 2024 dibandingkan 2023."
        assert year_from_text(text) in (2024, 2023)


if __name__ == "__main__":
    pytest.main([__file__])
