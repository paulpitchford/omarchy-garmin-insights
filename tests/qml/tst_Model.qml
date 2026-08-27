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

  function syntheticPageEnvelope() {
    var page = Model.syntheticActivityPage("7Days", "2026-08-26", null, 0)
    return {
      schemaVersion: 1,
      command: "activities.list",
      ok: true,
      data: page,
      error: null
    }
  }

  function syntheticDetailEnvelope(activity) {
    return {
      schemaVersion: 1,
      command: "activities.detail",
      ok: true,
      data: { found: true, activity: activity },
      error: null
    }
  }

  function test_activity_page_parser_accepts_bounded_newest_first_contract() {
    var expected = { periodKey: "7Days", asOfDate: "2026-08-26", typeKey: null, offset: 0 }
    var result = Model.parseActivityPageEnvelope(JSON.stringify(syntheticPageEnvelope()), expected)

    verify(result.ok)
    compare(result.page.activities.length, 4)
    compare(result.page.activities[0].typeKey, "strength_training")
    compare(result.page.hasMore, false)
  }

  function test_activity_page_parser_rejects_unknown_fields_and_wrong_request() {
    var envelope = syntheticPageEnvelope()
    envelope.data.activities[0].completeUrl = "https://hostile.example/activity/1"
    var expected = { periodKey: "7Days", asOfDate: "2026-08-26", typeKey: null, offset: 0 }
    verify(!Model.parseActivityPageEnvelope(JSON.stringify(envelope), expected).ok)

    envelope = syntheticPageEnvelope()
    expected.offset = 20
    verify(!Model.parseActivityPageEnvelope(JSON.stringify(envelope), expected).ok)
  }

  function test_activity_page_parser_rejects_oversized_input() {
    var expected = { periodKey: "7Days", asOfDate: "2026-08-26", typeKey: null, offset: 0 }
    verify(!Model.parseActivityPageEnvelope("x".repeat(65537), expected).ok)
  }

  function test_activity_page_parser_enforces_period_and_type_filter() {
    var envelope = syntheticPageEnvelope()
    envelope.data.typeKey = "running"
    var expected = { periodKey: "7Days", asOfDate: "2026-08-26", typeKey: "running", offset: 0 }
    verify(!Model.parseActivityPageEnvelope(JSON.stringify(envelope), expected).ok)

    envelope = syntheticPageEnvelope()
    envelope.data.activities[0].localDate = "2026-08-01"
    envelope.data.activities[0].startedAtLocal = "2026-08-01 18:15:00"
    expected.typeKey = null
    verify(!Model.parseActivityPageEnvelope(JSON.stringify(envelope), expected).ok)
  }

  function test_activity_page_parser_rejects_malformed_identifier_and_order() {
    var envelope = syntheticPageEnvelope()
    envelope.data.activities[0].activityId = "1;open-browser"
    var expected = { periodKey: "7Days", asOfDate: "2026-08-26", typeKey: null, offset: 0 }
    verify(!Model.parseActivityPageEnvelope(JSON.stringify(envelope), expected).ok)

    envelope = syntheticPageEnvelope()
    var first = envelope.data.activities[0]
    envelope.data.activities[0] = envelope.data.activities[1]
    envelope.data.activities[1] = first
    verify(!Model.parseActivityPageEnvelope(JSON.stringify(envelope), expected).ok)
  }

  function test_activity_detail_parser_preserves_hostile_name_as_display_text() {
    var activity = Model.syntheticActivityDetail("900000000001", "2026-08-26")
    activity.name = "<b>Fabricated & plain</b>"
    var result = Model.parseActivityDetailEnvelope(
      JSON.stringify(syntheticDetailEnvelope(activity)), activity.activityId)

    verify(result.ok)
    compare(result.activity.name, "<b>Fabricated & plain</b>")
    compare(result.activity.movingDurationSeconds, 2070)
  }

  function test_activity_detail_parser_accepts_not_found_and_rejects_wrong_id() {
    var missing = {
      schemaVersion: 1,
      command: "activities.detail",
      ok: true,
      data: { found: false, activity: null },
      error: null
    }
    var result = Model.parseActivityDetailEnvelope(JSON.stringify(missing), "101")
    verify(result.ok)
    verify(!result.found)

    var activity = Model.syntheticActivityDetail("900000000001", "2026-08-26")
    verify(!Model.parseActivityDetailEnvelope(
      JSON.stringify(syntheticDetailEnvelope(activity)), "900000000002").ok)
  }

  function test_activity_type_filter_keeps_all_activities_as_null() {
    compare(Model.normalizeActivityTypeFilter(undefined), null)
    compare(Model.normalizeActivityTypeFilter(null), null)
    compare(Model.normalizeActivityTypeFilter(""), null)
    compare(Model.normalizeActivityTypeFilter("running"), "running")
  }

  function test_garmin_connect_url_uses_only_fixed_origin_and_decimal_id() {
    compare(Model.garminConnectUrl("900000000001"),
      "https://connect.garmin.com/app/activity/900000000001")
    compare(Model.garminConnectUrl("1/../../hostile.example"), "")
    compare(Model.garminConnectUrl("9223372036854775808"), "")
  }

  function test_update_commit_parsers_accept_only_fixed_bounded_forms() {
    var local = "1".repeat(40)
    var remote = "2".repeat(40)
    compare(Model.parseLocalCommit(local + "\n"), local)
    compare(Model.parseRemoteCommit(remote + "\trefs/heads/main\n"), remote)
    compare(Model.parseLocalCommit("A".repeat(40)), "")
    compare(Model.parseRemoteCommit(remote + "\trefs/heads/other"), "")
    compare(Model.parseRemoteCommit("x".repeat(97)), "")
    compare(Model.parseRemoteCommit(remote + "\trefs/heads/main\nhostile"), "")
  }

  function test_update_claim_parser_restores_only_matching_valid_commits() {
    var local = "1".repeat(40)
    var remote = "2".repeat(40)
    var claim = {
      due: false,
      localCommit: local,
      remoteCommit: remote,
      schemaVersion: 1
    }
    var result = Model.parseUpdateClaim(JSON.stringify(claim), local)
    verify(result !== null)
    compare(result.remoteCommit, remote)
    verify(Model.commitsDiffer(local, result.remoteCommit))

    claim.localCommit = "3".repeat(40)
    compare(Model.parseUpdateClaim(JSON.stringify(claim), local), null)
    claim.localCommit = local
    claim.remoteCommit = "https://hostile.example"
    compare(Model.parseUpdateClaim(JSON.stringify(claim), local), null)
    claim.remoteCommit = remote
    claim.command = "/bin/sh"
    compare(Model.parseUpdateClaim(JSON.stringify(claim), local), null)
  }

  function test_update_claim_parser_rejects_empty_malformed_and_oversized_output() {
    var local = "1".repeat(40)
    compare(Model.parseUpdateClaim("", local), null)
    compare(Model.parseUpdateClaim("not-json", local), null)
    compare(Model.parseUpdateClaim("x".repeat(513), local), null)
  }

  function test_equal_update_commits_do_not_show_availability() {
    var commit = "1".repeat(40)
    verify(!Model.commitsDiffer(commit, commit))
    verify(!Model.commitsDiffer(commit, ""))
  }

  function test_update_version_and_review_command_are_fixed() {
    compare(Model.safeVersion("0.1.0"), "0.1.0")
    compare(Model.safeVersion("<b>hostile</b>"), "Unknown")
    compare(Model.updateReviewCommand(), [
      "/usr/share/omarchy/bin/omarchy-launch-terminal",
      "/usr/bin/omarchy",
      "plugin",
      "update",
      "io.github.paulpitchford.garmin-insights"
    ])
  }

  function test_synthetic_activity_counts_match_summary_periods() {
    compare(Model.syntheticActivityPage("today", "2026-08-26", null, 0).activities.length, 1)
    compare(Model.syntheticActivityPage("7Days", "2026-08-26", null, 0).activities.length, 4)
    compare(Model.syntheticActivityPage("30Days", "2026-08-26", null, 0).activities.length, 13)
    var quarter = Model.syntheticActivityPage("90Days", "2026-08-26", null, 0)
    compare(quarter.activities.length, 20)
    verify(quarter.hasMore)
    compare(quarter.nextOffset, 20)
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

  function test_suspend_gap_detection_ignores_normal_ticks_and_clock_reversal() {
    verify(!Model.suspendGapDetected(100000, 100000 + Model.RECOVERY_HEARTBEAT_INTERVAL_MS))
    verify(!Model.suspendGapDetected(100000, 99999))
    verify(!Model.suspendGapDetected(0, 100000))
    verify(Model.suspendGapDetected(100000, 100000 + Model.RECOVERY_SUSPEND_GAP_MS))
  }

  function test_suspended_countdown_is_distinguished_from_normal_timer_jitter() {
    verify(!Model.timerOverrunDetected(100000, 130000, 30000))
    verify(!Model.timerOverrunDetected(100000, 134999, 30000))
    verify(Model.timerOverrunDetected(100000, 135000, 30000))
    verify(!Model.timerOverrunDetected(100000, 200000, 0))
  }

  function test_offline_recovery_stops_after_connectivity_is_restored() {
    var retry = Model.recoveryTransition(0, "offline")
    verify(retry.active)
    compare(retry.retryCount, 1)
    compare(retry.delayMs, 30000)

    var recovered = Model.recoveryTransition(retry.retryCount, "success")
    verify(!recovered.active)
    compare(recovered.retryCount, 0)
    compare(recovered.delayMs, -1)
  }

  function test_offline_recovery_has_a_bounded_retry_budget() {
    var first = Model.recoveryTransition(0, "offline")
    var second = Model.recoveryTransition(first.retryCount, "offline")
    var exhausted = Model.recoveryTransition(second.retryCount, "offline")

    compare(first.delayMs, 30000)
    compare(second.delayMs, 120000)
    verify(!exhausted.active)
    compare(exhausted.delayMs, -1)
  }

  function test_non_connectivity_failures_do_not_enter_recovery() {
    compare(Model.recoveryTransition(0, "rateLimited").delayMs, -1)
    compare(Model.recoveryTransition(0, "reconnect").delayMs, -1)
    compare(Model.recoveryTransition(0, "local").delayMs, -1)
    compare(Model.recoveryTransition(0, "").delayMs, -1)
  }

  function test_manual_refresh_uses_the_pending_recovery_attempt() {
    compare(Model.refreshOrigin(undefined, false), "manual")
    compare(Model.refreshOrigin(undefined, true), "recovery")
    compare(Model.refreshOrigin("manual", true), "recovery")
    compare(Model.refreshOrigin("scheduled", true), "scheduled")
    compare(Model.refreshOrigin("recovery", false), "recovery")
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
      "omarchy-garmin-insights",
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
