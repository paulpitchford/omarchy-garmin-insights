from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_phase_eight_keeps_the_completed_shell_dormant() -> None:
    widget = (ROOT / "BarWidget.qml").read_text(encoding="utf-8")
    shell = (ROOT / "PanelShell.qml").read_text(encoding="utf-8")

    assert 'source: Qt.resolvedUrl("Panel.qml")' in widget
    assert "PanelShell.qml" not in widget
    assert "WellnessShellPage {" in shell


def test_wellness_trends_show_one_of_six_metric_families() -> None:
    wellness = (ROOT / "WellnessShellPage.qml").read_text(encoding="utf-8")

    assert (
        '"trainingReadiness", "bodyBattery", "sleep", "steps", "hrv", "restingHeartRate"'
        in wellness
    )
    assert "model: root.trendFamilyLabels" in wellness
    assert wellness.count("WellnessTrendChart {") == 1
    assert "familyKey: root.trendFamilyKey" in wellness


def test_wellness_trends_offer_only_seven_and_thirty_day_ranges() -> None:
    wellness = (ROOT / "WellnessShellPage.qml").read_text(encoding="utf-8")

    assert 'model: ["7 days", "30 days"]' in wellness
    assert "readonly property int trendPeriodDays: trendPeriodIndex === 0 ? 7 : 30" in wellness
    assert "periodDays: root.trendPeriodDays" in wellness
    assert "90 days" not in wellness[wellness.index("id: trendsColumn") :]


def test_sleep_trends_have_clear_score_duration_and_stage_choices() -> None:
    wellness = (ROOT / "WellnessShellPage.qml").read_text(encoding="utf-8")
    chart = (ROOT / "WellnessTrendChart.qml").read_text(encoding="utf-8")

    assert 'model: ["Score", "Duration", "Stages"]' in wellness
    assert 'visible: root.trendFamilyKey === "sleep"' in wellness
    assert "modelData.sleep.deepSeconds" in chart
    assert "modelData.sleep.lightSeconds" in chart
    assert "modelData.sleep.remSeconds" in chart
    assert "modelData.sleep.awakeSeconds" in chart
    assert 'return "Deep, Light, REM, and Awake shown as one daily composition"' in chart


def test_wellness_chart_treatments_match_each_metric_semantics() -> None:
    chart = (ROOT / "WellnessTrendChart.qml").read_text(encoding="utf-8")

    assert 'familyKey === "bodyBattery" ? "range"' in chart
    assert 'familyKey === "sleep" && sleepMetric === "stages" ? "stages"' in chart
    assert 'familyKey === "steps"' in chart
    assert 'visible: root.familyKey === "steps" && modelData.steps' in chart
    assert 'visible: root.familyKey === "hrv" && modelData.hrv' in chart
    assert "balancedLowMs" in chart
    assert "balancedUpperMs" in chart
    assert "lineSegment.y2 - lineSegment.y1" in chart


def test_wellness_trends_explain_gaps_contributors_dates_and_partial_today() -> None:
    wellness = (ROOT / "WellnessShellPage.qml").read_text(encoding="utf-8")
    chart = (ROOT / "WellnessTrendChart.qml").read_text(encoding="utf-8")
    model = (ROOT / "Model.js").read_text(encoding="utf-8")

    assert "Model.wellnessTrendContributorCount(" in chart
    assert (
        'return contributorCount + (contributorCount === 1 ? " day" : " days") + subject' in chart
    )
    assert '" values are recorded for this range. Gaps are not zero."' in chart
    assert (
        'root.rangeDate(root.period.startDate) + "\u2013" + root.rangeDate(root.period.endDate)'
        in chart
    )
    assert '" · Today partial at last refresh"' in chart
    assert 'values.push("Partial at last refresh")' in chart
    assert (
        'trendChart.hasValues ? " · showing retained history" : " · no retained history"'
        in wellness
    )
    assert "function wellnessTrendDays(wellness, periodDays)" in model


def test_exact_wellness_values_are_available_to_pointer_and_panel_keyboard() -> None:
    wellness = (ROOT / "WellnessShellPage.qml").read_text(encoding="utf-8")
    chart = (ROOT / "WellnessTrendChart.qml").read_text(encoding="utf-8")

    assert "function moveTrendPoint(delta)" in wellness
    assert "moveTrendPoint(dx)" in wellness
    assert "selectedIndex: root.trendPointIndex" in wellness
    assert "PanelToolTip {" in chart
    assert "text: root.pointTooltip(pointCursor.modelData)" in chart
    assert "text: pointToolTip.text\n              textFormat: Text.PlainText" in chart
    assert "Accessible.name: root.pointTooltip(modelData)" in chart
    assert "text: root.selectedDetailText" in chart
    assert "bordered: index === root.boundedSelectedIndex" in chart


def test_goals_and_baselines_are_shown_only_for_matching_supplied_context() -> None:
    chart = (ROOT / "WellnessTrendChart.qml").read_text(encoding="utf-8")

    assert 'visible: root.familyKey === "steps" && modelData.steps' in chart
    assert "&& modelData.steps.goal !== null" in chart
    assert 'visible: root.familyKey === "hrv" && modelData.hrv' in chart
    assert "&& modelData.hrv.balancedLowMs !== null" in chart
    assert "&& modelData.hrv.balancedUpperMs !== null" in chart
    assert '"Garmin daily goals unavailable"' in chart
    assert '"Garmin balanced baselines unavailable"' in chart


def test_wellness_trends_use_theme_and_style_units_at_constrained_widths() -> None:
    wellness = (ROOT / "WellnessShellPage.qml").read_text(encoding="utf-8")
    chart = (ROOT / "WellnessTrendChart.qml").read_text(encoding="utf-8")

    assert "columns: root.wideLayout ? 3 : 1" in wellness
    assert "width: parent.width" in chart
    assert chart.count("Style.space(") >= 20
    assert "root.foreground" in chart
    assert "Color.accent" in chart
    assert "Color.urgent" not in chart


def test_wellness_trends_do_not_add_correlation_advice_or_unapproved_metrics() -> None:
    chart = (ROOT / "WellnessTrendChart.qml").read_text(encoding="utf-8").lower()

    assert "correlation" not in chart
    assert "advice" not in chart
    assert "recovery score" not in chart
    assert "stress" not in chart
    assert "latitude" not in chart
    assert "longitude" not in chart


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


def test_overview_failure_styling_guards_missing_source_state() -> None:
    overview = (ROOT / "OverviewShellPage.qml").read_text(encoding="utf-8")

    assert "function signalFailureIsProblem(category, day)" in overview
    assert (
        'source !== null && source.failure !== null && source.failure !== "unsupported"' in overview
    )
    assert 'signalSource("bodyBattery", root.batteryDay).failure' not in overview
    assert 'signalSource("sleep", root.sleepDay).failure' not in overview
    assert 'signalSource("steps", root.stepsDay).failure' not in overview


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
    assert "result.page.endDate === currentPeriod.endDate" in service
    assert "service.loadLatestActivity()" in shell


def test_latest_activity_is_hidden_during_load_and_after_background_failure() -> None:
    service = (ROOT / "Service.qml").read_text(encoding="utf-8")
    loader = service[service.index("function loadLatestActivity()") :]

    assert loader.index("latestActivity = null") < loader.index('activityListPurpose = "overview"')
    assert 'else if (purpose === "overview") latestActivity = null' in service
