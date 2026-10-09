from __future__ import annotations

import os
from pathlib import Path

import pytest

# Qt tests must not need a display; this has to be set before Qt is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FIXTURES = Path(__file__).parent / "fixtures"

# Minimal copy of the current player markup: signed urlParams with a percent
# encoded referer, the loose globals a few mirrors still emit, and the
# translation <option> list.
_SIGNED_JSON = (
    '{"d":"animego.org","d_sign":"aa:1","pd":"kodikplayer.com","pd_sign":"bb:1",'
    '"ref":"https%3A%2F%2Fanimego.org%2F","ref_sign":"cc:1"}'
)
SERIAL_PAGE = (
    "<!doctype html>\n<html><head>\n"
    "  <title>Kodik Player</title>\n"
    '  <script type="text/javascript">\n'
    '    var type = "seria";\n'
    '    var videoId = "1304528";\n'
    f"    var urlParams = '{_SIGNED_JSON}';\n"
    "    var translationId = 735;\n"
    '    var translationTitle = "2x2";\n'
    "  </script>\n"
    '  <script src="/assets/js/app.player_single.deadbeef.js"></script>\n'
    "</head><body>\n"
    '  <div class="movie-translations-box">\n'
    "    <select>\n"
    '      <option value="610" data-id="610" data-translation-type="voice"\n'
    '        data-media-id="102509" data-media-hash="E5AF7227AE1DE504D41F753C59C7B4BA"\n'
    '        data-media-type="video" data-title="AniLibria.TV">AniLibria.TV</option>\n'
    '      <option value="735" data-id="735" data-translation-type="voice"\n'
    '        data-media-id="1304528" data-media-hash="932d5da818729ec5ccc9be7968ee3717"\n'
    '        data-media-type="seria" data-title="2x2" selected="selected">2x2</option>\n'
    "    </select>\n"
    "  </div>\n"
    "  <script>\n"
    "    var vInfo = {};\n"
    "    vInfo.type = 'seria';\n"
    "    vInfo.hash = '932d5da818729ec5ccc9be7968ee3717';\n"
    "    vInfo.id = '1304528';\n"
    "  </script>\n"
    "</body></html>\n"
)


@pytest.fixture(autouse=True)
def _deterministic_ui_language(monkeypatch: pytest.MonkeyPatch):
    """Keep messages and auto-detection from depending on the host locale."""
    from kodikdown.i18n import set_language

    monkeypatch.setenv("LANG", "en_US.UTF-8")
    for name in ("LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        monkeypatch.delenv(name, raising=False)
    set_language("en")
    yield
    set_language("en")


@pytest.fixture()
def serial_page_html() -> str:
    return SERIAL_PAGE


@pytest.fixture()
def player_page_html() -> str:
    return (FIXTURES / "player_page.html").read_text(encoding="utf-8")


@pytest.fixture()
def player_js_snippet() -> str:
    return (FIXTURES / "player_bundle_snippet.js").read_text(encoding="utf-8")


@pytest.fixture()
def video_info_json() -> dict[str, object]:
    import json

    return json.loads((FIXTURES / "video_info_response.json").read_text(encoding="utf-8"))
