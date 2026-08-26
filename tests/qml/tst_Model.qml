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
