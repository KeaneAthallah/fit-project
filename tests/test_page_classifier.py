import pytest

from app.extraction.page_classifier import (
    classify_section,
    is_parent_only_page,
    is_relevant_page,
)


class TestSectionClassification:
    def test_balance_sheet_id(self):
        assert classify_section("LAPORAN POSISI KEUANGAN\nPT ABC\nAset") == "balance_sheet"

    def test_neraca(self):
        assert classify_section("NERACA\n30 Juni 2023") == "balance_sheet"

    def test_income_statement(self):
        assert classify_section("Laporan Laba Rugi\nUntuk tahun yang berakhir") == "income_statement"

    def test_cash_flow(self):
        assert classify_section("LAPORAN ARUS KAS\nAktivitas operasi") == "cash_flow"

    def test_equity(self):
        assert classify_section("LAPORAN PERUBAHAN EKUITAS") == "equity"

    def test_notes(self):
        assert classify_section("CATATAN ATAS LAPORAN KEUANGAN") == "notes"

    def test_english(self):
        assert classify_section("STATEMENT OF CASH FLOWS") == "cash_flow"
        assert classify_section("Balance Sheet") == "balance_sheet"

    def test_unclassified(self):
        assert classify_section("Direksi dan komisaris PT ABC") is None


class TestParentOnlyDetection:
    """Parent-only ('entitas induk') statements are a different reporting
    entity from the consolidated group and must never be merged into it."""

    def test_consolidated_page_is_not_parent_only(self):
        text = (
            "PT FKS FOOD SEJAHTERA TBK\n"
            "DAN ENTITAS ANAKNYA\n"
            "LAPORAN POSISI KEUANGAN\n"
            "KONSOLIDASIAN\n"
        )
        assert not is_parent_only_page(text)

    def test_parent_marker_line_above_title(self):
        text = (
            "PT FKS FOOD SEJAHTERA TBK\n"
            "(Dahulu PT TIGA PILAR SEJAHTERA FOOD TBK)\n"
            "(Entitas Induk)\n"
            "LAPORAN POSISI KEUANGAN\n"
            "Tanggal 31 Desember 2021\n"
        )
        assert is_parent_only_page(text)

    def test_english_parent_only(self):
        text = (
            "PT FKS FOOD SEJAHTERA TBK\n"
            "(Parent Only)\n"
            "STATEMENT OF FINANCIAL POSITION\n"
            "As of December 31, 2021\n"
        )
        assert is_parent_only_page(text)

    def test_supplementary_information_header(self):
        text = (
            "INFORMASI KEUANGAN TAMBAHAN\n"
            "Informasi berikut adalah laporan keuangan Entitas\n"
            "Induk PT FKS Food Sejahtera Tbk, yang merupakan\n"
            "informasi tambahan dalam laporan keuangan\n"
        )
        assert is_parent_only_page(text)

    def test_subsidiary_marker_is_not_parent_only(self):
        """'DAN ENTITAS ANAK' means subsidiaries, the opposite of parent-only.
        A loose 'entitas induk' substring search matches notes prose and must
        not be used here."""
        text = (
            "PT ASIA SEJAHTERA MINA, Tbk\n"
            "DAN ENTITAS ANAK\n"
            "CATATAN ATAS LAPORAN KEUANGAN\n"
            "KONSOLIDASIAN (Lanjutan)\n"
        )
        assert not is_parent_only_page(text)

    def test_consolidated_marker_wins_in_same_window(self):
        text = (
            "(Entitas Induk)\n"
            "PT ASIA SEJAHTERA MINA, Tbk\n"
            "DAN ENTITAS ANAK\n"
            "LAPORAN POSISI KEUANGAN\n"
        )
        assert not is_parent_only_page(text)

    def test_boilerplate_notes_header_is_not_parent_only(self):
        """Every page of a report carries the consolidated notes boilerplate."""
        text = (
            "The original consolidated financial statements included herein\n"
            "are in Indonesian language.\n"
            "Catatan atas laporan keuangan konsolidasian terlampir\n"
            "merupakan bagian yang tidak terpisahkan dari laporan\n"
            "keuangan konsolidasian secara keseluruhan.\n"
            "Investasi pada entitas induk\n"
        )
        assert not is_parent_only_page(text)

    def test_ordinary_statement_page(self):
        text = "LAPORAN POSISI KEUANGAN\nTotal Aset 1.234.567\n"
        assert not is_parent_only_page(text)

    def test_empty_text(self):
        assert not is_parent_only_page("")


class TestRelevance:
    def test_relevant_statement_page(self):
        text = "Aset Lancar Kas Piutang Persediaan Total Aset Liabilitas Ekuitas"
        assert is_relevant_page(text)

    def test_irrelevant_page(self):
        assert not is_relevant_page("Surat izin usaha Perusahaan ini didirikan pada tahun 1998")


if __name__ == "__main__":
    pytest.main([__file__])
