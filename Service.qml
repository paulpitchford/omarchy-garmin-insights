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

  readonly property string sourceDir: manifest && manifest.__sourceDir ? String(manifest.__sourceDir) : ""
  readonly property string homeDir: Quickshell.env("HOME")
  readonly property string cacheRoot: absoluteEnvironmentPath("XDG_CACHE_HOME", homeDir + "/.cache")
  readonly property string summaryPath: cacheRoot + "/omarchy-garmin-activities/summary.json"
  readonly property string pythonEnvironmentPath: cacheRoot + "/omarchy-garmin-activities/uv-environment"
  readonly property var summary: demoMode ? Model.syntheticSummary(nowMs) : cachedSummary
  readonly property bool hasSummary: summary !== null
  readonly property double summaryAgeMs: hasSummary ? Math.max(0, nowMs - Number(summary.generatedMs || 0)) : 0
  readonly property bool summaryStale: hasSummary && !demoMode && summaryAgeMs > Math.max(60, refreshMinutes * 2) * 60000
  readonly property string connectionState: computeState()
  readonly property string statusText: stateText(connectionState)
  readonly property bool processRunning: uvProbe.running || authStatusProcess.running || refreshProcess.running

  function absoluteEnvironmentPath(name, fallback) {
    var value = String(Quickshell.env(name) || "")
    return value.charAt(0) === "/" ? value.replace(/\/$/, "") : fallback
  }

  function computeState() {
    if (demoMode) return "connected"
    if (!backendReady) return "setup"
    if ((authStatusProcess.running || refreshProcess.running) && !hasSummary) return "loading"
    if (failureKind === "rateLimited") return "rateLimited"
    if (failureKind === "offline") return "offline"
    if (failureKind === "reconnect") return "reconnect"
    if (failureKind === "local") return hasSummary ? "stale" : "localError"
    if (!configured) return "unauthenticated"
    if (summaryStale || cacheError !== "") return "stale"
    if (hasSummary) return "connected"
    return refreshing ? "loading" : "stale"
  }

  function stateText(value) {
    if (value === "setup") return uvPath === "" ? "Backend setup required" : "Backend environment is not ready"
    if (value === "unauthenticated") return "Connect Garmin to begin"
    if (value === "loading") return "Loading Garmin activities"
    if (value === "connected") return demoMode ? "Synthetic demo data" : "Connected"
    if (value === "stale") {
      if (cacheError === "missing") return "No cached summary is available"
      return cacheError !== "" ? "Cached summary is invalid" : "Showing an older cached summary"
    }
    if (value === "offline") return hasSummary ? "Offline · showing cached data" : "Garmin Connect is unavailable"
    if (value === "rateLimited") return "Garmin rate limit reached"
    if (value === "reconnect") return "Reconnect Garmin"
    if (value === "localError") return "Garmin backend reported an error"
    return "Garmin activities"
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
      refreshing = false
      failureKind = ""
      failureCode = ""
    } else if (!demoMode && uvPath === "" && !uvProbe.running) {
      probeUvCandidate(0)
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

  function backendCommand(arguments) {
    var command = [
      "/usr/bin/env", "UV_PROJECT_ENVIRONMENT=" + pythonEnvironmentPath,
      uvPath, "--directory", sourceDir, "run", "--locked", "--no-sync",
      "omarchy-garmin-activities"
    ]
    for (var i = 0; i < arguments.length; i++) command.push(arguments[i])
    return command
  }

  function checkAuthentication() {
    if (demoMode || uvPath === "" || sourceDir === "" || authStatusProcess.running || refreshProcess.running) return
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
    if (!backendReady || !configured || authStatusProcess.running || refreshProcess.running) return
    failureKind = ""
    failureCode = ""
    refreshing = true
    refreshTimedOut = false
    refreshProcess.command = backendCommand(["refresh", "--json"])
    refreshProcess.running = true
    refreshDeadline.restart()
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
    if (failureCode === "rate_limited") failureKind = "rateLimited"
    else if (failureCode === "network_unavailable" || failureCode === "remote_service_error") failureKind = "offline"
    else if (failureCode === "auth_required" || failureCode === "authentication_failed"
             || failureCode === "account_mismatch") failureKind = "reconnect"
    else if (failureCode === "refresh_in_progress") failureKind = ""
    else failureKind = "local"
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
    summaryFile.reload()
  }

  function launchSetup() {
    if (uvPath === "" || sourceDir === "") return
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
    if (uvPath === "" || sourceDir === "") return
    Quickshell.execDetached([
      "/usr/share/omarchy/bin/omarchy-launch-terminal",
      "/usr/bin/env", "UV_PROJECT_ENVIRONMENT=" + pythonEnvironmentPath,
      uvPath,
      "--directory", sourceDir,
      "run", "--locked", "--no-sync",
      "omarchy-garmin-activities", "auth", "login"
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
        root.checkAuthentication()
      } else {
        root.probeUvCandidate(candidateIndex + 1)
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
