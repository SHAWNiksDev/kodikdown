from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


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
