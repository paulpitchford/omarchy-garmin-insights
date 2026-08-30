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
