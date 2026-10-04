"""Regressions for the four data-corruption bugs found in the CSV report.

Each test pins a real mis-extraction observed in output/reports/*.csv against
the real document text that produced it:

  1. prose/narrative table rows parsed as figures
     'triliun pada tahun 2020...' -> gross_profit = 12.3
  2. invented fiscal years from reference numbers
     'putusan Homologasi No. 121/Pdt' -> AISA year=2029 balance sheet
  3. year-header detection failing on side-by-side ID/EN statements
     AALI cash flow stored under both 2021 and 2022
  4. magnitude plausibility labelling for the export
"""
import pytest

from app.extraction.table_extractor import (
    PageTable,
    _detect_header_years,
    _find_year_header_depth,
    _header_years,
    _process_table,
    _split_row,
    is_prose_label,
    order_header_years,
)
from app.export.csv_export import _flag
from app.financial.plausibility import minimum_plausible_monetary
from app.pipeline.processor import DocumentProcessor


class TestProseGuard:
    """Bug 1: MD&A narrative rows became real line items.

    pdfplumber concatenates every text cell left of the first number, so an
    MD&A paragraph yields a sentence-shaped 'label'. The substring mapping tier
    then matched it and the digits inside the prose became the value.
    """

    @pytest.mark.parametrize("label", [
        "triliun pada tahun 2020. Marg in laba bruto jug a mengalami gross profit m "
        "argin also increa sed from",
        "transaksi kontrak berjangka komo ditas. Pada outstanding forward com "
        "modity contract Total aset",
        "beberapa asumsi mu ngkin saling berkorelasi. may be correlat ed. When "
        "calcul ating the sensitivity Kapitalisasi ke modal saham",
        "putusan Homologas i No. 121/ Pdt.Sus.PKPU/2018/ Jumlah Modal Saham",
        "laba ditahan serta menyetujui keputusan pembagian dividends until 2022 "
        "of amounting to",
        "Keputusan d an Realisa si RUPST - Tahun Buk u 2021 Decision and "
        "Realizat ion of AGMS",
    ])
    def test_narrative_labels_are_rejected(self, label):
        assert is_prose_label(label)

    @pytest.mark.parametrize("label", [
        "Total aset tidak lan car",
        "Total Aset La ncar",
        "Beban pokok penjualan",
        "Total Liabilitas Jangka Pendek",
        "Kas dan setara kas",
        "Persediaan",
        "Laba tahun berjalan",
        "Kas dari aktivitas operasi",
        "Penyimpanan barang dan bahan baku",
        "Aset tetap - neto",
    ])
    def test_real_line_items_survive(self, label):
        """Split labels are the normal case in these PDFs; the guard must not
        reject them, or every total in the corpus is lost."""
        assert not is_prose_label(label)

    def test_split_row_rejects_narrative(self):
        row = ["triliun pada tahun 2020. Marg in laba bruto", "12.3"]
        assert _split_row(row) is None

    def test_split_row_keeps_line_item(self):
        row = ["Total aset tidak lan car", "20,985,698"]
        assert _split_row(row) == ("Total aset tidak lan car", ["20,985,698"])

    def test_empty_label_is_prose(self):
        assert is_prose_label("")


class TestYearPlausibility:
    """Bug 2: a court-case reference number was read as a fiscal year."""

    def _proc(self):
        return DocumentProcessor.__new__(DocumentProcessor)

    class _Doc:
        def __init__(self, filename="Annual-Report-2020.pdf", reporting_year=2020):
            self.filename = filename
            self.reporting_year = reporting_year

    def test_court_case_year_rejected(self):
        # AISA's 2020 report produced a 2029 balance sheet from this.
        assert self._proc()._plausible_year(2029, self._Doc()) is None

    def test_far_future_rejected(self):
        assert self._proc()._plausible_year(2031, self._Doc()) is None

    def test_lookback_beyond_ten_years_rejected(self):
        assert self._proc()._plausible_year(2009, self._Doc()) is None

    def test_ten_years_back_kept(self):
        assert self._proc()._plausible_year(2010, self._Doc()) == 2010

    def test_reporting_year_kept(self):
        assert self._proc()._plausible_year(2020, self._Doc()) == 2020

    def test_prior_years_kept(self):
        for y in (2019, 2018, 2017):
            assert self._proc()._plausible_year(y, self._Doc()) == y

    def test_following_period_kept(self):
        assert self._proc()._plausible_year(2021, self._Doc()) == 2021

    def test_unknown_year_passes_through(self):
        assert self._proc()._plausible_year(None, self._Doc()) is None

    def test_uses_filename_when_reporting_year_missing(self):
        doc = self._Doc(filename="2024.pdf", reporting_year=None)
        assert self._proc()._plausible_year(2029, doc) is None
        assert self._proc()._plausible_year(2025, doc) == 2025

    def test_no_anchor_means_no_clamp(self):
        doc = self._Doc(filename="laporan.pdf", reporting_year=None)
        assert self._proc()._plausible_year(2029, doc) == 2029


class TestHeaderYearFallback:
    """Bug 3: side-by-side ID/EN statements lost their year header.

    AALI's cash-flow statement is printed twice, Indonesian at p164 and English
    at p165. The English block's header sits around row 8, past the rows[:4]
    shallow scan, so every value fell back to the document year and the same
    figure was stored under two different years.
    """

    def test_shallow_scan_finds_top_header(self):
        rows = [
            ["LAPORAN ARUS KAS", None],
            ["31 DESEMBER 2022 DAN 2021", None],
            ["(Dinyatakan dalam jutaan Rupiah,)", None],
        ]
        assert _detect_header_years(rows) == [2022, 2021]

    def test_deep_scan_finds_lowered_header(self):
        rows = [["PT ASTRA AGRO LESTARI Tbk", None]] * 6
        rows.append(["2022", "2021", None])
        assert _detect_header_years(rows) == []
        assert _find_year_header_depth(rows) == [2022, 2021]

    def test_header_years_falls_back_when_shallow_empty(self):
        rows = [["PT ABC", None]] * 6
        rows.append(["2023", "2022", None])
        assert _header_years(rows) == [2023, 2022]

    def test_shallow_result_wins_and_is_not_polluted(self):
        """A deeper scan on a table that already has a header picks up
        unrelated body years (AALI p167 returned 2016 beside 2022/2021), which
        would mis-zip every column. Shallow must therefore take precedence."""
        rows = [["31 DESEMBER 2022 DAN 2021", None]]
        rows += [["catatan kaki", None]] * 5
        rows += [["2016", None]] * 4
        assert _header_years(rows) == [2022, 2021]

    def test_year_zip_requires_matching_column_count(self):
        """More values than header columns means the columns are not the
        header's columns; zipping anyway mislabels every figure."""
        pt = PageTable(page_number=1)
        _process_table([["2022", "2021"],
                        ["Aktivitas Operasi", "1.835", "4.895", "9.999"]], pt)
        assert pt.rows[0].values == [(None, "1.835"), (None, "4.895"), (None, "9.999")]

    def test_matching_column_count_does_zip(self):
        pt = PageTable(page_number=1)
        _process_table([["2022", "2021"], ["Aktivitas Operasi", "1.835", "4.895"]], pt)
        assert pt.rows[0].values == [(2022, "1.835"), (2021, "4.895")]


class TestHeaderYearOrdering:
    """Bug 3b: header years read in text order are not in column order.

    AALI's 2021 equity statement prints the current year first, but the header
    was read as [2020, 2021], so 21,171,173 (a 2021 figure) was stored as 2020
    and 19,247,794 (a 2020 figure) as 2021. Statements put the reporting period
    in the first value column, so the detected list is anchored on it.
    """

    def test_reporting_year_moved_to_front(self):
        assert order_header_years([2020, 2021], 2021) == [2021, 2020]

    def test_already_ordered_is_unchanged(self):
        assert order_header_years([2021, 2020], 2021) == [2021, 2020]

    def test_single_year_unchanged(self):
        assert order_header_years([2020], 2021) == [2020]

    def test_year_absent_from_header_is_not_invented(self):
        assert order_header_years([2018, 2019], 2021) == [2018, 2019]

    def test_no_preferred_year_is_a_noop(self):
        assert order_header_years([2020, 2021], None) == [2020, 2021]

    def test_empty_header_unchanged(self):
        assert order_header_years([], 2021) == []

    def test_three_column_statement(self):
        assert order_header_years([2020, 2021, 2022], 2022) == [2022, 2020, 2021]

    def test_end_to_end_zip_uses_ordered_years(self):
        """The real AALI p138 shape: values are current-year-first."""
        from app.extraction.table_extractor import PageTable

        pt = PageTable(page_number=138)
        _process_table([["31 DESEMBER 2020 DAN 2021"],
                        ["Total ekuitas", "21,171,173", "19,247,794"]],
                       pt, preferred_year=2021)
        assert pt.rows[0].values == [(2021, "21,171,173"), (2020, "19,247,794")]

    def test_process_table_signature_still_defaults(self):
        """Existing callers pass only (table, page_table)."""
        pt = PageTable(page_number=1)
        _process_table([["2020", "2021"], ["X", "1", "2"]], pt)
        assert pt.rows[0].values == [(2020, "1"), (2021, "2")]


class TestExportPlausibilityFlags:
    """Bug 4: implausible magnitudes were emitted silently.

    'Dampak Perubahan Harga terhadap Penjualan' -> revenue = 72 juta is a
    percentage column read as currency. The CSV marks such rows instead of
    letting them blend into the totals.
    """

    def test_tiny_amount_flagged(self):
        # 72 juta: above a naive 1e6 floor, still nonsense for a listed company.
        assert _flag(72_000_000, "juta", "sales_and_revenue", "IDR") == (
            "IMPLAUSIBLE_MAGNITUDE")

    def test_plausible_amount_not_flagged(self):
        assert _flag(27_781_231_000_000, "juta", "total_assets") == ""

    def test_none_not_flagged(self):
        assert _flag(None) == ""

    def test_negative_large_amount_not_flagged(self):
        assert _flag(-1_179_794_000_000, "juta", "cost_of_revenue") == ""

    def test_threshold_boundary(self):
        floor = minimum_plausible_monetary("IDR", "juta")
        assert _flag(floor, "juta", "sales_and_revenue", "IDR") == ""
        assert _flag(floor - 1, "juta", "sales_and_revenue", "IDR") == (
            "IMPLAUSIBLE_MAGNITUDE")

    def test_share_counts_exempt_from_monetary_floor(self):
        """500,000 treasury shares is correct, not a misparse."""
        assert _flag(500_000, "shares", "treasury_shares_quantity") == ""

    def test_percentages_exempt(self):
        assert _flag(1.5, "percent", "treasury_shares_percentage") == ""


class TestFloorIsCurrencyAndScaleAware:
    """The floor used to be one rupiah constant applied to everything.

    That flagged correct figures: a -$122.9m annual loss is ordinary for a
    listed company, and a filer reporting in whole rupiah legitimately shows a
    non-controlling interest of 19,757. Both were marked IMPLAUSIBLE.
    """

    def test_usd_loss_is_not_judged_against_a_rupiah_floor(self):
        """PMMP 2024 total_profit_loss, verbatim from the corpus."""
        assert _flag(-122_921_818, None, "total_profit_loss", "USD") == ""

    def test_whole_rupiah_report_has_no_floor(self):
        """A filer stating plain rupiah has no multiplier to have mis-read."""
        assert _flag(19_757, None, "non_controlling_interest", "IDR") == ""
        assert _flag(1_000, None, "non_controlling_interest", "IDR") == ""

    def test_small_scaled_figure_is_still_real(self):
        """'(848,687)' ribu is 848,687,000 -- a real, if small, tax payment.

        A row read at a stated scale is still held to its currency's floor, so
        this one is flagged. That is the conservative side of the trade: the
        floor for scaled rows was left alone deliberately, because 897 juta and
        999 juta are the same order of magnitude and no magnitude alone tells
        them apart. Distinguishing them needs a per-field floor.
        """
        assert _flag(848_687_000, "ribuan", "income_tax_paid_operating", "IDR") == (
            "IMPLAUSIBLE_MAGNITUDE")

    def test_a_figure_that_lost_a_factor_is_still_caught(self):
        """'0.897' read as juta is 897,000 -- the raw had no integer part."""
        assert _flag(897_000, "juta", "other_equity_components", "IDR") == (
            "IMPLAUSIBLE_MAGNITUDE")

    def test_ceiling_is_unaffected_by_currency(self):
        """A unit applied too many times is wrong in any currency."""
        assert _flag(2e17, "juta", "total_assets", "IDR") == "IMPLAUSIBLE_SCALE"
        assert _flag(2e17, "juta", "total_assets", "USD") == "IMPLAUSIBLE_SCALE"

    def test_plain_unit_rows_still_reject_fragments(self):
        """Dropping the rupiah floor must not open the door to page numbers."""
        assert minimum_plausible_monetary("IDR", None) == 1_000.0
        assert _flag(37, None, "cash_and_cash_equivalents", "IDR") == (
            "IMPLAUSIBLE_MAGNITUDE")
        assert _flag(5e17, None, "cash_and_cash_equivalents", "IDR") == (
            "IMPLAUSIBLE_SCALE")

    def test_zero_is_never_implausible(self):
        assert _flag(0, None, "non_controlling_interest", "IDR") == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])