"""XBRL/HTML ingestion: folder scanning, cover scale, and table shape.

The corpus under ``XBRL/`` is organised ``<company>/<year>/<statement>.html``.
Three things here are easy to get wrong and silently produce plausible but wrong
numbers, so each is pinned:

1. Year comes from the *folder*, not the filename -- statement filenames are
   taxonomy codes (``1321000.html``) and carry no year at all.
2. One folder is one document. The cover holds the presentation scale and no
   statement page repeats it; read per-file, every figure is out by 10^3-10^6.
3. The income statement is not always ``1321000``. A 2020/2021 filing used
   ``1311000`` for the same statement, so identity comes from the page title.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.extraction.html_source import (  # noqa: E402
    is_html_path,
    read_declared_currency,
    read_declared_scale,
    read_document,
    read_html_file,
)
from app.ingestion.scanner import scan_directory  # noqa: E402

# Real cover layout is a three-column row rendered on consecutive lines:
# Indonesian label, the value, then the English label. Verified against
# AALI 2024, where the value sits directly above the English label.
COVER = """<html><body><table>
<tr><td>Pembulatan yang digunakan dalam penyajian jumlah dalam laporan keuangan</td></tr>
<tr><td>{scale}</td></tr>
<tr><td>Level of rounding used in financial statements</td></tr>
</table></body></html>"""

STATEMENT = """<html><body><table>
<tr><th></th><th colspan="2">{year}</th><th>vs</th><th>{prior}</th></tr>
<tr><th>Descriptions</th><th>{year}</th><th>{prior}</th><th>Descriptions</th></tr>
<tr><td>Penjualan</td><td>21,815,035</td><td>20,745,473</td><td>Sales</td></tr>
<tr><td>Beban pokok penjualan</td><td>( 18,474,414 )</td><td>( 17,974,493 )</td><td>Cost of goods</td></tr>
<tr><td>Laba bruto</td><td>3,340,621</td><td>2,770,980</td><td>Gross profit</td></tr>
</table></body></html>"""


def _write_filing(root: Path, company: str, year: int, scale: str,
                  income_filename: str = "1321000.html") -> Path:
    folder = root / company / str(year)
    folder.mkdir(parents=True)
    (folder / "1000000.html").write_text(
        COVER.format(scale=scale), encoding="utf-8")
    (folder / income_filename).write_text(
        STATEMENT.format(year=year, prior=year - 1), encoding="utf-8")
    (folder / "1210000.html").write_text(
        STATEMENT.format(year=year, prior=year - 1), encoding="utf-8")
    return folder


class TestScanDirectory:
    def test_one_document_per_filing_folder(self, tmp_path):
        """Six HTML files across two companies is two documents, not six."""
        _write_filing(tmp_path, "PT AAA Tbk", 2024, "Jutaan / In Million")
        _write_filing(tmp_path, "PT AAA Tbk", 2023, "Jutaan / In Million")
        _write_filing(tmp_path, "PT BBB Tbk", 2024, "Satuan Penuh / Full Amount")

        found = scan_directory(tmp_path)

        assert len(found) == 3
        assert sorted(f.filename_year for f in found) == [2023, 2024, 2024]
        assert sorted(f.company for f in found) == ["PT AAA Tbk", "PT AAA Tbk", "PT BBB Tbk"]

    def test_year_read_from_folder_not_filename(self, tmp_path):
        """Filenames are taxonomy codes, so only the folder states the year."""
        folder = _write_filing(tmp_path, "PT AAA Tbk", 2021, "Jutaan / In Million")
        assert (folder / "1321000.html").exists()

        found = scan_directory(tmp_path)

        assert found[0].filename_year == 2021
        # The year must survive in the filename too, since the processor reads
        # it back from there when reporting_year is unset.
        assert "2021" in found[0].filename

    def test_anchors_on_cover(self, tmp_path):
        folder = _write_filing(tmp_path, "PT AAA Tbk", 2024, "Jutaan / In Million")
        found = scan_directory(tmp_path)
        assert found[0].path == folder / "1000000.html"

    def test_falls_back_to_first_html_without_cover(self, tmp_path):
        folder = tmp_path / "PT AAA Tbk" / "2024"
        folder.mkdir(parents=True)
        (folder / "1210000.html").write_text(
            STATEMENT.format(year=2024, prior=2023), encoding="utf-8")

        found = scan_directory(tmp_path)

        assert len(found) == 1
        assert found[0].path == folder / "1210000.html"

    def test_skips_folder_with_no_year_in_name(self, tmp_path):
        _write_filing(tmp_path, "PT AAA Tbk", 2024, "Jutaan / In Million")
        stray = tmp_path / "PT AAA Tbk" / "notes"
        stray.mkdir()
        (stray / "1000000.html").write_text("<html></html>", encoding="utf-8")

        assert len(scan_directory(tmp_path)) == 1

    def test_pdf_corpus_still_scans_one_file_per_pdf(self, tmp_path):
        """The legacy layout must keep working."""
        (tmp_path / "PT AAA Tbk").mkdir()
        (tmp_path / "PT AAA Tbk" / "laporan-2024.pdf").write_bytes(b"%PDF-1.4")

        found = scan_directory(tmp_path)

        assert len(found) == 1
        assert found[0].filename_year == 2024

    def test_missing_root_is_rejected(self, tmp_path):
        from app.core.exceptions import SecurityError

        with pytest.raises(SecurityError):
            scan_directory(tmp_path / "nope")

    def test_html_detected_two_levels_down(self, tmp_path):
        """Regression: probing only the root missed <company>/<year>/*.html and
        the corpus was misread as PDF, yielding zero filings."""
        _write_filing(tmp_path, "PT AAA Tbk", 2024, "Jutaan / In Million")
        assert len(scan_directory(tmp_path)) == 1


class TestDeclaredScale:
    # (declared cover text) -> (normalised unit name, multiplier). A unit name of
    # None means full rupiah: the cover explicitly stated no scaling was applied.
    @pytest.mark.parametrize("scale,expected", [
        ("Satuan Penuh / Full Amount", (None, 1)),
        ("Jutaan / In Million", ("juta", 1_000_000)),
        ("Ribuan / In Thousand", ("ribuan", 1_000)),
        ("Miliaran / In Billion", ("miliar", 1_000_000_000)),
        ("Triliun / In Trillion", ("triliun", 1_000_000_000_000)),
    ])
    def test_declared_scales_normalise(self, scale, expected):
        assert read_declared_scale(COVER.format(scale=scale)) == expected

    def test_returns_none_when_undeclared(self):
        assert read_declared_scale("<html><body>no scale here</body></html>") is None

    def test_read_from_whole_document(self, tmp_path):
        folder = _write_filing(tmp_path, "PT AAA Tbk", 2024, "Jutaan / In Million")
        doc = read_document(folder / "1000000.html", preferred_year=2024)
        assert doc.declared_unit == ("juta", 1_000_000)


# Same three-line cover shape as the scale, ending in the English label.
CURRENCY_COVER = """<html><body><table>
<tr><td>Previous field value</td></tr>
<tr><td>Mata uang pelaporan</td></tr>
<tr><td>{currency}</td></tr>
<tr><td>Description of presentation currency</td></tr>
</table></body></html>"""


class TestDeclaredCurrency:
    @pytest.mark.parametrize("declared,expected", [
        ("Rupiah / IDR", "IDR"),
        ("Dollar Amerika / USD", "USD"),
        ("Singapore Dollar / SGD", "SGD"),
        ("Euro / EUR", "EUR"),
    ])
    def test_reads_iso_code(self, declared, expected):
        assert read_declared_currency(CURRENCY_COVER.format(currency=declared)) == expected

    def test_name_without_iso_code(self):
        assert read_declared_currency(
            CURRENCY_COVER.format(currency="Rupiah")) == "IDR"

    def test_returns_none_when_undeclared(self):
        assert read_declared_currency("<html><body>nothing here</body></html>") is None

    def test_not_hardcoded_to_idr(self):
        """17 of the 545 real filings present in USD, so assuming IDR would
        mislabel them."""
        assert read_declared_currency(
            CURRENCY_COVER.format(currency="Dollar Amerika / USD")) != "IDR"

    def test_ignores_the_line_above_the_indonesian_label(self):
        """The Indonesian label sits above its own value, so a naive
        'read the line above the first label' returns the previous field."""
        html = CURRENCY_COVER.format(currency="Rupiah / IDR")
        assert read_declared_currency(html) == "IDR"
        assert "Previous field value" not in str(read_declared_currency(html))

    def test_read_from_whole_document(self, tmp_path):
        folder = _write_filing(tmp_path, "PT AAA Tbk", 2024, "Jutaan / In Million")
        (folder / "1000000.html").write_text(
            CURRENCY_COVER.format(currency="Rupiah / IDR"), encoding="utf-8")
        doc = read_document(folder / "1000000.html", preferred_year=2024)
        assert doc.declared_currency == "IDR"


class TestStatementParsing:
    def test_reuses_pdfplumber_shaped_table(self, tmp_path):
        folder = _write_filing(tmp_path, "PT AAA Tbk", 2024, "Jutaan / In Million")
        page = read_html_file(folder / "1321000.html", preferred_year=2024)

        # header_years[0] is the filing year, so values[0] is the current year.
        assert page.table.header_years[:2] == [2024, 2023]
        labels = [r.row_label for r in page.table.rows]
        assert "Penjualan" in labels

        revenue = next(r for r in page.table.rows if r.row_label == "Penjualan")
        assert revenue.values[0] == (2024, "21,815,035")

    def test_parenthesised_values_are_preserved(self, tmp_path):
        """The number parser turns "( 18,474,414 )" into a negative; the parser
        must not strip the sign."""
        folder = _write_filing(tmp_path, "PT AAA Tbk", 2024, "Jutaan / In Million")
        page = read_html_file(folder / "1321000.html", preferred_year=2024)
        row = next(r for r in page.table.rows if r.row_label == "Beban pokok penjualan")
        assert row.values[0] == (2024, "( 18,474,414 )")

    def test_taxonomy_variant_1311000_parses_identically(self, tmp_path):
        """2020/2021 filings used 1311000 for the income statement."""
        folder = _write_filing(
            tmp_path, "PT AAA Tbk", 2020, "Ribuan / In Thousand",
            income_filename="1311000.html")

        doc = read_document(folder / "1000000.html", preferred_year=2020)
        income = [p for p in doc.pages if "Penjualan" in p.text]
        assert income, "1311000.html should still be parsed as a page"

    def test_document_pages_cover_every_statement(self, tmp_path):
        folder = _write_filing(tmp_path, "PT AAA Tbk", 2024, "Jutaan / In Million")
        doc = read_document(folder / "1000000.html", preferred_year=2024)
        assert len(doc.pages) == 3

    def test_cover_is_read_first_regardless_of_filename_order(self, tmp_path):
        """The scale lives on the cover; the processor needs it before anything
        else, so ordering must not depend on the taxonomy code."""
        folder = _write_filing(tmp_path, "PT AAA Tbk", 2024, "Jutaan / In Million")
        doc = read_document(folder / "1210000.html", preferred_year=2024)
        assert doc.pages[0].path.name == "1000000.html"

    def test_html_files_are_bounded_by_max_pages(self, tmp_path):
        folder = _write_filing(tmp_path, "PT AAA Tbk", 2024, "Jutaan / In Million")
        doc = read_document(folder / "1000000.html", preferred_year=2024, max_pages=2)
        assert len(doc.pages) == 2


class TestIsHtmlPath:
    @pytest.mark.parametrize("name,expected", [
        ("1000000.html", True), ("1410000PY.htm", True),
        ("instance.xbrl", False), ("laporan.pdf", False),
    ])
    def test_suffix_detection(self, name, expected):
        assert is_html_path(name) is expected