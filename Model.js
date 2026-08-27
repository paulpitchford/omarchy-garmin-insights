.pragma library

var SUMMARY_SCHEMA_VERSION = 1
var MAX_SUMMARY_CHARS = 1048576
var MAX_ACTIVITY_COUNT = 20000
var MAX_TYPES = 256
var PERIOD_KEYS = ["today", "7Days", "30Days", "90Days"]
var PERIOD_DAYS = [1, 7, 30, 90]
var UPDATE_REPOSITORY_URL = "https://github.com/paulpitchford/omarchy-garmin-insights.git"
var UPDATE_DEFAULT_BRANCH_REF = "refs/heads/main"
var PLUGIN_ID = "io.github.paulpitchford.garmin-insights"
var RECOVERY_HEARTBEAT_INTERVAL_MS = 15000
var RECOVERY_SUSPEND_GAP_MS = 45000
var RECOVERY_TIMER_OVERRUN_TOLERANCE_MS = 5000
var RESUME_RECOVERY_DELAY_MS = 15000
var RECOVERY_BUSY_DELAY_MS = 5000
var OFFLINE_RECOVERY_DELAYS_MS = [30000, 120000]

var METRIC_KEYS = [
  "durationSeconds",
  "movingDurationSeconds",
  "distanceMetres",
  "elevationGainMetres",
  "energyJoules",
  "averageHeartRateBpm",
  "maximumHeartRateBpm",
  "averageSpeedMetresPerSecond",
  "averagePowerWatts",
  "totalSets",
  "totalRepetitions"
]

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

function isFiniteNumber(value) {
  return typeof value === "number" && isFinite(value) && value >= 0
}

function isInteger(value) {
  return isFiniteNumber(value) && Math.floor(value) === value
}

function validDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  var parsed = Date.parse(value + "T00:00:00Z")
  return isFinite(parsed) && new Date(parsed).toISOString().slice(0, 10) === value
}

function validTimestamp(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value)) return false
  var parsed = Date.parse(value)
  return isFinite(parsed) && new Date(parsed).toISOString() === value.replace("Z", ".000Z")
}

function normalizeMetric(metric) {
  if (!isObject(metric) || !isInteger(metric.contributingActivityCount)) return null
  if (metric.value !== null && !isFiniteNumber(metric.value)) return null
  if (metric.value === null && metric.contributingActivityCount !== 0) return null
  if (metric.value !== null && metric.contributingActivityCount === 0) return null
  return {
    value: metric.value,
    contributingActivityCount: metric.contributingActivityCount
  }
}

function normalizeAggregate(source, includeType) {
  if (!isObject(source) || !isInteger(source.activityCount) || source.activityCount > MAX_ACTIVITY_COUNT)
    return null

  var result = { activityCount: source.activityCount }
  if (includeType) {
    if (!validDisplayText(source.typeKey, 100, false)) return null
    result.typeKey = source.typeKey
  }

  for (var i = 0; i < METRIC_KEYS.length; i++) {
    var key = METRIC_KEYS[i]
    var metric = normalizeMetric(source[key])
    if (!metric || metric.contributingActivityCount > source.activityCount) return null
    result[key] = metric
  }
  return result
}

function normalizePeriod(source, expectedKey, expectedEndDate, expectedDays) {
  if (!isObject(source) || source.key !== expectedKey || !validDate(source.startDate)
      || !validDate(source.endDate) || source.endDate !== expectedEndDate
      || Date.parse(source.endDate + "T00:00:00Z") - Date.parse(source.startDate + "T00:00:00Z")
        !== (expectedDays - 1) * 86400000
      || !Array.isArray(source.byType) || source.byType.length > MAX_TYPES) return null

  var overall = normalizeAggregate(source.overall, false)
  if (!overall) return null

  var byType = []
  var seen = {}
  var typeCount = 0
  for (var i = 0; i < source.byType.length; i++) {
    var aggregate = normalizeAggregate(source.byType[i], true)
    if (!aggregate || seen[aggregate.typeKey]) return null
    seen[aggregate.typeKey] = true
    typeCount += aggregate.activityCount
    byType.push(aggregate)
  }
  if (typeCount !== overall.activityCount) return null

  return {
    key: expectedKey,
    startDate: source.startDate,
    endDate: source.endDate,
    overall: overall,
    byType: byType
  }
}

function parseSummary(raw) {
  var text = String(raw || "")
  if (text.length === 0) return { ok: false, error: "missing" }
  if (text.length > MAX_SUMMARY_CHARS) return { ok: false, error: "too_large" }

  var source
  try {
    source = JSON.parse(text)
  } catch (error) {
    return { ok: false, error: "invalid_json" }
  }

  if (!isObject(source) || source.schemaVersion !== SUMMARY_SCHEMA_VERSION
      || !validDate(source.asOfLocalDate) || !validTimestamp(source.generatedAt)
      || !Array.isArray(source.periods) || source.periods.length !== PERIOD_KEYS.length)
    return { ok: false, error: "invalid_schema" }

  var generatedMs = Date.parse(source.generatedAt)
  if (!isFinite(generatedMs)) return { ok: false, error: "invalid_timestamp" }

  var periods = []
  for (var i = 0; i < PERIOD_KEYS.length; i++) {
    var period = normalizePeriod(source.periods[i], PERIOD_KEYS[i], source.asOfLocalDate, PERIOD_DAYS[i])
    if (!period) return { ok: false, error: "invalid_period" }
    periods.push(period)
  }

  return {
    ok: true,
    summary: {
      schemaVersion: SUMMARY_SCHEMA_VERSION,
      generatedAt: source.generatedAt,
      generatedMs: generatedMs,
      asOfLocalDate: source.asOfLocalDate,
      periods: periods
    }
  }
}

var MAX_ACTIVITY_PAGE_CHARS = 65536
var MAX_ACTIVITY_DETAIL_CHARS = 8192
var MAX_ACTIVITY_ID_TEXT = "9223372036854775807"
var ACTIVITY_LIST_KEYS = [
  "activityId", "name", "typeKey", "startedAtLocal", "localDate", "durationSeconds",
  "distanceMetres", "energyJoules", "totalSets", "totalRepetitions"
]
var ACTIVITY_DETAIL_KEYS = ACTIVITY_LIST_KEYS.concat([
  "movingDurationSeconds", "elevationGainMetres", "averageHeartRateBpm",
  "maximumHeartRateBpm", "averageSpeedMetresPerSecond", "averagePowerWatts"
])

function hasOnlyKeys(source, expected) {
  if (!isObject(source) || Object.keys(source).length !== expected.length) return false
  for (var i = 0; i < expected.length; i++)
    if (!Object.prototype.hasOwnProperty.call(source, expected[i])) return false
  return true
}

function validDisplayText(value, maximum, optional) {
  if (value === null && optional) return true
  if (typeof value !== "string" || value.length < 1 || value.length > maximum) return false
  return !/[\x00-\x1f\x7f]/.test(value)
}

function validActivityId(value) {
  if (typeof value !== "string" || !/^[1-9][0-9]{0,18}$/.test(value)) return false
  return value.length < 19 || (value.length === 19 && value <= MAX_ACTIVITY_ID_TEXT)
}

function validLocalStart(value, localDate) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(value)
      || value.slice(0, 10) !== localDate) return false
  var parsed = Date.parse(value.replace(" ", "T") + "Z")
  return isFinite(parsed) && new Date(parsed).toISOString().slice(0, 19)
    === value.replace(" ", "T")
}

function optionalMeasurement(value, maximum, integerOnly) {
  if (value === null) return true
  if (!isFiniteNumber(value) || value > maximum) return false
  return !integerOnly || isInteger(value)
}

function normalizeActivity(source, detail) {
  var keys = detail ? ACTIVITY_DETAIL_KEYS : ACTIVITY_LIST_KEYS
  if (!hasOnlyKeys(source, keys) || !validActivityId(source.activityId)
      || !validDisplayText(source.name, 256, true)
      || !validDisplayText(source.typeKey, 100, false)
      || !validDate(source.localDate)
      || !validLocalStart(source.startedAtLocal, source.localDate)
      || !optionalMeasurement(source.durationSeconds, 31622400, false)
      || !optionalMeasurement(source.distanceMetres, 50000000, false)
      || !optionalMeasurement(source.energyJoules, 4184000000, false)
      || !optionalMeasurement(source.totalSets, 1000000, true)
      || !optionalMeasurement(source.totalRepetitions, 1000000, true)) return null
  if (detail && (!optionalMeasurement(source.movingDurationSeconds, 31622400, false)
      || !optionalMeasurement(source.elevationGainMetres, 1000000, false)
      || !optionalMeasurement(source.averageHeartRateBpm, 300, false)
      || !optionalMeasurement(source.maximumHeartRateBpm, 300, false)
      || !optionalMeasurement(source.averageSpeedMetresPerSecond, 200, false)
      || !optionalMeasurement(source.averagePowerWatts, 100000, false))) return null

  var activity = {}
  for (var i = 0; i < keys.length; i++) activity[keys[i]] = source[keys[i]]
  return activity
}

function parseCommandEnvelope(raw, command, maximum) {
  var text = String(raw || "")
  if (text.length === 0 || text.length > maximum) return null
  var envelope
  try {
    envelope = JSON.parse(text)
  } catch (error) {
    return null
  }
  if (!hasOnlyKeys(envelope, ["schemaVersion", "command", "ok", "data", "error"])
      || envelope.schemaVersion !== 1 || envelope.command !== command
      || typeof envelope.ok !== "boolean") return null
  if (envelope.ok) {
    if (!isObject(envelope.data) || envelope.error !== null) return null
  } else if (envelope.data !== null
      || !hasOnlyKeys(envelope.error, ["code", "message"])
      || !validDisplayText(envelope.error.code, 64, false)
      || !validDisplayText(envelope.error.message, 256, false)) return null
  return envelope
}

function normalizeActivityPage(data, expected) {
  if (!hasOnlyKeys(data, [
      "periodKey", "startDate", "endDate", "typeKey", "offset", "pageSize",
      "activities", "hasMore", "nextOffset", "stale"
    ]) || !expected || data.periodKey !== expected.periodKey
      || data.endDate !== expected.asOfDate || data.typeKey !== expected.typeKey
      || data.offset !== expected.offset || data.pageSize !== 20
      || !validDate(data.startDate) || !validDate(data.endDate)
      || PERIOD_KEYS.indexOf(data.periodKey) < 0
      || Date.parse(data.endDate + "T00:00:00Z") - Date.parse(data.startDate + "T00:00:00Z")
        !== (PERIOD_DAYS[PERIOD_KEYS.indexOf(data.periodKey)] - 1) * 86400000
      || !isInteger(data.offset) || data.offset > 19980 || data.offset % 20 !== 0
      || !Array.isArray(data.activities) || data.activities.length > 20
      || typeof data.hasMore !== "boolean" || typeof data.stale !== "boolean") return null
  if ((data.hasMore && (data.activities.length !== 20
        || data.nextOffset !== data.offset + 20 || data.nextOffset > 19980))
      || (!data.hasMore && data.nextOffset !== null)) return null

  var activities = []
  var seen = {}
  var previousStart = ""
  var previousId = ""
  for (var i = 0; i < data.activities.length; i++) {
    var activity = normalizeActivity(data.activities[i], false)
    if (!activity || seen[activity.activityId]
        || activity.localDate < data.startDate || activity.localDate > data.endDate
        || (data.typeKey !== null && activity.typeKey !== data.typeKey)) return null
    if (i > 0 && (activity.startedAtLocal > previousStart
        || (activity.startedAtLocal === previousStart
          && (activity.activityId.length > previousId.length
            || (activity.activityId.length === previousId.length && activity.activityId > previousId)))))
      return null
    seen[activity.activityId] = true
    previousStart = activity.startedAtLocal
    previousId = activity.activityId
    activities.push(activity)
  }
  return {
    periodKey: data.periodKey,
    startDate: data.startDate,
    endDate: data.endDate,
    typeKey: data.typeKey,
    offset: data.offset,
    pageSize: 20,
    activities: activities,
    hasMore: data.hasMore,
    nextOffset: data.nextOffset,
    stale: data.stale
  }
}

function parseActivityPageEnvelope(raw, expected) {
  var envelope = parseCommandEnvelope(raw, "activities.list", MAX_ACTIVITY_PAGE_CHARS)
  if (!envelope || !envelope.ok) return { ok: false, envelope: envelope }
  var page = normalizeActivityPage(envelope.data, expected)
  return page ? { ok: true, page: page, envelope: envelope }
    : { ok: false, envelope: envelope }
}

function parseActivityDetailEnvelope(raw, expectedActivityId) {
  var envelope = parseCommandEnvelope(raw, "activities.detail", MAX_ACTIVITY_DETAIL_CHARS)
  if (!envelope || !envelope.ok || !hasOnlyKeys(envelope.data, ["found", "activity"])
      || typeof envelope.data.found !== "boolean") return { ok: false, envelope: envelope }
  if (!envelope.data.found)
    return envelope.data.activity === null
      ? { ok: true, found: false, activity: null, envelope: envelope }
      : { ok: false, envelope: envelope }
  var activity = normalizeActivity(envelope.data.activity, true)
  if (!activity || activity.activityId !== expectedActivityId)
    return { ok: false, envelope: envelope }
  return { ok: true, found: true, activity: activity, envelope: envelope }
}

function normalizeActivityTypeFilter(typeKey) {
  return typeKey === undefined || typeKey === null || typeKey === "" ? null : String(typeKey)
}

function validCommit(value) {
  return typeof value === "string" && /^[0-9a-f]{40}$/.test(value)
}

function boundedProcessLine(raw, maximum) {
  var text = String(raw || "")
  if (text.slice(-1) === "\n") text = text.slice(0, -1)
  if (text.length === 0 || text.length > maximum || /[\r\n\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(text))
    return ""
  return text
}

function parseLocalCommit(raw) {
  var line = boundedProcessLine(raw, 40)
  return validCommit(line) ? line : ""
}

function parseRemoteCommit(raw) {
  var line = boundedProcessLine(raw, 96)
  var suffix = "\t" + UPDATE_DEFAULT_BRANCH_REF
  if (line.slice(-suffix.length) !== suffix) return ""
  var commit = line.slice(0, -suffix.length)
  return validCommit(commit) ? commit : ""
}

function parseUpdateClaim(raw, expectedLocalCommit) {
  var text = String(raw || "")
  if (text.length === 0 || text.length > 512 || !validCommit(expectedLocalCommit)) return null
  var value
  try {
    value = JSON.parse(text)
  } catch (error) {
    return null
  }
  if (!hasOnlyKeys(value, ["due", "localCommit", "remoteCommit", "schemaVersion"])
      || value.schemaVersion !== 1 || typeof value.due !== "boolean"
      || value.localCommit !== expectedLocalCommit
      || (value.remoteCommit !== null && !validCommit(value.remoteCommit))) return null
  return {
    due: value.due,
    localCommit: value.localCommit,
    remoteCommit: value.remoteCommit
  }
}

function commitsDiffer(localCommit, remoteCommit) {
  return validCommit(localCommit) && validCommit(remoteCommit) && localCommit !== remoteCommit
}

function safeVersion(value) {
  var text = String(value || "")
  return text.length <= 32 && /^\d+\.\d+\.\d+(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?$/.test(text)
    ? text : "Unknown"
}

function updateReviewCommand() {
  return [
    "/usr/share/omarchy/bin/omarchy-launch-terminal",
    "/usr/bin/omarchy", "plugin", "update", PLUGIN_ID
  ]
}

function garminConnectUrl(activityId) {
  return validActivityId(activityId)
    ? "https://connect.garmin.com/app/activity/" + activityId : ""
}

function aggregate(activityCount, duration, distance, energy, heartRate, speed, power, sets, repetitions) {
  return {
    activityCount: activityCount,
    durationSeconds: { value: duration, contributingActivityCount: activityCount },
    movingDurationSeconds: { value: duration === null ? null : duration * 0.92, contributingActivityCount: activityCount },
    distanceMetres: { value: distance, contributingActivityCount: distance === null ? 0 : activityCount },
    elevationGainMetres: { value: distance === null ? null : distance * 0.012, contributingActivityCount: distance === null ? 0 : activityCount },
    energyJoules: { value: energy, contributingActivityCount: energy === null ? 0 : activityCount },
    averageHeartRateBpm: { value: heartRate, contributingActivityCount: heartRate === null ? 0 : activityCount },
    maximumHeartRateBpm: { value: heartRate === null ? null : heartRate + 24, contributingActivityCount: heartRate === null ? 0 : activityCount },
    averageSpeedMetresPerSecond: { value: speed, contributingActivityCount: speed === null ? 0 : activityCount },
    averagePowerWatts: { value: power, contributingActivityCount: power === null ? 0 : activityCount },
    totalSets: { value: sets, contributingActivityCount: sets === null ? 0 : activityCount },
    totalRepetitions: { value: repetitions, contributingActivityCount: repetitions === null ? 0 : activityCount }
  }
}

function typed(typeKey, values) {
  values.typeKey = typeKey
  return values
}

function dateDaysAgo(generated, days) {
  var value = new Date(generated.getTime())
  value.setUTCDate(value.getUTCDate() - days)
  return value.toISOString().slice(0, 10)
}

function syntheticSummary(nowMs) {
  var generated = new Date(nowMs || Date.now())
  generated.setUTCMilliseconds(0)
  var today = dateDaysAgo(generated, 0)
  var running = typed("running", aggregate(2, 4380, 12400, 3100000, 146, 2.84, null, null, null))
  var cycling = typed("cycling", aggregate(1, 5400, 32600, 2800000, 138, 6.04, 184, null, null))
  var strength = typed("strength_training", aggregate(1, 2700, null, 1700000, 128, null, null, 12, 96))
  var week = aggregate(4, 12480, 45000, 7600000, 139, 4.54, 184, 12, 96)
  var month = aggregate(13, 39720, 143800, 24100000, 141, 4.42, 191, 38, 304)
  var quarter = aggregate(37, 112800, 421300, 69800000, 140, 4.37, 188, 104, 832)
  return {
    schemaVersion: SUMMARY_SCHEMA_VERSION,
    generatedAt: generated.toISOString().replace(".000Z", "Z"),
    generatedMs: generated.getTime(),
    asOfLocalDate: today,
    periods: [
      { key: "today", startDate: today, endDate: today, overall: aggregate(1, 2700, null, 1700000, 128, null, null, 12, 96), byType: [strength] },
      { key: "7Days", startDate: dateDaysAgo(generated, 6), endDate: today, overall: week, byType: [running, cycling, strength] },
      { key: "30Days", startDate: dateDaysAgo(generated, 29), endDate: today, overall: month, byType: [typed("running", aggregate(6, 13200, 38200, 8500000, 144, 2.89, null, null, null)), typed("cycling", aggregate(4, 20100, 105600, 9800000, 137, 5.25, 191, null, null)), typed("strength_training", aggregate(3, 6420, null, 5800000, 129, null, null, 38, 304))] },
      { key: "90Days", startDate: dateDaysAgo(generated, 89), endDate: today, overall: quarter, byType: [typed("running", aggregate(17, 38100, 110400, 24600000, 143, 2.90, null, null, null)), typed("cycling", aggregate(12, 56300, 310900, 27800000, 136, 5.52, 188, null, null)), typed("strength_training", aggregate(8, 18400, null, 17400000, 130, null, null, 104, 832))] }
    ]
  }
}

function syntheticActivityRecords(asOfDate) {
  if (!validDate(asOfDate)) return []
  var generated = new Date(asOfDate + "T12:00:00Z")
  var records = []
  var definitions = [
    { typeKey: "running", offsets: [1, 4, 10, 15, 20, 25, 35, 39, 43, 47, 51, 55, 59, 63, 67, 71, 75] },
    { typeKey: "cycling", offsets: [3, 9, 17, 27, 34, 41, 48, 55, 62, 69, 76, 83] },
    { typeKey: "strength_training", offsets: [0, 12, 22, 40, 50, 60, 70, 80] }
  ]
  var nextId = 900000000000
  for (var group = 0; group < definitions.length; group++) {
    var definition = definitions[group]
    for (var index = 0; index < definition.offsets.length; index++) {
      var typeKey = definition.typeKey
      var localDate = dateDaysAgo(generated, definition.offsets[index])
      var strength = typeKey === "strength_training"
      var cycling = typeKey === "cycling"
      nextId++
      records.push({
        activityId: String(nextId),
        name: strength ? "Synthetic strength session" : (cycling ? "Synthetic cycle" : "Synthetic run"),
        typeKey: typeKey,
        startedAtLocal: localDate + (strength ? " 18:15:00" : " 07:30:00"),
        localDate: localDate,
        durationSeconds: strength ? 2700 : (cycling ? 5400 : 2190),
        movingDurationSeconds: strength ? null : (cycling ? 5100 : 2070),
        distanceMetres: strength ? null : (cycling ? 32600 : 6200),
        elevationGainMetres: strength ? null : (cycling ? 410 : 74),
        energyJoules: strength ? 1700000 : (cycling ? 2800000 : 1550000),
        averageHeartRateBpm: strength ? 128 : (cycling ? 138 : 146),
        maximumHeartRateBpm: strength ? 152 : (cycling ? 164 : 174),
        averageSpeedMetresPerSecond: strength ? null : (cycling ? 6.04 : 2.84),
        averagePowerWatts: cycling ? 184 : null,
        totalSets: strength ? 12 : null,
        totalRepetitions: strength ? 96 : null
      })
    }
  }
  records.sort(function(a, b) {
    if (a.startedAtLocal !== b.startedAtLocal) return a.startedAtLocal < b.startedAtLocal ? 1 : -1
    if (a.activityId.length !== b.activityId.length) return b.activityId.length - a.activityId.length
    return a.activityId < b.activityId ? 1 : -1
  })
  return records
}

function syntheticActivityPage(periodKey, asOfDate, typeKey, offset) {
  var periodIndex = PERIOD_KEYS.indexOf(periodKey)
  if (periodIndex < 0 || !validDate(asOfDate) || (typeKey !== null
      && !validDisplayText(typeKey, 100, false)) || !isInteger(offset)
      || offset > 19980 || offset % 20 !== 0) return null
  var generated = new Date(asOfDate + "T12:00:00Z")
  var startDate = dateDaysAgo(generated, PERIOD_DAYS[periodIndex] - 1)
  var records = syntheticActivityRecords(asOfDate).filter(function(activity) {
    return activity.localDate >= startDate && (typeKey === null || activity.typeKey === typeKey)
  })
  var visible = records.slice(offset, offset + 20)
  return {
    periodKey: periodKey,
    startDate: startDate,
    endDate: asOfDate,
    typeKey: typeKey,
    offset: offset,
    pageSize: 20,
    activities: visible.map(function(activity) {
      var item = {}
      for (var i = 0; i < ACTIVITY_LIST_KEYS.length; i++)
        item[ACTIVITY_LIST_KEYS[i]] = activity[ACTIVITY_LIST_KEYS[i]]
      return item
    }),
    hasMore: records.length > offset + 20,
    nextOffset: records.length > offset + 20 ? offset + 20 : null,
    stale: false
  }
}

function syntheticActivityDetail(activityId, asOfDate) {
  var records = syntheticActivityRecords(asOfDate)
  for (var i = 0; i < records.length; i++)
    if (records[i].activityId === activityId) return records[i]
  return null
}

function failureKindForCode(code) {
  var value = String(code || "internal_error")
  if (value === "rate_limited") return "rateLimited"
  if (value === "network_unavailable" || value === "remote_service_error") return "offline"
  if (value === "auth_required" || value === "authentication_failed" || value === "account_mismatch")
    return "reconnect"
  if (value === "refresh_in_progress") return ""
  return "local"
}

function suspendGapDetected(previousTickMs, currentTickMs) {
  return typeof previousTickMs === "number" && isFinite(previousTickMs) && previousTickMs > 0
    && typeof currentTickMs === "number" && isFinite(currentTickMs)
    && currentTickMs >= previousTickMs
    && currentTickMs - previousTickMs >= RECOVERY_SUSPEND_GAP_MS
}

function timerOverrunDetected(armedAtMs, currentMs, intervalMs) {
  return typeof armedAtMs === "number" && isFinite(armedAtMs) && armedAtMs > 0
    && typeof currentMs === "number" && isFinite(currentMs) && currentMs >= armedAtMs
    && typeof intervalMs === "number" && isFinite(intervalMs) && intervalMs > 0
    && currentMs - armedAtMs >= intervalMs + RECOVERY_TIMER_OVERRUN_TOLERANCE_MS
}

function recoveryTransition(retryCount, resultKind) {
  if (resultKind !== "offline" || !isInteger(retryCount))
    return { active: false, retryCount: 0, delayMs: -1 }
  if (retryCount >= OFFLINE_RECOVERY_DELAYS_MS.length)
    return { active: false, retryCount: 0, delayMs: -1 }
  return {
    active: true,
    retryCount: retryCount + 1,
    delayMs: OFFLINE_RECOVERY_DELAYS_MS[retryCount]
  }
}

function refreshOrigin(requestedOrigin, recoveryPending) {
  var origin = requestedOrigin === "scheduled" || requestedOrigin === "authentication"
    || requestedOrigin === "recovery" ? requestedOrigin : "manual"
  return origin === "manual" && recoveryPending ? "recovery" : origin
}

function connectionState(options) {
  if (options.demoMode) return "connected"
  if ((options.authStatusRunning || options.refreshRunning) && !options.hasSummary) return "loading"
  if (!options.backendReady) return "setup"
  if (options.failureKind === "rateLimited") return "rateLimited"
  if (options.failureKind === "offline") return "offline"
  if (options.failureKind === "reconnect") return "reconnect"
  if (options.failureKind === "local") return options.hasSummary ? "stale" : "localError"
  if (!options.configured) return "unauthenticated"
  if (options.summaryStale || options.cacheError !== "") return "stale"
  if (options.hasSummary) return "connected"
  return options.refreshing ? "loading" : "stale"
}

function statusText(state, options) {
  if (state === "setup") return options.uvAvailable ? "Backend environment is not ready" : "Backend setup required"
  if (state === "unauthenticated") return "Connect Garmin to begin"
  if (state === "loading") return "Loading Garmin insights"
  if (state === "connected") return options.demoMode ? "Synthetic demo data" : "Connected"
  if (state === "stale") {
    if (options.cacheError === "missing") return "No cached summary is available"
    return options.cacheError !== "" ? "Cached summary is invalid" : "Showing an older cached summary"
  }
  if (state === "offline") return options.hasSummary ? "Offline · showing cached data" : "Garmin Connect is unavailable"
  if (state === "rateLimited") return "Garmin rate limit reached"
  if (state === "reconnect") return "Reconnect Garmin"
  if (state === "localError") return "Garmin backend reported an error"
  return "Garmin insights"
}

function backendCommand(uvPath, sourceDir, pythonEnvironmentPath, extraArguments) {
  var command = [
    "/usr/bin/env", "UV_PROJECT_ENVIRONMENT=" + String(pythonEnvironmentPath),
    String(uvPath), "--directory", String(sourceDir), "run", "--locked", "--no-sync",
    "omarchy-garmin-insights"
  ]
  for (var i = 0; i < extraArguments.length; i++) command.push(String(extraArguments[i]))
  return command
}

function periodByKey(summary, key) {
  if (!summary || !Array.isArray(summary.periods)) return null
  for (var i = 0; i < summary.periods.length; i++)
    if (summary.periods[i].key === key) return summary.periods[i]
  return null
}

function periodLabel(key) {
  if (key === "today") return "Today"
  if (key === "7Days") return "7 days"
  if (key === "30Days") return "30 days"
  if (key === "90Days") return "90 days"
  return "Period"
}

function typeLabel(key) {
  var words = String(key || "Other").replace(/[_-]+/g, " ")
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function formatCount(value) {
  var count = Math.max(0, Math.floor(Number(value) || 0))
  return count + (count === 1 ? " activity" : " activities")
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—"
  var minutes = Math.round(Number(seconds) / 60)
  var hours = Math.floor(minutes / 60)
  var remainder = minutes % 60
  if (hours === 0) return remainder + "m"
  return remainder === 0 ? hours + "h" : hours + "h " + remainder + "m"
}

function formatDistance(metres, imperial) {
  if (metres === null || metres === undefined) return "—"
  var value = imperial ? Number(metres) / 1609.344 : Number(metres) / 1000
  return value.toFixed(value < 10 ? 1 : 0) + (imperial ? " mi" : " km")
}

function formatEnergy(joules, imperial) {
  if (joules === null || joules === undefined) return "—"
  if (imperial) return Math.round(Number(joules) / 4184) + " kcal"
  return (Number(joules) / 1000000).toFixed(1) + " MJ"
}

function formatElevation(metres, imperial) {
  if (metres === null || metres === undefined) return "—"
  return Math.round(imperial ? Number(metres) * 3.28084 : Number(metres))
    + (imperial ? " ft" : " m")
}

function formatSpeed(metresPerSecond, imperial) {
  if (metresPerSecond === null || metresPerSecond === undefined) return "—"
  var value = Number(metresPerSecond) * (imperial ? 2.236936 : 3.6)
  return value.toFixed(1) + (imperial ? " mph" : " km/h")
}

function formatIntegerMetric(value, suffix) {
  if (value === null || value === undefined) return "—"
  return Math.round(Number(value)) + String(suffix || "")
}

function activityHeadline(activity, imperial) {
  if (!activity) return ""
  if (activity.distanceMetres !== null) return formatDistance(activity.distanceMetres, imperial)
  if (activity.totalRepetitions !== null)
    return formatIntegerMetric(activity.totalRepetitions, " reps")
  if (activity.energyJoules !== null) return formatEnergy(activity.energyJoules, imperial)
  return formatDuration(activity.durationSeconds)
}
