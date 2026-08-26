import QtQuick
import QtTest
import "../../Model.js" as Model

TestCase {
  name: "GarminSummaryModel"

  function test_synthetic_summary_satisfies_parser() {
    var synthetic = Model.syntheticSummary(Date.parse("2026-08-26T12:00:00Z"))
    var result = Model.parseSummary(JSON.stringify(synthetic))

    verify(result.ok)
    compare(result.summary.periods.length, 4)
    compare(result.summary.periods[1].startDate, "2026-08-20")
    compare(result.summary.periods[3].startDate, "2026-05-29")
    compare(result.summary.periods[1].overall.activityCount, 4)
    compare(result.summary.periods[1].byType[2].typeKey, "strength_training")
  }

  function test_parser_rejects_unexpected_schema() {
    var synthetic = Model.syntheticSummary(Date.parse("2026-08-26T12:00:00Z"))
    synthetic.schemaVersion = 99

    var result = Model.parseSummary(JSON.stringify(synthetic))

    verify(!result.ok)
    compare(result.error, "invalid_schema")
  }

  function test_parser_rejects_non_contract_dates() {
    var synthetic = Model.syntheticSummary(Date.parse("2026-08-26T12:00:00Z"))
    synthetic.asOfLocalDate = "2026-99-99"
    verify(!Model.parseSummary(JSON.stringify(synthetic)).ok)

    synthetic = Model.syntheticSummary(Date.parse("2026-08-26T12:00:00Z"))
    synthetic.generatedAt = "August 26, 2026"
    verify(!Model.parseSummary(JSON.stringify(synthetic)).ok)
  }

  function test_parser_rejects_invalid_metric() {
    var synthetic = Model.syntheticSummary(Date.parse("2026-08-26T12:00:00Z"))
    synthetic.periods[0].overall.distanceMetres = {
      value: 100,
      contributingActivityCount: 0
    }

    var result = Model.parseSummary(JSON.stringify(synthetic))

    verify(!result.ok)
    compare(result.error, "invalid_period")
  }

  function test_parser_rejects_type_count_mismatch() {
    var synthetic = Model.syntheticSummary(Date.parse("2026-08-26T12:00:00Z"))
    synthetic.periods[1].overall.activityCount = 5

    var result = Model.parseSummary(JSON.stringify(synthetic))

    verify(!result.ok)
    compare(result.error, "invalid_period")
  }

  function test_parser_rejects_oversized_input_before_json_parsing() {
    var result = Model.parseSummary("x".repeat(1048577))

    verify(!result.ok)
    compare(result.error, "too_large")
  }

  function test_type_labels_remain_display_text() {
    compare(Model.typeLabel("<b>synthetic_type</b>"), "<b>synthetic type</b>")
  }

  function stateOptions(overrides) {
    var options = {
      demoMode: false,
      backendReady: true,
      authStatusRunning: false,
      refreshRunning: false,
      hasSummary: true,
      failureKind: "",
      configured: true,
      summaryStale: false,
      cacheError: "",
      refreshing: false
    }
    for (var key in overrides) options[key] = overrides[key]
    return options
  }

  function test_connection_states_cover_expected_failures() {
    compare(Model.connectionState(stateOptions({ demoMode: true, backendReady: false })), "connected")
    compare(Model.connectionState(stateOptions({ backendReady: false })), "setup")
    compare(Model.connectionState(stateOptions({ backendReady: false, authStatusRunning: true, hasSummary: false })), "loading")
    compare(Model.connectionState(stateOptions({ authStatusRunning: true, hasSummary: false })), "loading")
    compare(Model.connectionState(stateOptions({ configured: false })), "unauthenticated")
    compare(Model.connectionState(stateOptions({ failureKind: "rateLimited" })), "rateLimited")
    compare(Model.connectionState(stateOptions({ failureKind: "offline" })), "offline")
    compare(Model.connectionState(stateOptions({ failureKind: "reconnect" })), "reconnect")
    compare(Model.connectionState(stateOptions({ failureKind: "local", hasSummary: false })), "localError")
    compare(Model.connectionState(stateOptions({ failureKind: "local" })), "stale")
    compare(Model.connectionState(stateOptions({ summaryStale: true })), "stale")
    compare(Model.connectionState(stateOptions({ cacheError: "invalid_json" })), "stale")
    compare(Model.connectionState(stateOptions({})), "connected")
  }

  function test_stable_error_codes_map_to_display_states() {
    compare(Model.failureKindForCode("rate_limited"), "rateLimited")
    compare(Model.failureKindForCode("network_unavailable"), "offline")
    compare(Model.failureKindForCode("remote_service_error"), "offline")
    compare(Model.failureKindForCode("auth_required"), "reconnect")
    compare(Model.failureKindForCode("authentication_failed"), "reconnect")
    compare(Model.failureKindForCode("account_mismatch"), "reconnect")
    compare(Model.failureKindForCode("refresh_in_progress"), "")
    compare(Model.failureKindForCode("local_storage_error"), "local")
  }

  function test_status_text_never_reflects_backend_error_content() {
    compare(Model.statusText("offline", { hasSummary: true }), "Offline · showing cached data")
    compare(Model.statusText("reconnect", {}), "Reconnect Garmin")
    compare(Model.statusText("localError", {}), "Garmin backend reported an error")
  }

  function test_backend_command_keeps_each_argument_separate() {
    compare(Model.backendCommand(
      "/usr/bin/uv",
      "/synthetic/plugin",
      "/synthetic/cache/environment",
      ["auth", "status", "--json"]
    ), [
      "/usr/bin/env",
      "UV_PROJECT_ENVIRONMENT=/synthetic/cache/environment",
      "/usr/bin/uv",
      "--directory",
      "/synthetic/plugin",
      "run",
      "--locked",
      "--no-sync",
      "omarchy-garmin-activities",
      "auth",
      "status",
      "--json"
    ])
  }

  function test_formatters_preserve_missing_values() {
    compare(Model.formatDistance(null, false), "—")
    compare(Model.formatDuration(null), "—")
    compare(Model.formatEnergy(null, false), "—")
  }

  function test_formatters_convert_at_presentation_boundary() {
    compare(Model.formatDistance(5000, false), "5.0 km")
    compare(Model.formatDistance(16093.44, true), "10 mi")
    compare(Model.formatDuration(4380), "1h 13m")
    compare(Model.formatEnergy(4184000, true), "1000 kcal")
  }
}
