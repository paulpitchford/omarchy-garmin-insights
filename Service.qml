import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model

Item {
  id: root

  property var manifest: ({})
  property string uvPath: ""
  property bool backendReady: false
  property bool configured: false
  property bool verified: false
  property bool refreshing: false
  property bool demoMode: false
  property int refreshMinutes: 30
  property var cachedSummary: null
  property string failureKind: ""
  property string failureCode: ""
  property string cacheError: ""
  property double nowMs: Date.now()
  property int authPollTicks: 0
  property bool statusTimedOut: false
  property bool refreshTimedOut: false
  property var activityPage: null
  property var activityDetail: null
  property string activityViewError: ""
  property bool activityDetailMissing: false
  property var activityListExpected: null
  property string activityDetailExpectedId: ""
  property bool activityListTimedOut: false
  property bool activityDetailTimedOut: false
  property int refreshGeneration: 0
  property bool cacheRootReady: false
  property bool cacheRootTimedOut: false

  readonly property string sourceDir: manifest && manifest.__sourceDir ? String(manifest.__sourceDir) : ""
  readonly property string homeDir: Quickshell.env("HOME")
  readonly property string cacheRoot: absoluteEnvironmentPath("XDG_CACHE_HOME", homeDir + "/.cache")
  readonly property string applicationCacheRoot: cacheRoot + "/omarchy-garmin-insights"
  readonly property string summaryPath: applicationCacheRoot + "/summary.json"
  readonly property string pythonEnvironmentPath: applicationCacheRoot + "/uv-environment"
  readonly property var summary: demoMode ? Model.syntheticSummary(nowMs) : cachedSummary
  readonly property bool hasSummary: summary !== null
  readonly property double summaryAgeMs: hasSummary ? Math.max(0, nowMs - Number(summary.generatedMs || 0)) : 0
  readonly property bool summaryStale: hasSummary && !demoMode && summaryAgeMs > Math.max(60, refreshMinutes * 2) * 60000
  readonly property string connectionState: Model.connectionState({
    demoMode: demoMode,
    backendReady: backendReady,
    authStatusRunning: authStatusProcess.running,
    refreshRunning: refreshProcess.running,
    hasSummary: hasSummary,
    failureKind: failureKind,
    configured: configured,
    summaryStale: summaryStale,
    cacheError: cacheError,
    refreshing: refreshing
  })
  readonly property string statusText: Model.statusText(connectionState, {
    uvAvailable: uvPath !== "",
    demoMode: demoMode,
    cacheError: cacheError,
    hasSummary: hasSummary
  })
  readonly property bool activityViewRunning: activityListProcess.running || activityDetailProcess.running
  readonly property bool processRunning: uvProbe.running || cacheRootProcess.running
    || authStatusProcess.running || refreshProcess.running || activityViewRunning

  function absoluteEnvironmentPath(name, fallback) {
    var value = String(Quickshell.env(name) || "")
    return value.charAt(0) === "/" ? value.replace(/\/$/, "") : fallback
  }

  function configure(minutes, demo) {
    var parsedMinutes = Math.floor(Number(minutes))
    if (!isFinite(parsedMinutes)) parsedMinutes = 30
    parsedMinutes = Math.max(5, Math.min(360, parsedMinutes))
    var nextDemo = demo === true
    var demoChanged = demoMode !== nextDemo
    refreshMinutes = parsedMinutes
    demoMode = nextDemo
    if (demoChanged && demoMode) {
      authStatusProcess.running = false
      refreshProcess.running = false
      activityListProcess.running = false
      activityDetailProcess.running = false
      refreshing = false
      failureKind = ""
      failureCode = ""
    } else if (!demoMode && uvPath === "" && !uvProbe.running) {
      probeUvCandidate(0)
    } else if (!demoMode && !cacheRootReady) {
      prepareCacheRoot()
    } else if (demoChanged && !demoMode) {
      checkAuthentication()
    }
  }

  function probeUvCandidate(index) {
    var candidates = [
      "/usr/bin/uv",
      homeDir + "/.local/bin/uv",
      homeDir + "/.local/share/mise/shims/uv"
    ]
    if (index >= candidates.length) {
      uvPath = ""
      backendReady = false
      return
    }
    uvProbe.candidateIndex = index
    uvProbe.command = ["/usr/bin/test", "-x", candidates[index]]
    uvProbe.running = true
  }

  function backendCommand(extraArguments) {
    return Model.backendCommand(uvPath, sourceDir, pythonEnvironmentPath, extraArguments)
  }

  function prepareCacheRoot() {
    if (demoMode || sourceDir === "" || cacheRootProcess.running) return
    cacheRootReady = false
    cacheRootTimedOut = false
    cacheRootProcess.command = [
      "/usr/bin/python3",
      sourceDir + "/src/omarchy_garmin/cache_bootstrap.py",
      applicationCacheRoot
    ]
    cacheRootProcess.running = true
    cacheRootDeadline.restart()
  }

  function checkAuthentication() {
    if (demoMode || !cacheRootReady || uvPath === "" || sourceDir === "" || authStatusProcess.running
        || refreshProcess.running || activityViewRunning) return
    statusTimedOut = false
    authStatusProcess.command = backendCommand(["auth", "status", "--json"])
    authStatusProcess.running = true
    statusDeadline.restart()
  }

  function refresh() {
    if (demoMode) {
      nowMs = Date.now()
      return
    }
    if (!backendReady || !configured || authStatusProcess.running || refreshProcess.running
        || activityViewRunning) return
    failureKind = ""
    failureCode = ""
    refreshing = true
    refreshTimedOut = false
    refreshProcess.command = backendCommand(["refresh", "--json"])
    refreshProcess.running = true
    refreshDeadline.restart()
  }

  function periodAllowsType(period, typeKey) {
    if (typeKey === null) return true
    if (!period || !Array.isArray(period.byType)) return false
    for (var i = 0; i < period.byType.length; i++)
      if (period.byType[i].typeKey === typeKey) return true
    return false
  }

  function loadActivityPage(periodKey, asOfDate, typeKey, offset) {
    var normalizedType = typeKey === undefined || typeKey === "" ? null : String(typeKey)
    var normalizedOffset = Math.floor(Number(offset))
    var period = Model.periodByKey(summary, String(periodKey))
    if (!period || period.endDate !== String(asOfDate) || !periodAllowsType(period, normalizedType)
        || !isFinite(normalizedOffset) || normalizedOffset < 0 || normalizedOffset > 19980
        || normalizedOffset % 20 !== 0) {
      activityViewError = "invalid_request"
      return
    }
    activityViewError = ""
    activityDetail = null
    activityDetailMissing = false
    if (demoMode) {
      activityPage = Model.syntheticActivityPage(
        String(periodKey), String(asOfDate), normalizedType, normalizedOffset)
      if (!activityPage) activityViewError = "invalid_response"
      return
    }
    if (!backendReady || activityViewRunning || authStatusProcess.running || refreshProcess.running) {
      activityViewError = "backend_unavailable"
      return
    }
    activityListExpected = {
      periodKey: String(periodKey),
      asOfDate: String(asOfDate),
      typeKey: normalizedType,
      offset: normalizedOffset
    }
    activityPage = null
    activityListTimedOut = false
    var extraArguments = [
      "activities", "list", "--json", "--period", String(periodKey),
      "--as-of", String(asOfDate), "--offset", String(normalizedOffset)
    ]
    if (normalizedType !== null) extraArguments.push("--type-key", normalizedType)
    activityListProcess.command = backendCommand(extraArguments)
    activityListProcess.running = true
    activityListDeadline.restart()
  }

  function loadActivityDetail(activityId) {
    var validatedId = String(activityId || "")
    if (Model.garminConnectUrl(validatedId) === "") {
      activityViewError = "invalid_request"
      return
    }
    activityViewError = ""
    activityDetailMissing = false
    activityDetailExpectedId = validatedId
    activityDetail = null
    if (demoMode) {
      activityDetail = Model.syntheticActivityDetail(validatedId, summary.asOfLocalDate)
      activityDetailMissing = activityDetail === null
      return
    }
    if (!backendReady || activityViewRunning || authStatusProcess.running || refreshProcess.running) {
      activityViewError = "backend_unavailable"
      return
    }
    activityDetailTimedOut = false
    activityDetailProcess.command = backendCommand([
      "activities", "detail", "--json", "--activity-id", validatedId
    ])
    activityDetailProcess.running = true
    activityDetailDeadline.restart()
  }

  function clearActivityViews() {
    if (activityViewRunning) return
    activityPage = null
    activityDetail = null
    activityDetailMissing = false
    activityViewError = ""
  }

  function parseEnvelope(raw, expectedCommand) {
    var text = String(raw || "")
    if (text.length === 0 || text.length > 16384) return null
    try {
      var value = JSON.parse(text)
      if (!value || value.schemaVersion !== 1 || value.command !== expectedCommand || typeof value.ok !== "boolean")
        return null
      return value
    } catch (error) {
      return null
    }
  }

  function safeFailure(code) {
    failureCode = String(code || "internal_error")
    failureKind = Model.failureKindForCode(failureCode)
  }

  function handleStatus(exitCode, raw) {
    var envelope = parseEnvelope(raw, "auth.status")
    if (statusTimedOut || !envelope) {
      backendReady = false
      return
    }
    backendReady = true
    if (exitCode !== 0 || !envelope.ok || !envelope.data || typeof envelope.data.configured !== "boolean") {
      safeFailure(envelope && envelope.error ? envelope.error.code : "internal_error")
      return
    }

    backendReady = true
    configured = envelope.data.configured
    verified = envelope.data.verified === true
    failureKind = ""
    failureCode = ""
    if (configured) {
      authPollTimer.stop()
      authPollTicks = 0
      refresh()
    }
  }

  function handleRefresh(exitCode, raw) {
    refreshing = false
    var envelope = parseEnvelope(raw, "refresh")
    if (refreshTimedOut) {
      failureKind = "offline"
      failureCode = "request_timeout"
      return
    }
    if (!envelope) {
      backendReady = false
      failureKind = "local"
      failureCode = "backend_unavailable"
      return
    }
    if (exitCode !== 0 || envelope.ok !== true) {
      safeFailure(envelope.error ? envelope.error.code : "internal_error")
      return
    }
    backendReady = true
    configured = true
    verified = true
    failureKind = ""
    failureCode = ""
    refreshGeneration++
    summaryFile.reload()
  }

  function handleActivityList(exitCode, raw) {
    var result = Model.parseActivityPageEnvelope(raw, activityListExpected)
    if (activityListTimedOut) {
      activityViewError = "timeout"
      return
    }
    if (exitCode !== 0 || !result.ok) {
      activityViewError = result.envelope && result.envelope.error
        ? String(result.envelope.error.code || "local_storage_error") : "invalid_response"
      return
    }
    activityPage = result.page
    activityViewError = ""
  }

  function handleActivityDetail(exitCode, raw) {
    var result = Model.parseActivityDetailEnvelope(raw, activityDetailExpectedId)
    if (activityDetailTimedOut) {
      activityViewError = "timeout"
      return
    }
    if (exitCode !== 0 || !result.ok) {
      activityViewError = result.envelope && result.envelope.error
        ? String(result.envelope.error.code || "local_storage_error") : "invalid_response"
      return
    }
    activityDetail = result.activity
    activityDetailMissing = !result.found
    activityViewError = ""
  }

  function launchSetup() {
    if (uvPath === "" || sourceDir === "" || !cacheRootReady) {
      prepareCacheRoot()
      return
    }
    Quickshell.execDetached([
      "/usr/share/omarchy/bin/omarchy-launch-terminal",
      "/usr/bin/env", "UV_PROJECT_ENVIRONMENT=" + pythonEnvironmentPath,
      uvPath,
      "--directory", sourceDir,
      "sync", "--locked", "--no-dev"
    ])
    authPollTicks = 0
    authPollTimer.start()
  }

  function launchLogin() {
    if (uvPath === "" || sourceDir === "" || !cacheRootReady) {
      prepareCacheRoot()
      return
    }
    Quickshell.execDetached([
      "/usr/share/omarchy/bin/omarchy-launch-terminal",
      "/usr/bin/env", "UV_PROJECT_ENVIRONMENT=" + pythonEnvironmentPath,
      uvPath,
      "--directory", sourceDir,
      "run", "--locked", "--no-sync",
      "omarchy-garmin-insights", "auth", "login"
    ])
    authPollTicks = 0
    authPollTimer.start()
  }

  FileView {
    id: summaryFile
    path: root.summaryPath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      var result = Model.parseSummary(text())
      if (result.ok) {
        root.cachedSummary = result.summary
        root.cacheError = ""
      } else {
        root.cacheError = result.error
      }
      root.nowMs = Date.now()
    }
    onLoadFailed: {
      if (root.cachedSummary === null) root.cacheError = "missing"
    }
  }

  Process {
    id: uvProbe
    property int candidateIndex: 0
    command: []
    onExited: function(exitCode) {
      var candidates = [
        "/usr/bin/uv",
        root.homeDir + "/.local/bin/uv",
        root.homeDir + "/.local/share/mise/shims/uv"
      ]
      if (exitCode === 0) {
        root.uvPath = candidates[candidateIndex]
        root.prepareCacheRoot()
      } else {
        root.probeUvCandidate(candidateIndex + 1)
      }
    }
  }

  Process {
    id: cacheRootProcess
    command: []
    onExited: function(exitCode) {
      cacheRootDeadline.stop()
      if (!root.cacheRootTimedOut && exitCode === 0) {
        root.cacheRootReady = true
        root.failureKind = ""
        root.failureCode = ""
        root.checkAuthentication()
      } else {
        root.cacheRootReady = false
        root.backendReady = false
        root.failureKind = "local"
        root.failureCode = "local_storage_error"
      }
    }
  }

  Process {
    id: authStatusProcess
    command: []
    stdout: StdioCollector { id: authStdout; waitForEnd: true }
    onExited: function(exitCode) {
      statusDeadline.stop()
      root.handleStatus(exitCode, authStdout.text)
    }
  }

  Process {
    id: refreshProcess
    command: []
    stdout: StdioCollector { id: refreshStdout; waitForEnd: true }
    onExited: function(exitCode) {
      refreshDeadline.stop()
      root.handleRefresh(exitCode, refreshStdout.text)
    }
  }

  Process {
    id: activityListProcess
    command: []
    stdout: StdioCollector { id: activityListStdout; waitForEnd: true }
    onExited: function(exitCode) {
      activityListDeadline.stop()
      root.handleActivityList(exitCode, activityListStdout.text)
    }
  }

  Process {
    id: activityDetailProcess
    command: []
    stdout: StdioCollector { id: activityDetailStdout; waitForEnd: true }
    onExited: function(exitCode) {
      activityDetailDeadline.stop()
      root.handleActivityDetail(exitCode, activityDetailStdout.text)
    }
  }

  Timer {
    id: cacheRootDeadline
    interval: 5000
    onTriggered: {
      root.cacheRootTimedOut = true
      cacheRootProcess.running = false
    }
  }

  Timer {
    id: statusDeadline
    interval: 15000
    onTriggered: {
      root.statusTimedOut = true
      authStatusProcess.running = false
    }
  }

  Timer {
    id: refreshDeadline
    interval: 125000
    onTriggered: {
      root.refreshTimedOut = true
      refreshProcess.running = false
    }
  }

  Timer {
    id: activityListDeadline
    interval: 5000
    onTriggered: {
      root.activityListTimedOut = true
      activityListProcess.running = false
    }
  }

  Timer {
    id: activityDetailDeadline
    interval: 5000
    onTriggered: {
      root.activityDetailTimedOut = true
      activityDetailProcess.running = false
    }
  }

  Timer {
    id: refreshTimer
    interval: root.refreshMinutes * 60000
    repeat: true
    running: !root.demoMode
    onTriggered: root.refresh()
  }

  Timer {
    interval: 60000
    repeat: true
    running: true
    onTriggered: root.nowMs = Date.now()
  }

  Timer {
    id: authPollTimer
    interval: 3000
    repeat: true
    onTriggered: {
      root.authPollTicks++
      if (root.authPollTicks >= 100) stop()
      else root.checkAuthentication()
    }
  }
}
