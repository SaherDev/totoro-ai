"""Legacy extraction dispatcher — kept for UnsupportedInputError only."""


class UnsupportedInputError(Exception):
    """Raised when no extractor supports the given input."""

    pass
