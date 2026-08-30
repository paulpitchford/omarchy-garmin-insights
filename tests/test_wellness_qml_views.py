from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_phase_seven_keeps_the_completed_shell_dormant() -> None:
    widget = (ROOT / "BarWidget.qml").read_text(encoding="utf-8")
    shell = (ROOT / "PanelShell.qml").read_text(encoding="utf-8")

    assert 'source: Qt.resolvedUrl("Panel.qml")' in widget
    assert "PanelShell.qml" not in widget
    assert "WellnessShellPage {" in shell


def test_overview_has_three_wellness_signals_and_one_activity_strip() -> None:
    overview = (ROOT / "OverviewShellPage.qml").read_text(encoding="utf-8")

    assert overview.count("SignalCard {") == 3
    assert 'title: "BODY BATTERY"' in overview
    assert 'title: "SLEEP"' in overview
    assert 'title: "STEPS"' in overview
    assert "ActivityTimeChart {" in overview
    assert "service.latestActivity" in overview
    assert '? "Latest · " + Qt.formatDate(' in overview


def test_wellness_today_cards_follow_the_accepted_order_and_widths() -> None:
    wellness = (ROOT / "WellnessShellPage.qml").read_text(encoding="utf-8")

    readiness = wellness.index('title: "TRAINING READINESS"')
    battery = wellness.index('title: "BODY BATTERY"')
    sleep = wellness.index('title: "SLEEP"')
    steps = wellness.index('title: "STEPS"')
    hrv = wellness.index('title: "HRV"')
    resting = wellness.index('title: "RESTING HEART RATE"')

    assert readiness < battery < sleep < steps < hrv < resting
    assert "visible: root.sleepDay !== null\n      width: parent.width" in wellness
    assert "columns: root.wideLayout ? 2 : 1" in wellness
    assert "columns: root.wideLayout ? 3 : 1" in wellness


def test_wellness_today_shows_dates_freshness_partial_state_and_retained_failures() -> None:
    wellness = (ROOT / "WellnessShellPage.qml").read_text(encoding="utf-8")

    assert '"Today · " : "Latest retained value · "' in wellness
    assert 'return "Refreshed " + Qt.formatDateTime(' in wellness
    assert '" · Partial at last refresh"' in wellness
    assert 'card.failureLabel + " · showing retained value"' in wellness
    assert 'color: card.source && card.source.failure === "unsupported"' in wellness


def test_missing_wellness_categories_use_one_compact_explanatory_section() -> None:
    wellness = (ROOT / "WellnessShellPage.qml").read_text(encoding="utf-8")
    overview = (ROOT / "OverviewShellPage.qml").read_text(encoding="utf-8")

    assert "root.unavailableCategories.length > 0" in wellness
    assert 'text: "UNAVAILABLE"' in wellness
    assert 'modelData.label + " · " + modelData.reason' in wellness
    assert "root.unavailableSignals.length > 0" in overview
    assert 'modelData.label + " unavailable · " + modelData.reason' in overview


def test_today_visuals_match_each_metric_semantics_without_cross_metric_overlays() -> None:
    wellness = (ROOT / "WellnessShellPage.qml").read_text(encoding="utf-8")

    assert "rangeHigh - card.rangeLow" in wellness
    assert "root.stepsDay.steps.value / root.stepsDay.steps.goal" in wellness
    assert 'label: "Deep"' in wellness
    assert 'label: "Light"' in wellness
    assert 'label: "REM"' in wellness
    assert 'label: "Awake"' in wellness
    assert 'return "Garmin balanced baseline "' in wellness
    assert "stress" not in wellness.lower()


def test_wellness_remote_text_is_plain_and_wraps_in_constrained_cards() -> None:
    wellness = (ROOT / "WellnessShellPage.qml").read_text(encoding="utf-8")

    assert wellness.count("textFormat: Text.PlainText") >= 8
    assert wellness.count("wrapMode: Text.WordWrap") >= 12
    assert "detailText: root.readinessDay && root.readinessDay.trainingReadiness.level" in wellness
    assert "if (hrv.status !== null) values.push(hrv.status)" in wellness


def test_latest_activity_is_loaded_through_the_existing_bounded_local_contract() -> None:
    service = (ROOT / "Service.qml").read_text(encoding="utf-8")
    shell = (ROOT / "PanelShell.qml").read_text(encoding="utf-8")

    assert "function loadLatestActivity()" in service
    assert 'periodKey: "90Days", asOfDate: period.endDate, typeKey: null, offset: 0' in service
    assert '"activities", "list", "--json", "--period", "90Days"' in service
    assert "latestActivity = result.page.activities.length > 0" in service
    assert "service.loadLatestActivity()" in shell
