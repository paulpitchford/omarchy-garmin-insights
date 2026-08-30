from pathlib import Path


def test_service_routes_private_display_cache_reads_through_backend() -> None:
    service = (Path(__file__).parents[1] / "Service.qml").read_text()

    assert "FileView {" not in service
    assert '"cache", "read", "--json", "--kind", "summary"' in service
    assert '"cache", "read", "--json", "--kind", "activity-trends"' in service
    assert '"cache", "read", "--json", "--kind", "wellness"' in service
    assert "summaryCacheDeadline.restart()" in service
    assert "activityTrendsCacheDeadline.restart()" in service
    assert "wellnessCacheDeadline.restart()" in service
    assert "Model.summaryCacheReadError(" in service
    assert "cachedSummary !== null, cacheError, result.error" in service
    assert "cachedWellness !== null, wellnessCacheError, result.error" in service


def test_sensitive_settings_actions_remain_confirmed_and_service_owned() -> None:
    root = Path(__file__).parents[1]
    shell = (root / "PanelShell.qml").read_text(encoding="utf-8")
    service = (root / "Service.qml").read_text(encoding="utf-8")
    settings = (root / "SettingsView.qml").read_text(encoding="utf-8")

    assert "Quickshell.execDetached" not in shell
    assert "backendCommand" not in shell
    assert "service.logout()" in shell
    assert "service.purge()" in shell
    assert '["auth", "logout", "--json", "--confirm"]' in service
    assert '["auth", "purge", "--json", "--confirm"]' in service
    assert "|| activityViewRunning || displayCacheRunning" in service
    assert "envelope.data.collectionEnabled === actionRequestedCollectionEnabled" in service
    assert "envelope.data.configured === false" in service
    assert 'confirmationRequested("logout")' in settings
    assert 'confirmationRequested("purge")' in settings


def test_activity_and_wellness_refreshes_are_sequential_and_bounded() -> None:
    service = (Path(__file__).parents[1] / "Service.qml").read_text(encoding="utf-8")

    activity_start = service.index('refreshProcess.command = backendCommand(["refresh", "--json"])')
    wellness_start = service.index('var arguments = ["wellness", "refresh", "--json"]')
    handler = service.index("function handleRefresh(exitCode, raw)")
    assert activity_start < wellness_start < handler
    assert "startWellnessRefresh()" in service[handler:]
    assert 'if (wellnessManualRefresh) arguments.push("--manual")' in service
    assert '["scheduled", "authentication", "recovery"].indexOf(' in service
    assert "function refreshWellnessScheduled()" in service
    assert "activityRefreshIncluded = false" in service
    assert "id: wellnessScheduleTimer" in service
    assert "interval: 1805000" in service
    assert "interval: 124000" in service
    assert "interval: 249000" in service
    assert "combinedRefreshDeadline.restart()" in service
    refresh_handler = service[service.index("function handleRefresh(exitCode, raw)") :]
    assert refresh_handler.index("if (demoMode)") < refresh_handler.index("startWellnessRefresh()")
