class ApiError(Exception):
    """An error that is safe to show to the caller: becomes {"message": ...} with the given HTTP status."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class DuplicateKey(Exception):
    """Raised by a store when an insert collides with an existing tracking ID."""
