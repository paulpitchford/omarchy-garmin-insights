from pathlib import Path


def test_panel_keeps_action_footer_outside_scrollable_content() -> None:
    panel = (Path(__file__).parents[1] / "Panel.qml").read_text()

    assert "Style.space(640))" in panel
    assert "anchors.bottom: panelFooter.top" in panel
    assert "Controls.ScrollBar.vertical: Controls.ScrollBar" in panel
    assert "active: scroll.interactive" in panel
    assert "id: panelFooter" in panel
    assert "contentColumn.implicitHeight + panelFooter.implicitHeight" in panel
    assert "onViewModeChanged: scroll.contentY = 0" in panel
