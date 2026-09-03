from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_panel_keeps_action_footer_outside_scrollable_content() -> None:
    panel = (ROOT / "Panel.qml").read_text(encoding="utf-8")

    assert "Style.space(640))" in panel
    assert "anchors.bottom: panelFooter.top" in panel
    assert "Controls.ScrollBar.vertical: Controls.ScrollBar" in panel
    assert "active: scroll.interactive" in panel
    assert "id: panelFooter" in panel
    assert "contentColumn.implicitHeight + panelFooter.implicitHeight" in panel
    assert "onViewModeChanged: scroll.contentY = 0" in panel


def test_production_shell_uses_public_panel_fitting_and_widget_anchor() -> None:
    widget = (ROOT / "BarWidget.qml").read_text(encoding="utf-8")
    shell = (ROOT / "PanelShell.qml").read_text(encoding="utf-8")

    assert 'source: Qt.resolvedUrl("PanelShell.qml")' in widget
    assert "panel.fittedContentWidth(Style.space(600))" in shell
    assert "panel.fittedContentHeight(" in shell
    assert "Style.space(session.modeIndex === 0 ? 600 : 800)" in shell
    assert "target.anchorItem = button" in widget
    assert "anchorItem: root.anchorItem" in shell
    assert "centerOnBar: false" in shell
    assert "readonly property bool wideLayout: panel.contentWidth >= Style.space(520)" in shell
    assert "anchors.top: shellHeader.bottom" in shell
    assert "anchors.bottom: shellFooter.top" in shell
    assert "Controls.ScrollBar.vertical: Controls.ScrollBar" in shell
    assert "PointerMoveGate {" in shell
    assert "referenceItem: keyCatcher" in shell
    assert "pagePointerGate.reset()" in shell
    assert "pagePointerGate.moved(pageScroll" in shell
    assert "currentPage().cursorIndex = 0" in shell
    assert "function followKeyboardCursor(delta)" in shell
    assert "pageScroll.contentY + delta * Style.space(56)" in shell
    assert "columns: root.wideLayout ? 2 : 1" in (ROOT / "SettingsView.qml").read_text(
        encoding="utf-8"
    )
    assert "columns: width >= Style.space(420) ? 2 : 1" in (ROOT / "DomainStatusRow.qml").read_text(
        encoding="utf-8"
    )


def test_phase_six_shell_contains_the_accepted_navigation_and_pages() -> None:
    shell = (ROOT / "PanelShell.qml").read_text(encoding="utf-8")
    session = (ROOT / "PanelSession.qml").read_text(encoding="utf-8")

    assert '["Overview", "Wellness", "Activities", "Settings"]' in session
    assert "OverviewShellPage {" in shell
    assert "WellnessShellPage {" in shell
    assert "ActivitiesView {" in shell
    assert "SettingsView {" in shell
    assert "session.beginSession()" in shell
    assert "scrollPositions[session.pageKey]" in shell
    assert "saveScroll()" in shell
    assert "restoreScroll()" in shell
    assert 'if (session.confirmationKind !== "")' in shell
    assert 'if (session.modeIndex === 2 && session.activityViewMode !== "summary")' in shell
    assert 'if (session.modeIndex === 3 && session.settingsViewMode === "account")' in shell


def test_phase_nine_shell_wires_confirmed_sensitive_actions_to_the_service() -> None:
    shell = (ROOT / "PanelShell.qml").read_text(encoding="utf-8")
    service = (ROOT / "Service.qml").read_text(encoding="utf-8")

    assert "service.setWellnessCollection(enabled)" in shell
    assert "service.logout()" in shell
    assert "service.purge()" in shell
    assert "service.openHelp()" in shell
    assert '"wellness", "collection", "--json"' in service
    assert '["auth", "logout", "--json", "--confirm"]' in service
    assert '["auth", "purge", "--json", "--confirm"]' in service
    assert '["/usr/bin/xdg-open", sourceDir + "/README.md"]' in service


def test_phase_six_header_refresh_is_persistent_and_accessible() -> None:
    shell = (ROOT / "PanelShell.qml").read_text(encoding="utf-8")

    assert "trailingControl: Component" in shell
    assert "PanelActionButton {" in shell
    assert "tooltipText: root.actionLabel()" in shell
    assert "Accessible.name: root.actionLabel()" in shell
    assert 'hasCursor: root.cursorActive && root.focusArea === "header"' in shell
    assert "bordered: true" in shell
    assert 'if (text === "r" || text === "R") root.primaryAction()' in shell


def test_phase_six_shell_shows_visible_onboarding_action() -> None:
    shell = (ROOT / "PanelShell.qml").read_text(encoding="utf-8")

    assert "id: primarySetupButton" in shell
    assert '"setup", "unauthenticated", "reconnect", "localError"' in shell
    assert "text: root.actionLabel()" in shell
    assert "onClicked: root.primaryAction()" in shell


def test_panel_headers_omit_unofficial_badge() -> None:
    production_shell = (ROOT / "PanelShell.qml").read_text(encoding="utf-8")
    legacy_panel = (ROOT / "Panel.qml").read_text(encoding="utf-8")

    assert "UNOFFICIAL" not in production_shell
    assert "UNOFFICIAL" not in legacy_panel


def test_phase_six_activities_preserve_contracts_and_drilldown_selection() -> None:
    activities = (ROOT / "ActivitiesView.qml").read_text(encoding="utf-8")

    assert "page.periodKey === periodKey" in activities
    assert 'page.endDate === (currentPeriod ? currentPeriod.endDate : "")' in activities
    assert "page.typeKey === expectedType && page.offset === listOffset" in activities
    assert "service.loadActivityPage(" in activities
    assert "service.loadActivityDetail(selectedActivityId)" in activities
    assert "Model.garminConnectUrl(" in activities
    assert '["Time", "Distance", "Elevation gain", "Energy"]' in activities
    assert (
        "columns: width >= Style.space(520) ? 4 : (width >= Style.space(320) ? 2 : 1)" in activities
    )
    assert "metricKey: root.chartMetricKeys[root.chartMetricIndex]" in activities
    chart = (ROOT / "ActivityTimeChart.qml").read_text(encoding="utf-8")
    assert "normalizedMetricKey" in chart
    assert 'return "Elevation gain"' in chart
    assert "savedListIndex = cursorIndex" in activities
    assert "Math.min(savedListIndex" in activities
    assert "Quickshell.execDetached" not in activities


def test_phase_six_settings_groups_preferences_status_and_sensitive_actions() -> None:
    settings = (ROOT / "SettingsView.qml").read_text(encoding="utf-8")
    shell = (ROOT / "PanelShell.qml").read_text(encoding="utf-8")

    for label in (
        "Wellness collection",
        "Units",
        "Activity refresh",
        "Update checks",
        "Plugin updates",
        "Help and privacy",
        "Account and data",
        "Garmin connection",
        "Retained local data",
    ):
        assert label in settings
    assert "signal confirmationRequested(string kind)" in settings
    assert "signal wellnessCollectionChangeRequested(bool enabled)" in shell
    assert "signal logoutRequested()" in shell
    assert "signal purgeRequested()" in shell
    assert "ConfirmDialog {" in shell
    assert "Stopping wellness collection, logging out, and purging are separate actions" in settings
    assert (
        "readonly property bool sensitiveActionsEnabled: service && !service.demoMode" in settings
    )
    assert settings.count("actionEnabled: root.sensitiveActionsEnabled") == 3
