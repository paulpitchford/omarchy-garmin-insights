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


def test_dormant_shell_does_not_execute_sensitive_settings_actions() -> None:
    root = Path(__file__).parents[1]
    shell = (root / "PanelShell.qml").read_text(encoding="utf-8")
    settings = (root / "SettingsView.qml").read_text(encoding="utf-8")

    assert "Quickshell.execDetached" not in shell
    assert "backendCommand" not in shell
    assert '"auth", "logout"' not in shell
    assert '"auth", "purge"' not in shell
    assert "logoutRequested()" in shell
    assert "purgeRequested()" in shell
    assert 'confirmationRequested("logout")' in settings
    assert 'confirmationRequested("purge")' in settings
