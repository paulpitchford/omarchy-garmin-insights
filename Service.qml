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
  property var cachedActivityTrends: null
  property string activityTrendsCacheError: ""
  property string failureKind: ""
  property string failureCode: ""
  property string cacheError: ""
  property double nowMs: Date.now()
  property int authPollTicks: 0
  property bool statusTimedOut: false
  property bool refreshTimedOut: false
  property bool summaryCacheTimedOut: false
  property bool activityTrendsCacheTimedOut: false
  property bool summaryCacheReloadPending: false
  property bool activityTrendsCacheReloadPending: false
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
  property bool updateChecksEnabled: false
  property bool updateInitialCheckStarted: false
  property bool updateSupported: false
  property bool updateAvailable: false
  property string updateStage: ""
  property string updateOutput: ""
  property bool updateOutputTooLarge: false
  property bool updateTimedOut: false
  property bool updateManual: false
  property string localCommit: ""
  property string remoteCommit: ""
  property bool recoveryActive: false
  property int recoveryRetryCount: 0
  property double recoveryHeartbeatMs: Date.now()

  readonly property string sourceDir: manifest && manifest.__sourceDir ? String(manifest.__sourceDir) : ""
  readonly property string homeDir: Quickshell.env("HOME")
  readonly property string cacheRoot: absoluteEnvironmentPath("XDG_CACHE_HOME", homeDir + "/.cache")
  readonly property string applicationCacheRoot: cacheRoot + "/omarchy-garmin-insights"
  readonly property string runtimeRoot: absoluteEnvironmentPath("XDG_RUNTIME_DIR", "")
  readonly property string applicationRuntimeRoot: runtimeRoot === ""
    ? "" : runtimeRoot + "/omarchy-garmin-insights"
  readonly property string expectedInstallDir: homeDir
    + "/.config/omarchy/plugins/io.github.paulpitchford.garmin-insights"
  readonly property string updateHelperPath: sourceDir + "/src/omarchy_garmin/update_helper.py"
  readonly property string installedVersion: Model.safeVersion(
    manifest && manifest.version ? manifest.version : "")
  readonly property var updateGitEnvironment: ({
    GIT_ASKPASS: "/usr/bin/false",
    GIT_CONFIG_COUNT: "0",
    GIT_CONFIG_GLOBAL: "/dev/null",
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_TERMINAL_PROMPT: "0",
    HOME: "/nonexistent",
    SSH_ASKPASS: "/usr/bin/false",
    XDG_CONFIG_HOME: "/nonexistent"
  })
  readonly property string pythonEnvironmentPath: applicationCacheRoot + "/uv-environment"
  readonly property var summary: demoMode ? Model.syntheticSummary(nowMs) : cachedSummary
  readonly property var candidateActivityTrends: demoMode
    ? Model.syntheticActivityTrends(nowMs) : cachedActivityTrends
  readonly property var activityTrends: Model.trendsForSummary(candidateActivityTrends, summary)
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
  readonly property bool updateCheckRunning: updateStage !== "" || updateHelperProcess.running
    || updateGitProcess.running
  readonly property bool displayCacheRunning: summaryCacheProcess.running
    || activityTrendsCacheProcess.running
  readonly property bool processRunning: uvProbe.running || cacheRootProcess.running
    || authStatusProcess.running || refreshProcess.running || activityViewRunning
    || displayCacheRunning

  function absoluteEnvironmentPath(name, fallback) {
    var value = String(Quickshell.env(name) || "")
    return value.charAt(0) === "/" ? value.replace(/\/$/, "") : fallback
  }

  function configure(minutes, demo, checkUpdates) {
    var parsedMinutes = Math.floor(Number(minutes))
    if (!isFinite(parsedMinutes)) parsedMinutes = 30
    parsedMinutes = Math.max(5, Math.min(360, parsedMinutes))
    var nextDemo = demo === true
    var demoChanged = demoMode !== nextDemo
    var nextUpdateChecks = checkUpdates !== false
    var updateSettingChanged = updateChecksEnabled !== nextUpdateChecks
    refreshMinutes = parsedMinutes
    demoMode = nextDemo
    updateChecksEnabled = nextUpdateChecks
    if (!nextUpdateChecks && updateSettingChanged) cancelUpdateCheck()
    else if (nextUpdateChecks && updateSettingChanged && !updateInitialCheckStarted)
      updateStartupDelay.restart()
    if (demoChanged && demoMode) {
      authStatusProcess.running = false
      refreshProcess.running = false
      activityListProcess.running = false
      activityDetailProcess.running = false
      summaryCacheProcess.running = false
      activityTrendsCacheProcess.running = false
      summaryCacheDeadline.stop()
      activityTrendsCacheDeadline.stop()
      summaryCacheReloadPending = false
      activityTrendsCacheReloadPending = false
      refreshing = false
      stopRecovery()
      failureKind = ""
      failureCode = ""
    } else if (!demoMode && uvPath === "" && !uvProbe.running) {
      probeUvCandidate(0)
    } else if (!demoMode && !cacheRootReady) {
      prepareCacheRoot()
    } else if (demoChanged && !demoMode) {
      requestDisplayCacheReload()
      checkAuthentication()
    }
  }

  function cancelUpdateCheck() {
    updateStartupDelay.stop()
    updateDeadline.stop()
    updateStage = ""
    if (updateHelperProcess.running) updateHelperProcess.signal(9)
    if (updateGitProcess.running) updateGitProcess.signal(9)
    updateSupported = false
    updateAvailable = false
    localCommit = ""
    remoteCommit = ""
    updateInitialCheckStarted = false
  }

  function completeUpdateCheck() {
    updateDeadline.stop()
    updateStage = ""
    updateOutput = ""
    updateOutputTooLarge = false
    updateTimedOut = false
  }

  function collectUpdateOutput(data) {
    var line = String(data || "")
    var next = updateOutput === "" ? line : updateOutput + "\n" + line
    if (next.length > 1024) {
      updateOutputTooLarge = true
      if (updateHelperProcess.running) updateHelperProcess.signal(9)
      if (updateGitProcess.running) updateGitProcess.signal(9)
      return
    }
    updateOutput = next
  }

  function startUpdateHelper(stage, extraArguments) {
    updateStage = stage
    updateOutput = ""
    updateOutputTooLarge = false
    updateTimedOut = false
    updateHelperProcess.command = ["/usr/bin/python3", updateHelperPath].concat(extraArguments)
    updateHelperProcess.running = true
    updateDeadline.interval = 5000
    updateDeadline.restart()
  }

  function startUpdateGit(stage, gitArguments, deadlineMs) {
    updateStage = stage
    updateOutput = ""
    updateOutputTooLarge = false
    updateTimedOut = false
    updateGitProcess.command = ["/usr/bin/git"].concat(gitArguments)
    updateGitProcess.running = true
    updateDeadline.interval = deadlineMs
    updateDeadline.restart()
  }

  function startUpdateCheck(manual) {
    if (!updateChecksEnabled || updateCheckRunning || sourceDir === "") return
    updateInitialCheckStarted = true
    updateManual = manual === true
    if (sourceDir !== expectedInstallDir || applicationRuntimeRoot === "") {
      updateSupported = false
      updateAvailable = false
      completeUpdateCheck()
      return
    }
    startUpdateHelper("validate", ["validate-checkout", sourceDir, expectedInstallDir])
  }

  function checkUpdatesNow() {
    if (!updateChecksEnabled || !updateSupported || updateCheckRunning) return
    startUpdateCheck(true)
  }

  function handleUpdateHelper(exitCode) {
    updateDeadline.stop()
    var stage = updateStage
    if (stage === "") return
    if (updateTimedOut || updateOutputTooLarge || exitCode !== 0) {
      if (stage === "validate") {
        updateSupported = false
        updateAvailable = false
      }
      completeUpdateCheck()
      return
    }
    if (stage === "validate") {
      if (updateOutput !== "") {
        updateSupported = false
        updateAvailable = false
        completeUpdateCheck()
        return
      }
      startUpdateGit("top", ["-C", sourceDir, "rev-parse", "--show-toplevel"], 5000)
      return
    }
    if (stage === "claim") {
      var claim = Model.parseUpdateClaim(updateOutput, localCommit)
      if (!claim) {
        completeUpdateCheck()
        return
      }
      remoteCommit = claim.remoteCommit === null ? "" : claim.remoteCommit
      updateAvailable = Model.commitsDiffer(localCommit, remoteCommit)
      if (claim.due) {
        startUpdateGit("remote", [
          "ls-remote", Model.UPDATE_REPOSITORY_URL, Model.UPDATE_DEFAULT_BRANCH_REF
        ], 10000)
      } else completeUpdateCheck()
      return
    }
    completeUpdateCheck()
  }

  function handleUpdateGit(exitCode) {
    updateDeadline.stop()
    var stage = updateStage
    if (stage === "") return
    if (updateTimedOut || updateOutputTooLarge || exitCode !== 0) {
      if (stage !== "remote") {
        updateSupported = false
        updateAvailable = false
      }
      completeUpdateCheck()
      return
    }
    if (stage === "top") {
      if (Model.boundedProcessLine(updateOutput, 4096) !== sourceDir) {
        updateSupported = false
        updateAvailable = false
        completeUpdateCheck()
      } else startUpdateGit("branch", [
        "-C", sourceDir, "symbolic-ref", "--quiet", "--short", "HEAD"
      ], 5000)
      return
    }
    if (stage === "branch") {
      if (Model.boundedProcessLine(updateOutput, 16) !== "main") {
        updateSupported = false
        updateAvailable = false
        completeUpdateCheck()
      } else startUpdateGit("head", [
        "-C", sourceDir, "rev-parse", "--verify", "HEAD^{commit}"
      ], 5000)
      return
    }
    if (stage === "head") {
      localCommit = Model.parseLocalCommit(updateOutput)
      if (localCommit === "") {
        updateSupported = false
        updateAvailable = false
        completeUpdateCheck()
        return
      }
      updateSupported = true
      var claimArguments = [
        "claim", applicationCacheRoot, applicationRuntimeRoot, localCommit
      ]
      if (updateManual) claimArguments.push("--force")
      startUpdateHelper("claim", claimArguments)
      return
    }
    if (stage === "remote") {
      var checkedRemote = Model.parseRemoteCommit(updateOutput)
      if (checkedRemote === "") {
        completeUpdateCheck()
        return
      }
      remoteCommit = checkedRemote
      updateAvailable = Model.commitsDiffer(localCommit, remoteCommit)
      startUpdateHelper("record", [
        "record", applicationCacheRoot, applicationRuntimeRoot, localCommit, remoteCommit
      ])
      return
    }
    completeUpdateCheck()
  }

  function launchUpdateReview() {
    if (!updateChecksEnabled || !updateSupported || !updateAvailable || updateCheckRunning) return
    Quickshell.execDetached(Model.updateReviewCommand())
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

  function requestSummaryCacheReload() {
    if (demoMode || !cacheRootReady || uvPath === "" || sourceDir === "") return
    if (summaryCacheProcess.running) {
      summaryCacheReloadPending = true
      return
    }
    summaryCacheReloadPending = false
    summaryCacheTimedOut = false
    summaryCacheProcess.command = backendCommand([
      "cache", "read", "--json", "--kind", "summary"
    ])
    summaryCacheProcess.running = true
    summaryCacheDeadline.restart()
  }

  function requestActivityTrendsCacheReload() {
    if (demoMode || !cacheRootReady || uvPath === "" || sourceDir === "") return
    if (activityTrendsCacheProcess.running) {
      activityTrendsCacheReloadPending = true
      return
    }
    activityTrendsCacheReloadPending = false
    activityTrendsCacheTimedOut = false
    activityTrendsCacheProcess.command = backendCommand([
      "cache", "read", "--json", "--kind", "activity-trends"
    ])
    activityTrendsCacheProcess.running = true
    activityTrendsCacheDeadline.restart()
  }

  function requestDisplayCacheReload() {
    requestSummaryCacheReload()
    requestActivityTrendsCacheReload()
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

  function stopRecovery() {
    recoveryTimer.stop()
    recoveryActive = false
    recoveryRetryCount = 0
  }

  function scheduleRecovery(delayMs) {
    recoveryActive = true
    recoveryTimer.interval = delayMs
    recoveryTimer.armedAtMs = Date.now()
    recoveryTimer.restart()
  }

  function applyRecoveryResult(resultKind) {
    recoveryTimer.stop()
    var transition = Model.recoveryTransition(recoveryRetryCount, resultKind)
    recoveryActive = transition.active
    recoveryRetryCount = transition.retryCount
    if (transition.delayMs >= 0) scheduleRecovery(transition.delayMs)
  }

  function beginResumeRecovery() {
    if (demoMode || !backendReady || !configured) return
    if (!recoveryActive) {
      recoveryActive = true
      recoveryRetryCount = 0
    }
    if (!refreshProcess.running) scheduleRecovery(Model.RESUME_RECOVERY_DELAY_MS)
  }

  function runRecoveryAttempt() {
    if (!recoveryActive) return
    if (demoMode || !backendReady || !configured) {
      stopRecovery()
      return
    }
    if (authStatusProcess.running || refreshProcess.running || activityViewRunning) {
      scheduleRecovery(Model.RECOVERY_BUSY_DELAY_MS)
      return
    }
    refresh("recovery")
  }

  function refresh(requestedOrigin) {
    var origin = Model.refreshOrigin(requestedOrigin, recoveryTimer.running)
    if (demoMode) {
      stopRecovery()
      nowMs = Date.now()
      return true
    }
    if (!backendReady || !configured || authStatusProcess.running || refreshProcess.running
        || activityViewRunning || (origin === "scheduled" && recoveryActive)) return false
    if (origin === "recovery") recoveryTimer.stop()
    else stopRecovery()
    failureKind = ""
    failureCode = ""
    refreshing = true
    refreshTimedOut = false
    refreshProcess.command = backendCommand(["refresh", "--json"])
    refreshProcess.running = true
    refreshDeadline.restart()
    return true
  }

  function periodAllowsType(period, typeKey) {
    if (typeKey === null) return true
    if (!period || !Array.isArray(period.byType)) return false
    for (var i = 0; i < period.byType.length; i++)
      if (period.byType[i].typeKey === typeKey) return true
    return false
  }

  function loadActivityPage(periodKey, asOfDate, typeKey, offset) {
    var normalizedType = Model.normalizeActivityTypeFilter(typeKey)
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
      stopRecovery()
      return
    }
    backendReady = true
    if (exitCode !== 0 || !envelope.ok || !envelope.data || typeof envelope.data.configured !== "boolean") {
      safeFailure(envelope && envelope.error ? envelope.error.code : "internal_error")
      stopRecovery()
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
      refresh("authentication")
    } else stopRecovery()
  }

  function handleRefresh(exitCode, raw) {
    refreshing = false
    var envelope = parseEnvelope(raw, "refresh")
    if (refreshTimedOut) {
      failureKind = "offline"
      failureCode = "request_timeout"
      applyRecoveryResult(failureKind)
      return
    }
    if (!envelope) {
      backendReady = false
      failureKind = "local"
      failureCode = "backend_unavailable"
      applyRecoveryResult(failureKind)
      return
    }
    if (exitCode !== 0 || envelope.ok !== true) {
      safeFailure(envelope.error ? envelope.error.code : "internal_error")
      applyRecoveryResult(failureKind)
      return
    }
    backendReady = true
    configured = true
    verified = true
    failureKind = ""
    failureCode = ""
    applyRecoveryResult("success")
    refreshGeneration++
    requestDisplayCacheReload()
  }

  function handleSummaryCache(exitCode, raw) {
    summaryCacheDeadline.stop()
    var result = summaryCacheTimedOut
      ? { ok: false, error: "timeout" }
      : Model.parseDisplayCacheEnvelope(raw, "summary")
    if (exitCode === 0 && result.ok) {
      cachedSummary = result.summary
      cacheError = ""
    } else cacheError = Model.summaryCacheReadError(
      cachedSummary !== null, cacheError, result.error)
    nowMs = Date.now()
    if (summaryCacheReloadPending) {
      summaryCacheReloadPending = false
      requestSummaryCacheReload()
    }
  }

  function handleActivityTrendsCache(exitCode, raw) {
    activityTrendsCacheDeadline.stop()
    var result = activityTrendsCacheTimedOut
      ? { ok: false, error: "timeout" }
      : Model.parseDisplayCacheEnvelope(raw, "activity-trends")
    if (exitCode === 0 && result.ok) {
      cachedActivityTrends = result.trends
      activityTrendsCacheError = ""
    } else activityTrendsCacheError = result.error || "local_storage_error"
    if (activityTrendsCacheReloadPending) {
      activityTrendsCacheReloadPending = false
      requestActivityTrendsCacheReload()
    }
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
        root.requestDisplayCacheReload()
        root.checkAuthentication()
      } else {
        root.cacheRootReady = false
        root.backendReady = false
        root.stopRecovery()
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
    id: summaryCacheProcess
    command: []
    stdout: StdioCollector { id: summaryCacheStdout; waitForEnd: true }
    onExited: function(exitCode) {
      root.handleSummaryCache(exitCode, summaryCacheStdout.text)
    }
  }

  Process {
    id: activityTrendsCacheProcess
    command: []
    stdout: StdioCollector { id: activityTrendsCacheStdout; waitForEnd: true }
    onExited: function(exitCode) {
      root.handleActivityTrendsCache(exitCode, activityTrendsCacheStdout.text)
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

  Process {
    id: updateHelperProcess
    command: []
    clearEnvironment: true
    stdout: SplitParser { onRead: function(data) { root.collectUpdateOutput(data) } }
    onExited: function(exitCode) { root.handleUpdateHelper(exitCode) }
  }

  Process {
    id: updateGitProcess
    command: []
    workingDirectory: "/"
    clearEnvironment: true
    environment: root.updateGitEnvironment
    stdout: SplitParser { onRead: function(data) { root.collectUpdateOutput(data) } }
    onExited: function(exitCode) { root.handleUpdateGit(exitCode) }
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
    id: summaryCacheDeadline
    interval: 5000
    onTriggered: {
      root.summaryCacheTimedOut = true
      summaryCacheProcess.running = false
    }
  }

  Timer {
    id: activityTrendsCacheDeadline
    interval: 5000
    onTriggered: {
      root.activityTrendsCacheTimedOut = true
      activityTrendsCacheProcess.running = false
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
    id: updateStartupDelay
    interval: 30000
    onTriggered: root.startUpdateCheck(false)
  }

  Timer {
    id: updateDeadline
    interval: 5000
    onTriggered: {
      root.updateTimedOut = true
      if (updateHelperProcess.running) updateHelperProcess.signal(9)
      else if (updateGitProcess.running) updateGitProcess.signal(9)
      else if (["validate", "claim", "record"].indexOf(root.updateStage) !== -1)
        root.handleUpdateHelper(-1)
      else root.handleUpdateGit(-1)
    }
  }

  Timer {
    id: recoveryTimer
    property double armedAtMs: 0
    interval: Model.RESUME_RECOVERY_DELAY_MS
    onTriggered: {
      var currentMs = Date.now()
      if (Model.timerOverrunDetected(armedAtMs, currentMs, interval)) {
        root.recoveryHeartbeatMs = currentMs
        root.scheduleRecovery(Model.RESUME_RECOVERY_DELAY_MS)
      } else root.runRecoveryAttempt()
    }
  }

  Timer {
    id: refreshTimer
    property double armedAtMs: Date.now()
    interval: root.refreshMinutes * 60000
    repeat: true
    running: !root.demoMode
    onIntervalChanged: armedAtMs = Date.now()
    onRunningChanged: if (running) armedAtMs = Date.now()
    onTriggered: {
      var currentMs = Date.now()
      var overranDuringSuspend = Model.timerOverrunDetected(armedAtMs, currentMs, interval)
      armedAtMs = currentMs
      if (overranDuringSuspend) root.beginResumeRecovery()
      else root.refresh("scheduled")
    }
  }

  Timer {
    interval: Model.RECOVERY_HEARTBEAT_INTERVAL_MS
    repeat: true
    running: true
    onTriggered: {
      var currentMs = Date.now()
      if (Model.suspendGapDetected(root.recoveryHeartbeatMs, currentMs))
        root.beginResumeRecovery()
      root.recoveryHeartbeatMs = currentMs
      root.nowMs = currentMs
    }
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
