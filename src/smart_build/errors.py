class SmartBuildError(Exception):
    """Base exception with a stable user-facing error code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
