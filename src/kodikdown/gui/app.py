"""Application bootstrap: Qt setup, theme, crash handling."""

from __future__ import annotations

import logging
import sys
import traceback
from types import TracebackType

from PySide6.QtWidgets import QApplication, QMessageBox

from kodikdown import __version__
from kodikdown.config import ConfigStore
from kodikdown.gui.icons import app_icon
from kodikdown.gui.main_window import MainWindow
from kodikdown.gui.theme import palette_for
from kodikdown.i18n import set_language, t

logger = logging.getLogger(__name__)


def run(argv: list[str] | None = None) -> int:
    # A windowed Windows build has no streams at all.
    if sys.stderr is not None:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    # One line per HTTP request is far too chatty for a desktop app.
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    application = QApplication(argv if argv is not None else sys.argv)
    application.setApplicationName("KodikDown")
    application.setApplicationDisplayName("KodikDown")
    application.setApplicationVersion(__version__)
    application.setOrganizationName("KodikDown")
    application.setDesktopFileName("kodikdown")
    application.setWindowIcon(app_icon(palette_for("auto").accent))
    # Fusion renders the same on every platform, which keeps the stylesheet
    # predictable across Windows and the various Linux desktops.
    application.setStyle("Fusion")

    store = ConfigStore()
    settings = store.load()
    set_language(settings.language)
    _install_excepthook()

    window = MainWindow(store, settings)
    window.show()
    url = _url_argument(argv if argv is not None else sys.argv)
    if url:
        window.prefill(url)
    return application.exec()


def _url_argument(argv: list[str]) -> str:
    """`kodikdown <link>` opens the window with the lookup already running."""
    for argument in argv[1:]:
        if not argument.startswith("-"):
            return argument
    return ""


def _install_excepthook() -> None:
    def handle(
        exc_type: type[BaseException],
        value: BaseException,
        tb: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, value, tb)
            return
        logger.error("unhandled exception", exc_info=(exc_type, value, tb))
        detail = "".join(traceback.format_exception_only(exc_type, value)).strip()
        QMessageBox.critical(None, t("app_title"), t("unexpected_error", detail=detail))

    sys.excepthook = handle
