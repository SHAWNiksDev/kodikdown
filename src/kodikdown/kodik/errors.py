class KodikError(Exception):
    """Base class for all kodikdown failures."""


class InvalidUrlError(KodikError):
    """The pasted text does not contain a recognizable player embed."""


class PageStructureError(KodikError):
    """Player page or its scripts changed beyond what we know how to parse."""


class NoStreamsError(KodikError):
    """The server answered, but no playable streams were found."""


class RequestFailedError(KodikError):
    """Network request to the player failed."""
