.pragma library

var SUMMARY_SCHEMA_VERSION = 1
var MAX_SUMMARY_CHARS = 1048576
var MAX_ACTIVITY_COUNT = 20000
var MAX_TYPES = 256
var ACTIVITY_TRENDS_SCHEMA_VERSION = 1
var MAX_ACTIVITY_TRENDS_CHARS = 65536
var WELLNESS_SCHEMA_VERSION = 1
var MAX_WELLNESS_CHARS = 65536
var WELLNESS_SOURCE_KEYS = [
  "user_summary", "steps", "body_battery", "sleep", "hrv",
  "resting_heart_rate", "training_readiness"
]
var WELLNESS_FAILURE_KEYS = [
  "authentication", "rate_limit", "offline_transport", "remote_service",
  "invalid_data", "local_storage", "unsupported"
]
var WELLNESS_PERIOD_KEYS = ["7Days", "30Days"]
var WELLNESS_PERIOD_DAYS = [7, 30]
var TREND_PERIOD_KEYS = ["7Days", "30Days", "90Days"]
var TREND_PERIOD_DAYS = [7, 30, 90]
var TREND_POINT_COUNTS = [7, 30, 13]
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

function addCalendarDays(value, days) {
  var parsed = new Date(value + "T00:00:00Z")
  parsed.setUTCDate(parsed.getUTCDate() + days)
  return parsed.toISOString().slice(0, 10)
}

function normalizeTrendMetric(metric, activityCount) {
  if (!hasOnlyKeys(metric, ["value", "contributingActivityCount"])
      || !isInteger(metric.contributingActivityCount)
      || metric.contributingActivityCount > activityCount) return null
  if (activityCount === 0)
    return metric.value === 0 && metric.contributingActivityCount === 0
      ? { value: 0, contributingActivityCount: 0 } : null
  if (metric.contributingActivityCount === 0)
    return metric.value === null ? { value: null, contributingActivityCount: 0 } : null
  return isFiniteNumber(metric.value)
    ? { value: metric.value, contributingActivityCount: metric.contributingActivityCount }
    : null
}

function normalizeTrendPoint(source, expectedStart, expectedEnd, expectedPartial) {
  if (!hasOnlyKeys(source, [
      "startDate", "endDate", "partial", "activityCount", "durationSeconds",
      "distanceMetres", "elevationGainMetres", "energyJoules"
    ]) || source.startDate !== expectedStart || source.endDate !== expectedEnd
      || source.partial !== expectedPartial || !isInteger(source.activityCount)
      || source.activityCount > MAX_ACTIVITY_COUNT) return null
  var point = {
    startDate: source.startDate,
    endDate: source.endDate,
    partial: source.partial,
    activityCount: source.activityCount
  }
  var keys = ["durationSeconds", "distanceMetres", "elevationGainMetres", "energyJoules"]
  for (var i = 0; i < keys.length; i++) {
    var metric = normalizeTrendMetric(source[keys[i]], source.activityCount)
    if (!metric) return null
    point[keys[i]] = metric
  }
  return point
}

function normalizeTrendPeriod(source, expectedKey, expectedEnd, expectedDays, expectedPoints) {
  var expectedStart = addCalendarDays(expectedEnd, 1 - expectedDays)
  if (!hasOnlyKeys(source, ["key", "startDate", "endDate", "points"])
      || source.key !== expectedKey || source.startDate !== expectedStart
      || source.endDate !== expectedEnd || !Array.isArray(source.points)
      || source.points.length !== expectedPoints) return null

  var points = []
  var pointStart = expectedStart
  for (var i = 0; i < source.points.length; i++) {
    var span = expectedKey === "90Days" ? (i === 0 ? 6 : 7) : 1
    var pointEnd = addCalendarDays(pointStart, span - 1)
    var point = normalizeTrendPoint(
      source.points[i], pointStart, pointEnd, i === source.points.length - 1)
    if (!point) return null
    points.push(point)
    pointStart = addCalendarDays(pointEnd, 1)
  }
  if (addCalendarDays(pointStart, -1) !== expectedEnd) return null
  return {
    key: expectedKey,
    startDate: expectedStart,
    endDate: expectedEnd,
    points: points
  }
}

function parseActivityTrends(raw) {
  var text = String(raw || "")
  if (text.length === 0) return { ok: false, error: "missing" }
  if (text.length > MAX_ACTIVITY_TRENDS_CHARS) return { ok: false, error: "too_large" }
  var source
  try {
    source = JSON.parse(text)
  } catch (error) {
    return { ok: false, error: "invalid_json" }
  }
  if (!hasOnlyKeys(source, ["schemaVersion", "generatedAt", "asOfLocalDate", "periods"])
      || source.schemaVersion !== ACTIVITY_TRENDS_SCHEMA_VERSION
      || !validTimestamp(source.generatedAt) || !validDate(source.asOfLocalDate)
      || !Array.isArray(source.periods) || source.periods.length !== TREND_PERIOD_KEYS.length)
    return { ok: false, error: "invalid_schema" }

  var periods = []
  for (var i = 0; i < TREND_PERIOD_KEYS.length; i++) {
    var period = normalizeTrendPeriod(
      source.periods[i], TREND_PERIOD_KEYS[i], source.asOfLocalDate,
      TREND_PERIOD_DAYS[i], TREND_POINT_COUNTS[i])
    if (!period) return { ok: false, error: "invalid_period" }
    periods.push(period)
  }
  return {
    ok: true,
    trends: {
      schemaVersion: ACTIVITY_TRENDS_SCHEMA_VERSION,
      generatedAt: source.generatedAt,
      generatedMs: Date.parse(source.generatedAt),
      asOfLocalDate: source.asOfLocalDate,
      periods: periods
    }
  }
}

function optionalWellnessNumber(value, maximum, integerOnly, minimum) {
  if (value === null) return true
  if (!isFiniteNumber(value) || value > maximum || value < minimum) return false
  return !integerOnly || isInteger(value)
}

function normalizeWellnessGroup(source, keys, limits, textKeys) {
  if (source === null) return null
  if (!hasOnlyKeys(source, keys)) return undefined
  var result = {}
  var present = false
  for (var i = 0; i < keys.length; i++) {
    var key = keys[i]
    var value = source[key]
    if (textKeys.indexOf(key) !== -1) {
      if (!validDisplayText(value, 64, true)) return undefined
    } else {
      var limit = limits[key]
      if (!optionalWellnessNumber(value, limit[1], limit[2], limit[0])) return undefined
    }
    if (value !== null) present = true
    result[key] = value
  }
  return present ? result : undefined
}

function normalizeWellnessDay(source, expectedDate) {
  if (!hasOnlyKeys(source, [
      "date", "steps", "bodyBattery", "sleep", "trainingReadiness", "hrv",
      "restingHeartRate"
    ]) || source.date !== expectedDate) return null
  var steps = normalizeWellnessGroup(source.steps, ["value", "goal"], {
    value: [0, 1000000, true], goal: [0, 1000000, true]
  }, [])
  var bodyBattery = normalizeWellnessGroup(source.bodyBattery, [
    "charged", "drained", "lowest", "highest", "latest"
  ], {
    charged: [0, 1000, true], drained: [0, 1000, true], lowest: [0, 100, true],
    highest: [0, 100, true], latest: [0, 100, true]
  }, [])
  var sleep = normalizeWellnessGroup(source.sleep, [
    "score", "totalSeconds", "deepSeconds", "lightSeconds", "remSeconds", "awakeSeconds"
  ], {
    score: [0, 100, true], totalSeconds: [0, 86400, true], deepSeconds: [0, 86400, true],
    lightSeconds: [0, 86400, true], remSeconds: [0, 86400, true], awakeSeconds: [0, 86400, true]
  }, [])
  var readiness = normalizeWellnessGroup(source.trainingReadiness, ["score", "level"], {
    score: [0, 100, true]
  }, ["level"])
  var hrv = normalizeWellnessGroup(source.hrv, [
    "weeklyAverageMs", "lastNightAverageMs", "status", "balancedLowMs", "balancedUpperMs"
  ], {
    weeklyAverageMs: [0, 1000, false], lastNightAverageMs: [0, 1000, false],
    balancedLowMs: [0, 1000, false], balancedUpperMs: [0, 1000, false]
  }, ["status"])
  var resting = normalizeWellnessGroup(source.restingHeartRate, ["beatsPerMinute"], {
    beatsPerMinute: [20, 300, true]
  }, [])
  if (steps === undefined || bodyBattery === undefined || sleep === undefined
      || readiness === undefined || hrv === undefined || resting === undefined) return null
  if (bodyBattery && bodyBattery.lowest !== null && bodyBattery.highest !== null
      && bodyBattery.lowest > bodyBattery.highest) return null
  if (sleep && Number(sleep.deepSeconds || 0) + Number(sleep.lightSeconds || 0)
      + Number(sleep.remSeconds || 0) + Number(sleep.awakeSeconds || 0) > 86400) return null
  if (hrv && hrv.balancedLowMs !== null && hrv.balancedUpperMs !== null
      && hrv.balancedLowMs > hrv.balancedUpperMs) return null
  return {
    date: expectedDate,
    steps: steps,
    bodyBattery: bodyBattery,
    sleep: sleep,
    trainingReadiness: readiness,
    hrv: hrv,
    restingHeartRate: resting
  }
}

function normalizeWellnessCountGroup(source, keys, maximum) {
  if (!hasOnlyKeys(source, keys)) return null
  var result = {}
  for (var i = 0; i < keys.length; i++) {
    if (!isInteger(source[keys[i]]) || source[keys[i]] > maximum) return null
    result[keys[i]] = source[keys[i]]
  }
  return result
}

function normalizeWellnessCounts(source, maximum) {
  if (!hasOnlyKeys(source, [
      "steps", "bodyBattery", "sleep", "trainingReadiness", "hrv", "restingHeartRate"
    ])) return null
  var result = {
    steps: normalizeWellnessCountGroup(source.steps, ["value", "goal"], maximum),
    bodyBattery: normalizeWellnessCountGroup(source.bodyBattery, [
      "charged", "drained", "lowest", "highest", "latest"
    ], maximum),
    sleep: normalizeWellnessCountGroup(source.sleep, [
      "score", "totalSeconds", "deepSeconds", "lightSeconds", "remSeconds", "awakeSeconds"
    ], maximum),
    trainingReadiness: normalizeWellnessCountGroup(
      source.trainingReadiness, ["score", "level"], maximum),
    hrv: normalizeWellnessCountGroup(source.hrv, [
      "weeklyAverageMs", "lastNightAverageMs", "status", "balancedLowMs", "balancedUpperMs"
    ], maximum),
    restingHeartRate: normalizeWellnessCountGroup(
      source.restingHeartRate, ["beatsPerMinute"], maximum)
  }
  for (var key in result) if (!result[key]) return null
  return result
}

function wellnessCountsForDays(days, startIndex) {
  var result = {
    steps: { value: 0, goal: 0 },
    bodyBattery: { charged: 0, drained: 0, lowest: 0, highest: 0, latest: 0 },
    sleep: { score: 0, totalSeconds: 0, deepSeconds: 0, lightSeconds: 0, remSeconds: 0, awakeSeconds: 0 },
    trainingReadiness: { score: 0, level: 0 },
    hrv: { weeklyAverageMs: 0, lastNightAverageMs: 0, status: 0, balancedLowMs: 0, balancedUpperMs: 0 },
    restingHeartRate: { beatsPerMinute: 0 }
  }
  for (var i = startIndex; i < days.length; i++) {
    var day = days[i]
    for (var group in result) {
      if (day[group] === null) continue
      for (var key in result[group]) if (day[group][key] !== null) result[group][key]++
    }
  }
  return result
}

function latestWellnessValueDate(source, days) {
  for (var i = days.length - 1; i >= 0; i--) {
    var day = days[i]
    if (source === "user_summary" && (day.steps !== null || day.restingHeartRate !== null))
      return day.date
    if (source === "steps" && day.steps !== null && day.steps.value !== null) return day.date
    if (source === "body_battery" && day.bodyBattery !== null) return day.date
    if (source === "sleep" && day.sleep !== null) return day.date
    if (source === "hrv" && day.hrv !== null) return day.date
    if (source === "resting_heart_rate" && day.restingHeartRate !== null) return day.date
    if (source === "training_readiness" && day.trainingReadiness !== null) return day.date
  }
  return null
}

function normalizeWellnessSource(source, expectedSource, days, generatedMs) {
  if (!hasOnlyKeys(source, ["source", "refreshedAt", "latestValueDate", "failure"])
      || source.source !== expectedSource
      || (source.refreshedAt !== null && !validTimestamp(source.refreshedAt))
      || (source.refreshedAt !== null && Date.parse(source.refreshedAt) > generatedMs)
      || (source.latestValueDate !== null && !validDate(source.latestValueDate))
      || source.latestValueDate !== latestWellnessValueDate(expectedSource, days)
      || (source.failure !== null && WELLNESS_FAILURE_KEYS.indexOf(source.failure) === -1)) return null
  return {
    source: expectedSource,
    refreshedAt: source.refreshedAt,
    refreshedMs: source.refreshedAt === null ? 0 : Date.parse(source.refreshedAt),
    latestValueDate: source.latestValueDate,
    failure: source.failure
  }
}

function parseWellness(raw) {
  var text = String(raw || "")
  if (text.length === 0) return { ok: false, error: "missing" }
  if (text.length > MAX_WELLNESS_CHARS) return { ok: false, error: "too_large" }
  var source
  try {
    source = JSON.parse(text)
  } catch (error) {
    return { ok: false, error: "invalid_json" }
  }
  if (!hasOnlyKeys(source, [
      "schemaVersion", "generatedAt", "asOfLocalDate", "collectionEnabled",
      "partialCurrentDaySources", "sources", "periods", "days"
    ]) || source.schemaVersion !== WELLNESS_SCHEMA_VERSION || !validTimestamp(source.generatedAt)
      || !validDate(source.asOfLocalDate) || typeof source.collectionEnabled !== "boolean"
      || !Array.isArray(source.partialCurrentDaySources)
      || JSON.stringify(source.partialCurrentDaySources) !== JSON.stringify(["steps", "bodyBattery"])
      || !Array.isArray(source.days) || source.days.length !== 30
      || !Array.isArray(source.sources) || source.sources.length !== WELLNESS_SOURCE_KEYS.length
      || !Array.isArray(source.periods) || source.periods.length !== WELLNESS_PERIOD_KEYS.length)
    return { ok: false, error: "invalid_schema" }

  var days = []
  var expectedDate = addCalendarDays(source.asOfLocalDate, -29)
  for (var i = 0; i < source.days.length; i++) {
    var day = normalizeWellnessDay(source.days[i], expectedDate)
    if (!day) return { ok: false, error: "invalid_day" }
    days.push(day)
    expectedDate = addCalendarDays(expectedDate, 1)
  }

  var periods = []
  for (var periodIndex = 0; periodIndex < source.periods.length; periodIndex++) {
    var periodDays = WELLNESS_PERIOD_DAYS[periodIndex]
    var period = source.periods[periodIndex]
    var counts = period && normalizeWellnessCounts(period.contributingDays, periodDays)
    if (!hasOnlyKeys(period, ["key", "startDate", "endDate", "contributingDays"])
        || period.key !== WELLNESS_PERIOD_KEYS[periodIndex]
        || period.startDate !== addCalendarDays(source.asOfLocalDate, 1 - periodDays)
        || period.endDate !== source.asOfLocalDate || !counts
        || JSON.stringify(counts) !== JSON.stringify(wellnessCountsForDays(days, 30 - periodDays)))
      return { ok: false, error: "invalid_period" }
    periods.push({
      key: period.key,
      startDate: period.startDate,
      endDate: period.endDate,
      contributingDays: counts
    })
  }

  var generatedMs = Date.parse(source.generatedAt)
  var sources = []
  for (var sourceIndex = 0; sourceIndex < source.sources.length; sourceIndex++) {
    var normalizedSource = normalizeWellnessSource(
      source.sources[sourceIndex], WELLNESS_SOURCE_KEYS[sourceIndex], days, generatedMs)
    if (!normalizedSource) return { ok: false, error: "invalid_source" }
    sources.push(normalizedSource)
  }
  return {
    ok: true,
    wellness: {
      schemaVersion: WELLNESS_SCHEMA_VERSION,
      generatedAt: source.generatedAt,
      generatedMs: generatedMs,
      asOfLocalDate: source.asOfLocalDate,
      collectionEnabled: source.collectionEnabled,
      partialCurrentDaySources: ["steps", "bodyBattery"],
      sources: sources,
      periods: periods,
      days: days
    }
  }
}

function wellnessSummaryDateMatches(wellness, summary) {
  return wellness !== null && summary !== null
    && wellness.asOfLocalDate === summary.asOfLocalDate
}

function wellnessSourceByKey(wellness, key) {
  if (!wellness || !Array.isArray(wellness.sources)) return null
  for (var i = 0; i < wellness.sources.length; i++)
    if (wellness.sources[i].source === key) return wellness.sources[i]
  return null
}

function wellnessSourceStale(source, nowMs, maximumAgeMs) {
  if (!source || !isFiniteNumber(nowMs) || !isFiniteNumber(maximumAgeMs)
      || source.refreshedMs <= 0) return true
  return Math.max(0, nowMs - source.refreshedMs) > maximumAgeMs
}

function wellnessCategoryDefinition(key) {
  var definitions = {
    trainingReadiness: {
      label: "Training Readiness", group: "trainingReadiness",
      sources: ["training_readiness"]
    },
    bodyBattery: {
      label: "Body Battery", group: "bodyBattery", sources: ["body_battery"]
    },
    sleep: { label: "Sleep", group: "sleep", sources: ["sleep"] },
    steps: {
      label: "Steps", group: "steps", sources: ["user_summary", "steps"]
    },
    hrv: { label: "HRV", group: "hrv", sources: ["hrv"] },
    restingHeartRate: {
      label: "Resting heart rate", group: "restingHeartRate",
      sources: ["user_summary", "resting_heart_rate"]
    }
  }
  return definitions[key] || null
}

function latestWellnessDay(wellness, categoryKey) {
  var definition = wellnessCategoryDefinition(categoryKey)
  if (!wellness || !definition || !Array.isArray(wellness.days)) return null
  for (var index = wellness.days.length - 1; index >= 0; index--)
    if (wellness.days[index][definition.group] !== null) return wellness.days[index]
  return null
}

function wellnessSourceForCategory(wellness, categoryKey, valueDate) {
  var definition = wellnessCategoryDefinition(categoryKey)
  if (!wellness || !definition) return null
  var best = null
  for (var index = 0; index < definition.sources.length; index++) {
    var candidate = wellnessSourceByKey(wellness, definition.sources[index])
    if (!candidate || (valueDate && candidate.latestValueDate !== valueDate)) continue
    if (!best || candidate.refreshedMs > best.refreshedMs
        || (candidate.refreshedMs === best.refreshedMs
          && best.failure !== null && candidate.failure === null)) best = candidate
  }
  if (best || !valueDate) return best
  return wellnessSourceForCategory(wellness, categoryKey, null)
}

function wellnessFailureText(failure) {
  if (failure === "authentication") return "Garmin sign-in is required"
  if (failure === "rate_limit") return "Garmin rate limit reached"
  if (failure === "offline_transport") return "Garmin was unreachable"
  if (failure === "remote_service") return "Garmin service failed"
  if (failure === "invalid_data") return "Garmin returned invalid data"
  if (failure === "local_storage") return "Local wellness storage failed"
  if (failure === "unsupported") return "Not supported by this Garmin account or device"
  return ""
}

function wellnessUnavailableReason(wellness, categoryKey) {
  var definition = wellnessCategoryDefinition(categoryKey)
  if (!definition) return "No retained value is available"
  if (!wellness) return "No local wellness summary is available"
  var failures = []
  for (var index = 0; index < definition.sources.length; index++) {
    var source = wellnessSourceByKey(wellness, definition.sources[index])
    if (source && source.failure !== null) failures.push(source.failure)
  }
  if (failures.length === definition.sources.length) {
    if (failures.indexOf("unsupported") !== -1
        && failures.every(function(failure) { return failure === "unsupported" }))
      return wellnessFailureText("unsupported")
    return wellnessFailureText(failures[0]) + "; no retained value"
  }
  if (wellness.collectionEnabled === false)
    return "Collection is off and no retained value is available"
  return "No value is recorded in the retained 30 days"
}

function wellnessCacheReadError(hasWellness, currentError, resultError) {
  if (resultError === "cache_missing")
    return hasWellness ? String(currentError || "") : "missing"
  return typeof resultError === "string" && resultError !== ""
    ? resultError : "local_storage_error"
}

function parseDisplayCacheEnvelope(raw, expectedKind) {
  var maxContent = expectedKind === "summary" ? MAX_SUMMARY_CHARS
    : expectedKind === "activity-trends" ? MAX_ACTIVITY_TRENDS_CHARS
    : expectedKind === "wellness" ? MAX_WELLNESS_CHARS : 0
  if (maxContent === 0) return { ok: false, error: "invalid_kind" }

  var text = String(raw || "")
  if (text.length === 0) return { ok: false, error: "invalid_envelope" }
  if (text.length > maxContent * 2 + 4096) return { ok: false, error: "too_large" }

  var envelope
  try {
    envelope = JSON.parse(text)
  } catch (error) {
    return { ok: false, error: "invalid_json" }
  }
  if (!hasOnlyKeys(envelope, ["schemaVersion", "command", "ok", "data", "error"])
      || envelope.schemaVersion !== 1 || envelope.command !== "cache.read"
      || typeof envelope.ok !== "boolean") return { ok: false, error: "invalid_envelope" }
  if (!envelope.ok) {
    if (envelope.data !== null || !hasOnlyKeys(envelope.error, ["code", "message"])
        || ["cache_missing", "local_storage_error"].indexOf(envelope.error.code) === -1)
      return { ok: false, error: "invalid_envelope" }
    return { ok: false, error: envelope.error.code }
  }
  if (envelope.error !== null || !hasOnlyKeys(envelope.data, ["kind", "content"])
      || envelope.data.kind !== expectedKind || typeof envelope.data.content !== "string"
      || envelope.data.content.length > maxContent)
    return { ok: false, error: "invalid_envelope" }

  var result = expectedKind === "summary" ? parseSummary(envelope.data.content)
    : expectedKind === "activity-trends" ? parseActivityTrends(envelope.data.content)
    : parseWellness(envelope.data.content)
  result.kind = expectedKind
  return result
}

function summaryCacheReadError(hasSummary, currentError, resultError) {
  if (resultError === "cache_missing")
    return hasSummary ? String(currentError || "") : "missing"
  return typeof resultError === "string" && resultError !== ""
    ? resultError : "local_storage_error"
}

function trendMetricMatchesSummary(period, summaryMetric, key) {
  var contributors = 0
  var total = 0
  for (var i = 0; i < period.points.length; i++) {
    var metric = period.points[i][key]
    contributors += metric.contributingActivityCount
    if (metric.contributingActivityCount > 0) total += metric.value
  }
  if (contributors !== summaryMetric.contributingActivityCount) return false
  if (contributors === 0) return summaryMetric.value === null
  var tolerance = Math.max(1, Math.abs(summaryMetric.value)) * 1e-9
  return Math.abs(total - summaryMetric.value) <= tolerance
}

function trendsForSummary(trends, summary) {
  if (!trends || !summary || trends.generatedAt !== summary.generatedAt
      || trends.asOfLocalDate !== summary.asOfLocalDate) return null
  var metricKeys = ["durationSeconds", "distanceMetres", "elevationGainMetres", "energyJoules"]
  for (var i = 0; i < trends.periods.length; i++) {
    var trendPeriod = trends.periods[i]
    var summaryPeriod = periodByKey(summary, trendPeriod.key)
    if (!summaryPeriod || summaryPeriod.startDate !== trendPeriod.startDate
        || summaryPeriod.endDate !== trendPeriod.endDate) return null
    var activityCount = 0
    for (var pointIndex = 0; pointIndex < trendPeriod.points.length; pointIndex++)
      activityCount += trendPeriod.points[pointIndex].activityCount
    if (activityCount !== summaryPeriod.overall.activityCount) return null
    for (var metricIndex = 0; metricIndex < metricKeys.length; metricIndex++) {
      var key = metricKeys[metricIndex]
      if (!trendMetricMatchesSummary(trendPeriod, summaryPeriod.overall[key], key)) return null
    }
  }
  return trends
}

function trendByKey(trends, key) {
  if (!trends || !Array.isArray(trends.periods)) return null
  for (var i = 0; i < trends.periods.length; i++)
    if (trends.periods[i].key === key) return trends.periods[i]
  return null
}

function trendDurationPeak(period) {
  if (!period || !Array.isArray(period.points)) return 0
  var peak = 0
  for (var i = 0; i < period.points.length; i++) {
    var value = period.points[i].durationSeconds.value
    if (value !== null) peak = Math.max(peak, value)
  }
  return peak
}

function typeActivityShare(period, activityCount) {
  if (!period || !Array.isArray(period.byType) || !isFiniteNumber(activityCount)) return 0
  var peak = 0
  for (var i = 0; i < period.byType.length; i++)
    peak = Math.max(peak, Number(period.byType[i].activityCount || 0))
  return peak > 0 ? Math.max(0, Math.min(1, activityCount / peak)) : 0
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

function dateDaysAgo(generated, days) {
  var value = new Date(generated.getTime())
  value.setUTCDate(value.getUTCDate() - days)
  return value.toISOString().slice(0, 10)
}

function syntheticSummaryTotal(records, key) {
  var total = 0
  var contributors = 0
  for (var i = 0; i < records.length; i++) {
    if (records[i][key] === null) continue
    total += records[i][key]
    contributors++
  }
  return {
    value: contributors > 0 ? total : null,
    contributingActivityCount: contributors
  }
}

function syntheticSummaryMaximum(records, key) {
  var maximum = null
  var contributors = 0
  for (var i = 0; i < records.length; i++) {
    if (records[i][key] === null) continue
    maximum = maximum === null ? records[i][key] : Math.max(maximum, records[i][key])
    contributors++
  }
  return { value: maximum, contributingActivityCount: contributors }
}

function syntheticSummaryWeighted(records, valueKey, weightKey) {
  var weightedTotal = 0
  var totalWeight = 0
  var contributors = 0
  for (var i = 0; i < records.length; i++) {
    var value = records[i][valueKey]
    var weight = records[i][weightKey]
    if (value === null || weight === null || weight <= 0) continue
    weightedTotal += value * weight
    totalWeight += weight
    contributors++
  }
  return {
    value: contributors > 0 ? weightedTotal / totalWeight : null,
    contributingActivityCount: contributors
  }
}

function syntheticSummaryAggregate(records) {
  return {
    activityCount: records.length,
    durationSeconds: syntheticSummaryTotal(records, "durationSeconds"),
    movingDurationSeconds: syntheticSummaryTotal(records, "movingDurationSeconds"),
    distanceMetres: syntheticSummaryTotal(records, "distanceMetres"),
    elevationGainMetres: syntheticSummaryTotal(records, "elevationGainMetres"),
    energyJoules: syntheticSummaryTotal(records, "energyJoules"),
    averageHeartRateBpm: syntheticSummaryWeighted(records, "averageHeartRateBpm", "durationSeconds"),
    maximumHeartRateBpm: syntheticSummaryMaximum(records, "maximumHeartRateBpm"),
    averageSpeedMetresPerSecond: syntheticSummaryWeighted(
      records, "averageSpeedMetresPerSecond", "movingDurationSeconds"),
    averagePowerWatts: syntheticSummaryWeighted(records, "averagePowerWatts", "durationSeconds"),
    totalSets: syntheticSummaryTotal(records, "totalSets"),
    totalRepetitions: syntheticSummaryTotal(records, "totalRepetitions")
  }
}

function syntheticSummaryPeriod(records, key, startDate, endDate) {
  var matching = records.filter(function(activity) {
    return activity.localDate >= startDate && activity.localDate <= endDate
  })
  var groups = {}
  for (var i = 0; i < matching.length; i++) {
    var typeKey = matching[i].typeKey
    if (!groups[typeKey]) groups[typeKey] = []
    groups[typeKey].push(matching[i])
  }
  var byType = Object.keys(groups).map(function(typeKey) {
    var aggregate = syntheticSummaryAggregate(groups[typeKey])
    aggregate.typeKey = typeKey
    return aggregate
  })
  byType.sort(function(a, b) {
    if (a.activityCount !== b.activityCount) return b.activityCount - a.activityCount
    return a.typeKey < b.typeKey ? -1 : (a.typeKey > b.typeKey ? 1 : 0)
  })
  return {
    key: key,
    startDate: startDate,
    endDate: endDate,
    overall: syntheticSummaryAggregate(matching),
    byType: byType
  }
}

function syntheticSummary(nowMs) {
  var generated = new Date(nowMs || Date.now())
  generated.setUTCMilliseconds(0)
  var today = dateDaysAgo(generated, 0)
  var records = syntheticActivityRecords(today)
  return {
    schemaVersion: SUMMARY_SCHEMA_VERSION,
    generatedAt: generated.toISOString().replace(".000Z", "Z"),
    generatedMs: generated.getTime(),
    asOfLocalDate: today,
    periods: [
      syntheticSummaryPeriod(records, "today", today, today),
      syntheticSummaryPeriod(records, "7Days", dateDaysAgo(generated, 6), today),
      syntheticSummaryPeriod(records, "30Days", dateDaysAgo(generated, 29), today),
      syntheticSummaryPeriod(records, "90Days", dateDaysAgo(generated, 89), today)
    ]
  }
}

function syntheticWellness(nowMs, requestedVariant) {
  var generated = new Date(nowMs || Date.now())
  generated.setUTCMilliseconds(0)
  var generatedAt = generated.toISOString().replace(".000Z", "Z")
  var today = dateDaysAgo(generated, 0)
  var variant = ["complete", "sparse", "unsupported", "stale", "partial"].indexOf(
    requestedVariant) === -1 ? "complete" : requestedVariant
  var days = []
  for (var offset = 29; offset >= 0; offset--) {
    days.push({
      date: dateDaysAgo(generated, offset), steps: null, bodyBattery: null,
      sleep: null, trainingReadiness: null, hrv: null, restingHeartRate: null
    })
  }
  var valueIndex = variant === "stale" || variant === "partial" ? 28 : 29
  var valueDay = days[valueIndex]
  if (variant === "complete" || variant === "stale" || variant === "partial") {
    valueDay.sleep = {
      score: 84, totalSeconds: 27000, deepSeconds: 4500, lightSeconds: 15000,
      remSeconds: 6000, awakeSeconds: 1500
    }
    valueDay.trainingReadiness = { score: 71, level: "Synthetic high" }
    valueDay.hrv = {
      weeklyAverageMs: 48.5, lastNightAverageMs: 52, status: "Synthetic balanced",
      balancedLowMs: 40, balancedUpperMs: 60
    }
    valueDay.restingHeartRate = { beatsPerMinute: 54 }
  }
  if (variant !== "unsupported") {
    days[29].steps = { value: variant === "sparse" ? 0 : 6420, goal: 8000 }
    days[29].bodyBattery = variant === "sparse" ? null : {
      charged: 42, drained: 31, lowest: 28, highest: 76, latest: 64
    }
  }
  if (variant === "sparse") days[29].sleep = {
    score: 84, totalSeconds: null, deepSeconds: null, lightSeconds: null,
    remSeconds: null, awakeSeconds: null
  }

  var failures = {}
  if (variant === "unsupported") {
    for (var unsupportedIndex = 0; unsupportedIndex < WELLNESS_SOURCE_KEYS.length;
        unsupportedIndex++) failures[WELLNESS_SOURCE_KEYS[unsupportedIndex]] = "unsupported"
  } else if (variant === "stale") failures.sleep = "remote_service"

  var sources = WELLNESS_SOURCE_KEYS.map(function(key, index) {
    var refreshed = new Date(generated.getTime() - (index + 1) * 60000)
    if (variant === "stale") refreshed = new Date(generated.getTime() - 36 * 3600000)
    if (variant === "unsupported") refreshed = null
    return {
      source: key,
      refreshedAt: refreshed ? refreshed.toISOString().replace(".000Z", "Z") : null,
      latestValueDate: latestWellnessValueDate(key, days),
      failure: failures[key] || null
    }
  })
  return {
    schemaVersion: WELLNESS_SCHEMA_VERSION,
    generatedAt: generatedAt,
    asOfLocalDate: today,
    collectionEnabled: true,
    partialCurrentDaySources: ["steps", "bodyBattery"],
    sources: sources,
    periods: [
      {
        key: "7Days", startDate: addCalendarDays(today, -6), endDate: today,
        contributingDays: wellnessCountsForDays(days, 23)
      },
      {
        key: "30Days", startDate: addCalendarDays(today, -29), endDate: today,
        contributingDays: wellnessCountsForDays(days, 0)
      }
    ],
    days: days
  }
}

function syntheticTrendMetric(records, key) {
  if (records.length === 0) return { value: 0, contributingActivityCount: 0 }
  var total = 0
  var contributors = 0
  for (var i = 0; i < records.length; i++) {
    if (records[i][key] === null) continue
    total += records[i][key]
    contributors++
  }
  return {
    value: contributors > 0 ? total : null,
    contributingActivityCount: contributors
  }
}

function syntheticTrendPoint(records, startDate, endDate, partial) {
  var matching = records.filter(function(activity) {
    return activity.localDate >= startDate && activity.localDate <= endDate
  })
  return {
    startDate: startDate,
    endDate: endDate,
    partial: partial,
    activityCount: matching.length,
    durationSeconds: syntheticTrendMetric(matching, "durationSeconds"),
    distanceMetres: syntheticTrendMetric(matching, "distanceMetres"),
    elevationGainMetres: syntheticTrendMetric(matching, "elevationGainMetres"),
    energyJoules: syntheticTrendMetric(matching, "energyJoules")
  }
}

function syntheticTrendPeriod(records, key, asOfDate, days) {
  var startDate = addCalendarDays(asOfDate, 1 - days)
  var points = []
  var pointStart = startDate
  var index = 0
  while (pointStart <= asOfDate) {
    var span = key === "90Days" ? (index === 0 ? 6 : 7) : 1
    var pointEnd = addCalendarDays(pointStart, span - 1)
    points.push(syntheticTrendPoint(records, pointStart, pointEnd, pointEnd === asOfDate))
    pointStart = addCalendarDays(pointEnd, 1)
    index++
  }
  return { key: key, startDate: startDate, endDate: asOfDate, points: points }
}

function syntheticActivityTrends(nowMs) {
  var generated = new Date(nowMs || Date.now())
  generated.setUTCMilliseconds(0)
  var asOfDate = dateDaysAgo(generated, 0)
  var records = syntheticActivityRecords(asOfDate)
  return {
    schemaVersion: ACTIVITY_TRENDS_SCHEMA_VERSION,
    generatedAt: generated.toISOString().replace(".000Z", "Z"),
    asOfLocalDate: asOfDate,
    periods: [
      syntheticTrendPeriod(records, "7Days", asOfDate, 7),
      syntheticTrendPeriod(records, "30Days", asOfDate, 30),
      syntheticTrendPeriod(records, "90Days", asOfDate, 90)
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
