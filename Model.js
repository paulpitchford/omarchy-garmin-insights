.pragma library

var SUMMARY_SCHEMA_VERSION = 1
var MAX_SUMMARY_CHARS = 1048576
var MAX_ACTIVITY_COUNT = 20000
var MAX_TYPES = 256
var PERIOD_KEYS = ["today", "7Days", "30Days", "90Days"]
var PERIOD_DAYS = [1, 7, 30, 90]
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
    if (typeof source.typeKey !== "string" || source.typeKey.length < 1 || source.typeKey.length > 100)
      return null
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
