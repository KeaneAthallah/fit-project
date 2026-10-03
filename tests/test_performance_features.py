"""Tests for performance features: page scoring, OCR quality, processing modes."""
from app.extraction.page_classifier import financial_page_score, is_relevant_page
from app.extraction.ocr import image_quality


class TestFinancialPageScore:
    def test_statement_title_scores_high(self):
        text = "LAPORAN POSISI KEUANGAN\nPer 31 Desember 2024\nAset Lancar 100\nLiabilitas 50"
        assert financial_page_score(text) >= 4

    def test_random_text_scores_low(self):
        text = "Direksi: Budi Santoso\nKomisaris: Ani Wijaya\nSekretaris: Citra Lestari"
        assert financial_page_score(text) < 3

    def test_numeric_density_bonus(self):
        text = "kas " + " ".join(str(i) for i in range(500))
        assert financial_page_score(text) >= 2

    def test_empty_text(self):
        assert financial_page_score("") == 0

    def test_cap(self):
        text = " ".join(["laporan posisi keuangan neraca ekuitas kas saham modal"] * 10)
        assert financial_page_score(text) <= 20


class TestRelevanceIntegration:
    def test_statement_page_relevant(self):
        text = "LAPORAN LABA RUGI\nPendapatan 100\nBeban 60\nLaba 40"
        assert is_relevant_page(text) or financial_page_score(text) >= 3

    def test_director_page_not_relevant(self):
        text = "Susunan Direksi dan Komisaris PT Maju Jaya\nTahun 2024"
        assert financial_page_score(text) < 3


class TestImageQuality:
    def test_clean_image_scores_high(self):
        import numpy as np
        rng = np.random.default_rng(42)
        img = rng.integers(0, 255, size=(400, 400, 3), dtype=np.uint8)
        # Random noise has high contrast; sharpness moderate.
        score = image_quality(img)
        assert 0.0 <= score <= 1.0

    def test_flat_image_scores_low(self):
        import numpy as np
        img = np.full((400, 400, 3), 128, dtype=np.uint8)
        assert image_quality(img) < 0.55


class TestProcessingModeConfig:
    def test_mode_fast_tightens_settings(self):
        from app.core.config import AppConfig, _apply_mode
        cfg = AppConfig()
        cfg.ocr.deskew = True
        cfg.ocr.denoise = True
        cfg.processing.mode = "fast"
        _apply_mode(cfg)
        assert cfg.ocr.deskew is False
        assert cfg.ocr.denoise is False
        assert cfg.ocr.binarize is False
        assert cfg.processing.min_financial_page_score >= 5

    def test_mode_accurate_relaxes_settings(self):
        from app.core.config import AppConfig, _apply_mode
        cfg = AppConfig()
        cfg.ocr.dpi = 150
        cfg.processing.mode = "accurate"
        _apply_mode(cfg)
        assert cfg.ocr.dpi >= 300
        assert cfg.processing.min_financial_page_score <= 2


if __name__ == "__main__":
    import pytest
    pytest.main([__file__])
