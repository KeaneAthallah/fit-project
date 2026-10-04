"""What `confidence` means.

Confidence answers one question: how authoritative was the page this figure was
read from. It deliberately carries no term for label matching, because matching
is exact -- a label either is the registered wording or it is not -- so scoring
the match only ever added a constant that crowded out the distinction worth
showing.
"""
from __future__ import annotations

import pytest

from app.core.config import ConfidenceConfig
from app.financial.mappings import FIELD_LABELS, map_label
from app.pipeline.processor import (
    CONFIDENCE_HEADER_ZIPPED,
    CONFIDENCE_INDIRECT,
    CONFIDENCE_STATEMENT_PAGE,
    page_confidence,
)


class TestPageAuthorityScale:
    def test_primary_statement_page_is_certain(self):
        for statement in ("balance_sheet", "income_statement", "cash_flow", "equity"):
            assert page_confidence(statement) == CONFIDENCE_STATEMENT_PAGE == 1.0

    def test_header_zipped_is_one_step_down(self):
        assert page_confidence(None, year_from_header=True) == CONFIDENCE_HEADER_ZIPPED

    def test_unsectioned_or_notes_page_is_lowest(self):
        assert page_confidence(None) == CONFIDENCE_INDIRECT
        # A section that is not one of the statements is not authority either.
        assert page_confidence("notes") == CONFIDENCE_INDIRECT

    def test_the_scale_is_ordered(self):
        assert CONFIDENCE_STATEMENT_PAGE > CONFIDENCE_HEADER_ZIPPED > CONFIDENCE_INDIRECT


class TestMatchingContributesNothing:
    def test_every_registered_label_resolves_certainly(self):
        """No registered label may score below 1.0.

        Sweeping the whole registry is the point: reintroducing a tier for, say,
        split-cell labels would quietly reintroduce the constant, and a single
        hand-picked label would not catch it.
        """
        underconfident = {}
        unmapped = []
        for statement, fields in FIELD_LABELS.items():
            for _field, labels in fields.items():
                for label in labels:
                    got, conf = map_label(label, statement)
                    if got is None:
                        unmapped.append((statement, label))
                    elif conf != 1.0:
                        underconfident[label] = (statement, got, conf)
        assert not unmapped, unmapped
        assert not underconfident, underconfident

    def test_no_intermediate_score_is_reachable(self):
        """map_label returns a match indicator, not a graded score."""
        assert map_label("Total aset tidak lancar", "balance_sheet") == (
            "non_current_assets", 1.0,
        )
        assert map_label("Biaya peluang aneh sekali", "income_statement") == (None, 0.0)

    def test_a_split_label_is_still_certain(self):
        """Being chopped across table cells does not make a label less certain."""
        assert map_label("Total aset tidak lan car", "balance_sheet") == (
            "non_current_assets", 1.0,
        )


class TestReviewThresholdIsReachable:
    """A threshold nothing can fall below is a threshold that never fires.

    The old 0.50 sat below every score the extractor could produce, so
    REVIEW_REQUIRED never appeared on any row. It now sits above the indirect
    tier so a figure read off a notes page is the thing that gets flagged.
    """

    def test_threshold_sits_between_the_lowest_tier_and_the_middle_one(self):
        cfg = ConfidenceConfig()
        assert CONFIDENCE_INDIRECT < cfg.review_threshold <= CONFIDENCE_HEADER_ZIPPED

    def test_a_notes_page_figure_is_flagged_and_a_statement_figure_is_not(self):
        cfg = ConfidenceConfig()
        assert page_confidence(None) < cfg.review_threshold
        assert page_confidence("balance_sheet") >= cfg.review_threshold

    @pytest.mark.parametrize("statement", ["balance_sheet", "income_statement"])
    def test_no_primary_statement_figure_is_ever_flagged(self, statement):
        """An exact label off the face of a statement must pass as OK."""
        cfg = ConfidenceConfig()
        assert page_confidence(statement) >= cfg.review_threshold


class TestConfidenceIsNotAMatchScore:
    def test_same_label_different_page_gives_different_confidence(self):
        """The number moves with the page, not with the label.

        This is the distinction the old scheme could not express: both figures
        were exact label matches, and under `map_conf * 0.9` both stored 0.9, so
        the rank column and the confidence column agreed on nothing.
        """
        statement_page = page_confidence("balance_sheet")
        notes_page = page_confidence(None)
        assert statement_page != notes_page
        assert statement_page > notes_page