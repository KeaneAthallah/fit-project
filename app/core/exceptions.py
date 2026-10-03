"""Custom exceptions for the pipeline."""


class FinanceExtractorError(Exception):
    """Base application error."""


class DocumentNotFoundError(FinanceExtractorError):
    pass


class PDFParseError(FinanceExtractorError):
    pass


class OCRError(FinanceExtractorError):
    pass


class AIProviderError(FinanceExtractorError):
    pass


class ExtractionError(FinanceExtractorError):
    pass


class ValidationError(FinanceExtractorError):
    pass


class ExportError(FinanceExtractorError):
    pass


class SecurityError(FinanceExtractorError):
    """Raised when a path or operation violates security rules."""
