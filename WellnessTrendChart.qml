pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

Column {
  id: root

  property var wellness: null
  property string familyKey: "trainingReadiness"
  property int periodDays: 7
  property string sleepMetric: "score"
  property int selectedIndex: 6
  property bool cursorActive: false
  property color foreground: Color.foreground
  property color dim: Qt.darker(foreground, 1.5)
  property string fontFamily: Style.font.family

  readonly property var period: Model.wellnessPeriodByDays(wellness, periodDays)
  readonly property var points: Model.wellnessTrendDays(wellness, periodDays)
  readonly property int boundedSelectedIndex: Math.max(0,
    Math.min(points.length - 1, selectedIndex))
  readonly property string chartKind: familyKey === "bodyBattery" ? "range"
    : familyKey === "sleep" && sleepMetric === "stages" ? "stages"
    : familyKey === "steps" || (familyKey === "sleep" && sleepMetric !== "stages")
      ? "bars" : "line"
  readonly property real minimumValue: chartMinimum()
  readonly property real maximumValue: chartMaximum()
  readonly property int contributorCount: Model.wellnessTrendContributorCount(
    wellness, periodDays, familyKey, sleepMetric)
  readonly property bool currentDayPartial: Model.wellnessTrendIsPartial(
    wellness, familyKey) && points.length > 0 && groupForPoint(points[points.length - 1]) !== null
  readonly property bool hasValues: valuePointCount() > 0
  readonly property bool hasGoals: contextPointCount("goal") > 0
  readonly property bool hasBaselines: contextPointCount("baseline") > 0
  readonly property string selectedDetailText: points.length > 0
    ? pointTooltip(points[boundedSelectedIndex]) : "No retained wellness dates are available"

  signal pointRequested(int index)
  signal pointHovered(int index)

  function alpha(color, opacity) {
    return Qt.rgba(color.r, color.g, color.b, opacity)
  }

  function familyLabel() {
    if (familyKey === "trainingReadiness") return "Training Readiness"
    if (familyKey === "bodyBattery") return "Body Battery"
    if (familyKey === "sleep") return "Sleep"
    if (familyKey === "steps") return "Steps"
    if (familyKey === "hrv") return "HRV"
    return "Resting heart rate"
  }

  function metricLabel() {
    if (familyKey !== "sleep") return familyLabel()
    if (sleepMetric === "duration") return "Sleep duration"
    if (sleepMetric === "stages") return "Sleep stages"
    return "Sleep score"
  }

  function shortDate(value) {
    if (typeof value !== "string" || value.length !== 10) return ""
    return Qt.formatDate(new Date(value + "T12:00:00"), "d MMM")
  }

  function fullDate(value) {
    if (typeof value !== "string" || value.length !== 10) return "Date unavailable"
    return Qt.formatDate(new Date(value + "T12:00:00"), "dddd d MMMM yyyy")
  }

  function rangeDate(value) {
    if (typeof value !== "string" || value.length !== 10) return "Date unavailable"
    return Qt.formatDate(new Date(value + "T12:00:00"), "d MMM yyyy")
  }

  function groupForPoint(point) {
    if (!point) return null
    if (familyKey === "trainingReadiness") return point.trainingReadiness
    if (familyKey === "bodyBattery") return point.bodyBattery
    if (familyKey === "sleep") return point.sleep
    if (familyKey === "steps") return point.steps
    if (familyKey === "hrv") return point.hrv
    return point.restingHeartRate
  }

  function primaryValue(point) {
    var group = groupForPoint(point)
    if (!group) return null
    if (familyKey === "trainingReadiness") return group.score
    if (familyKey === "bodyBattery") return group.latest
    if (familyKey === "sleep") {
      if (sleepMetric === "duration" || sleepMetric === "stages") return group.totalSeconds
      return group.score
    }
    if (familyKey === "steps") return group.value
    if (familyKey === "hrv") return group.lastNightAverageMs
    return group.beatsPerMinute
  }

  function stageTotal(point) {
    var sleep = point ? point.sleep : null
    if (!sleep) return null
    var found = false
    var total = 0
    var keys = ["deepSeconds", "lightSeconds", "remSeconds", "awakeSeconds"]
    for (var index = 0; index < keys.length; index++) {
      if (sleep[keys[index]] === null) continue
      found = true
      total += sleep[keys[index]]
    }
    return found ? total : null
  }

  function pointHasValue(point) {
    if (familyKey === "bodyBattery") {
      var battery = groupForPoint(point)
      return battery !== null && (battery.lowest !== null || battery.highest !== null
        || battery.latest !== null)
    }
    if (familyKey === "sleep" && sleepMetric === "stages")
      return stageTotal(point) !== null
    return primaryValue(point) !== null
  }

  function valuePointCount() {
    var count = 0
    for (var index = 0; index < points.length; index++)
      if (pointHasValue(points[index])) count++
    return count
  }

  function contextPointCount(kind) {
    var count = 0
    for (var index = 0; index < points.length; index++) {
      var group = groupForPoint(points[index])
      if (kind === "goal" && familyKey === "steps" && group && group.goal !== null) count++
      if (kind === "baseline" && familyKey === "hrv" && group
          && group.balancedLowMs !== null && group.balancedUpperMs !== null) count++
    }
    return count
  }

  function chartMinimum() {
    if (familyKey !== "hrv" && familyKey !== "restingHeartRate") return 0
    var minimum = null
    for (var index = 0; index < points.length; index++) {
      var value = primaryValue(points[index])
      if (value !== null) minimum = minimum === null ? value : Math.min(minimum, value)
      var group = groupForPoint(points[index])
      if (familyKey === "hrv" && group && group.balancedLowMs !== null)
        minimum = minimum === null ? group.balancedLowMs : Math.min(minimum, group.balancedLowMs)
    }
    return minimum === null ? 0 : Math.max(0, minimum - Math.max(2, minimum * 0.08))
  }

  function chartMaximum() {
    if (familyKey === "trainingReadiness" || familyKey === "bodyBattery"
        || (familyKey === "sleep" && sleepMetric === "score")) return 100
    var maximum = 0
    for (var index = 0; index < points.length; index++) {
      var value = familyKey === "sleep" && sleepMetric === "stages"
        ? stageTotal(points[index]) : primaryValue(points[index])
      if (value !== null) maximum = Math.max(maximum, value)
      var group = groupForPoint(points[index])
      if (familyKey === "steps" && group && group.goal !== null)
        maximum = Math.max(maximum, group.goal)
      if (familyKey === "hrv" && group && group.balancedUpperMs !== null)
        maximum = Math.max(maximum, group.balancedUpperMs)
    }
    if (maximum <= minimumValue) return minimumValue + 1
    return maximum + (chartKind === "line" ? Math.max(1, maximum * 0.04) : 0)
  }

  function scaledY(value, height) {
    if (value === null || maximumValue <= minimumValue) return height
    var ratio = (Number(value) - minimumValue) / (maximumValue - minimumValue)
    return height * (1 - Math.max(0, Math.min(1, ratio)))
  }

  function formatNumber(value, decimals) {
    if (value === null || value === undefined) return "—"
    return Number(value).toLocaleString(Qt.locale(), "f", decimals || 0)
  }

  function formatMilliseconds(value) {
    if (value === null) return "—"
    var decimals = Math.round(value) === value ? 0 : 1
    return formatNumber(value, decimals) + " ms"
  }

  function scoreText(value) {
    return value === null ? "Score unavailable" : formatNumber(value, 0) + " / 100"
  }

  function partialForPoint(point) {
    return currentDayPartial && point && wellness && point.date === wellness.asOfLocalDate
  }

  function pointTooltip(point) {
    if (!point) return "No retained value"
    var group = groupForPoint(point)
    var values = []
    if (familyKey === "trainingReadiness" && group) {
      values.push(scoreText(group.score))
      if (group.level !== null) values.push(group.level)
    } else if (familyKey === "bodyBattery" && group) {
      if (group.lowest !== null && group.highest !== null)
        values.push("range " + group.lowest + "–" + group.highest)
      else if (group.lowest !== null) values.push("lowest " + group.lowest)
      else if (group.highest !== null) values.push("highest " + group.highest)
      if (group.latest !== null) values.push("latest " + group.latest)
      if (group.charged !== null) values.push("charged +" + group.charged)
      if (group.drained !== null) values.push("drained −" + group.drained)
    } else if (familyKey === "sleep" && group) {
      if (sleepMetric === "score") values.push(scoreText(group.score))
      else if (sleepMetric === "duration")
        values.push(group.totalSeconds === null ? "Duration unavailable"
          : Model.formatDuration(group.totalSeconds))
      else {
        if (group.deepSeconds !== null) values.push("Deep " + Model.formatDuration(group.deepSeconds))
        if (group.lightSeconds !== null) values.push("Light " + Model.formatDuration(group.lightSeconds))
        if (group.remSeconds !== null) values.push("REM " + Model.formatDuration(group.remSeconds))
        if (group.awakeSeconds !== null) values.push("Awake " + Model.formatDuration(group.awakeSeconds))
      }
    } else if (familyKey === "steps" && group) {
      if (group.value !== null) values.push(formatNumber(group.value, 0) + " steps")
      if (group.goal !== null) values.push("Garmin goal " + formatNumber(group.goal, 0))
    } else if (familyKey === "hrv" && group) {
      if (group.lastNightAverageMs !== null)
        values.push("last night " + formatMilliseconds(group.lastNightAverageMs))
      if (group.weeklyAverageMs !== null)
        values.push("7-day average " + formatMilliseconds(group.weeklyAverageMs))
      if (group.balancedLowMs !== null && group.balancedUpperMs !== null)
        values.push("Garmin baseline " + formatMilliseconds(group.balancedLowMs)
          + "–" + formatMilliseconds(group.balancedUpperMs))
      if (group.status !== null) values.push(group.status)
    } else if (familyKey === "restingHeartRate" && group
        && group.beatsPerMinute !== null) {
      values.push(formatNumber(group.beatsPerMinute, 0) + " bpm")
    }
    if (values.length === 0) values.push("No " + metricLabel().toLowerCase() + " value")
    if (partialForPoint(point)) values.push("Partial at last refresh")
    return fullDate(point.date) + " · " + values.join(" · ")
  }

  function contributorText() {
    var subject = familyKey === "bodyBattery" ? " with a latest level"
      : familyKey === "sleep" && sleepMetric === "stages" ? " with a Deep value"
      : " with a value"
    return contributorCount + (contributorCount === 1 ? " day" : " days") + subject
  }

  function contextText() {
    if (familyKey === "bodyBattery") return "Daily low–high range with latest level"
    if (familyKey === "steps") return hasGoals
      ? "Bars with supplied Garmin daily goals" : "Garmin daily goals unavailable"
    if (familyKey === "hrv") return hasBaselines
      ? "Last-night average within supplied Garmin balanced baselines"
      : "Garmin balanced baselines unavailable"
    if (familyKey === "sleep" && sleepMetric === "stages")
      return "Deep, Light, REM, and Awake shown as one daily composition"
    if (familyKey === "sleep" && sleepMetric === "duration") return "Total sleep duration"
    if (familyKey === "sleep") return "Garmin sleep score"
    if (familyKey === "trainingReadiness") return "Garmin Training Readiness score"
    return "Daily resting heart rate"
  }

  spacing: Style.space(7)

  PanelSectionHeader {
    width: parent.width
    text: root.metricLabel().toUpperCase()
    foreground: root.foreground
    fontFamily: root.fontFamily
  }

  Text {
    width: parent.width
    text: root.period
      ? root.rangeDate(root.period.startDate) + "–" + root.rangeDate(root.period.endDate)
        + " · " + root.contributorText()
        + (root.currentDayPartial ? " · Today partial at last refresh" : "")
      : "No retained period is available"
    textFormat: Text.PlainText
    color: root.dim
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
  }

  Text {
    width: parent.width
    text: root.contextText()
    textFormat: Text.PlainText
    color: root.dim
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
  }

  Item {
    id: chartArea
    width: parent.width
    height: Style.space(142)

    Rectangle {
      anchors.fill: parent
      radius: Style.cornerRadius
      color: root.alpha(root.foreground, 0.035)
    }

    Item {
      id: chartPlot
      anchors.fill: parent
      anchors.leftMargin: Style.space(5)
      anchors.rightMargin: Style.space(5)
      anchors.topMargin: Style.space(8)
      anchors.bottomMargin: Style.space(8)
      readonly property real cellWidth: width / Math.max(1, root.points.length)

      Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: Math.max(1, Style.space(1))
        color: root.alpha(root.foreground, 0.18)
      }

      Repeater {
        model: root.points

        Rectangle {
          required property var modelData
          required property int index
          visible: root.familyKey === "hrv" && modelData.hrv
            && modelData.hrv.balancedLowMs !== null
            && modelData.hrv.balancedUpperMs !== null
          x: index * chartPlot.cellWidth + Style.space(1)
          y: root.scaledY(modelData.hrv ? modelData.hrv.balancedUpperMs : null,
            chartPlot.height)
          width: Math.max(1, chartPlot.cellWidth - Style.space(2))
          height: modelData.hrv ? Math.max(1,
            root.scaledY(modelData.hrv.balancedLowMs, chartPlot.height) - y) : 0
          color: root.alpha(root.foreground, 0.11)
        }
      }

      Repeater {
        model: root.points

        Rectangle {
          required property var modelData
          required property int index
          visible: root.familyKey === "steps" && modelData.steps
            && modelData.steps.goal !== null
          x: index * chartPlot.cellWidth + Style.space(1)
          y: root.scaledY(modelData.steps ? modelData.steps.goal : null,
            chartPlot.height)
          width: Math.max(1, chartPlot.cellWidth - Style.space(2))
          height: Math.max(1, Style.space(1))
          color: root.alpha(root.foreground, 0.56)
        }
      }

      Repeater {
        model: root.points

        Item {
          id: barPoint
          required property var modelData
          required property int index
          visible: root.chartKind === "bars" && root.primaryValue(modelData) !== null
          x: index * chartPlot.cellWidth
          width: chartPlot.cellWidth
          height: chartPlot.height

          Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            width: Math.max(2, Math.min(parent.width - Style.space(2), Style.space(15)))
            height: Math.max(Style.space(2), chartPlot.height
              - root.scaledY(root.primaryValue(barPoint.modelData), chartPlot.height))
            radius: Math.min(width / 2, Style.cornerRadius)
            color: root.alpha(root.foreground, 0.62)
          }
        }
      }

      Repeater {
        model: root.points

        Item {
          id: batteryPoint
          required property var modelData
          required property int index
          visible: root.chartKind === "range" && modelData.bodyBattery !== null
          x: index * chartPlot.cellWidth
          width: chartPlot.cellWidth
          height: chartPlot.height

          Rectangle {
            visible: batteryPoint.modelData.bodyBattery.lowest !== null
              || batteryPoint.modelData.bodyBattery.highest !== null
            anchors.horizontalCenter: parent.horizontalCenter
            y: root.scaledY(batteryPoint.modelData.bodyBattery.highest !== null
              ? batteryPoint.modelData.bodyBattery.highest
              : batteryPoint.modelData.bodyBattery.lowest, parent.height)
            width: Math.max(2, Math.min(parent.width - Style.space(3), Style.space(8)))
            height: Math.max(Style.space(2),
              root.scaledY(batteryPoint.modelData.bodyBattery.lowest !== null
                ? batteryPoint.modelData.bodyBattery.lowest
                : batteryPoint.modelData.bodyBattery.highest, parent.height) - y)
            radius: width / 2
            color: root.alpha(root.foreground, 0.44)
          }

          Rectangle {
            visible: batteryPoint.modelData.bodyBattery.latest !== null
            anchors.horizontalCenter: parent.horizontalCenter
            y: root.scaledY(batteryPoint.modelData.bodyBattery.latest, parent.height) - height / 2
            width: Math.max(Style.space(4), 4)
            height: width
            radius: width / 2
            color: root.foreground
          }
        }
      }

      Repeater {
        model: root.points

        Item {
          id: stagePoint
          required property var modelData
          required property int index
          readonly property real total: Number(root.stageTotal(modelData) || 0)
          visible: root.chartKind === "stages" && total >= 0
          x: index * chartPlot.cellWidth
          width: chartPlot.cellWidth
          height: chartPlot.height

          Rectangle {
            visible: root.stageTotal(stagePoint.modelData) !== null && stagePoint.total === 0
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            width: Math.max(Style.space(4), 4)
            height: Math.max(Style.space(2), 2)
            radius: height / 2
            color: root.foreground
          }

          Column {
            id: stageStack
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            width: Math.max(2, Math.min(parent.width - Style.space(2), Style.space(15)))
            height: stagePoint.total > 0 ? Math.max(Style.space(2), chartPlot.height
              - root.scaledY(stagePoint.total, chartPlot.height)) : 0
            spacing: 0

            Repeater {
              model: [
                { value: stagePoint.modelData.sleep ? stagePoint.modelData.sleep.deepSeconds : null,
                  opacity: 0.92 },
                { value: stagePoint.modelData.sleep ? stagePoint.modelData.sleep.lightSeconds : null,
                  opacity: 0.68 },
                { value: stagePoint.modelData.sleep ? stagePoint.modelData.sleep.remSeconds : null,
                  opacity: 0.46 },
                { value: stagePoint.modelData.sleep ? stagePoint.modelData.sleep.awakeSeconds : null,
                  opacity: 0.24 }
              ]

              Rectangle {
                required property var modelData
                width: stageStack.width
                height: stagePoint.total > 0 && modelData.value !== null
                  ? stageStack.height * modelData.value / stagePoint.total : 0
                color: root.alpha(root.foreground, modelData.opacity)
              }
            }
          }
        }
      }

      Repeater {
        model: Math.max(0, root.points.length - 1)

        Item {
          id: lineSegment
          required property int index
          readonly property var firstPoint: root.points[index]
          readonly property var secondPoint: root.points[index + 1]
          readonly property var firstValue: root.primaryValue(firstPoint)
          readonly property var secondValue: root.primaryValue(secondPoint)
          readonly property real x1: chartPlot.cellWidth * (index + 0.5)
          readonly property real x2: chartPlot.cellWidth * (index + 1.5)
          readonly property real y1: root.scaledY(firstValue, chartPlot.height)
          readonly property real y2: root.scaledY(secondValue, chartPlot.height)
          visible: root.chartKind === "line" && firstValue !== null && secondValue !== null
          anchors.fill: parent

          Rectangle {
            x: lineSegment.x1
            y: lineSegment.y1 - height / 2
            width: Math.sqrt(Math.pow(lineSegment.x2 - lineSegment.x1, 2)
              + Math.pow(lineSegment.y2 - lineSegment.y1, 2))
            height: Math.max(1, Style.space(1))
            transformOrigin: Item.Left
            rotation: Math.atan2(lineSegment.y2 - lineSegment.y1,
              lineSegment.x2 - lineSegment.x1) * 180 / Math.PI
            color: root.alpha(root.foreground, 0.58)
          }
        }
      }

      Repeater {
        model: root.points

        Rectangle {
          required property var modelData
          required property int index
          visible: root.chartKind === "line" && root.primaryValue(modelData) !== null
          x: chartPlot.cellWidth * (index + 0.5) - width / 2
          y: root.scaledY(root.primaryValue(modelData), chartPlot.height) - height / 2
          width: Math.max(Style.space(4), 4)
          height: width
          radius: width / 2
          color: root.foreground
        }
      }

      Repeater {
        model: root.points

        Rectangle {
          required property var modelData
          required property int index
          visible: !root.pointHasValue(modelData)
          x: chartPlot.cellWidth * (index + 0.5) - width / 2
          anchors.bottom: parent.bottom
          anchors.bottomMargin: Style.space(2)
          width: Math.max(Style.space(4), 4)
          height: width
          radius: width / 2
          color: "transparent"
          border.width: Math.max(1, Style.space(1))
          border.color: root.dim
        }
      }

      Repeater {
        model: root.points

        CursorSurface {
          id: pointCursor
          required property var modelData
          required property int index
          x: index * chartPlot.cellWidth
          width: chartPlot.cellWidth
          height: chartPlot.height
          current: index === root.boundedSelectedIndex
          hasCursor: root.cursorActive && index === root.boundedSelectedIndex
          foreground: root.foreground
          bordered: index === root.boundedSelectedIndex
          Accessible.role: Accessible.StaticText
          Accessible.name: root.pointTooltip(modelData)

          MouseArea {
            id: pointMouse
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.NoButton
            onEntered: {
              root.pointRequested(pointCursor.index)
              root.pointHovered(pointCursor.index)
            }
          }

          PanelToolTip {
            id: pointToolTip
            visible: pointMouse.containsMouse
            text: root.pointTooltip(pointCursor.modelData)
            fontFamily: root.fontFamily
            contentItem: Text {
              text: pointToolTip.text
              textFormat: Text.PlainText
              color: pointToolTip.panelForeground
              width: Math.max(Style.space(1),
                Math.min(Style.space(420), chartArea.width - Style.space(24)))
              wrapMode: Text.WordWrap
              font.family: pointToolTip.fontFamily
              font.pixelSize: pointToolTip.fontSize
              leftPadding: Style.spacing.controlPaddingX
              rightPadding: Style.spacing.controlPaddingX
              topPadding: Style.spacing.controlPaddingY
              bottomPadding: Style.spacing.controlPaddingY
            }
          }
        }
      }
    }

    Text {
      visible: !root.hasValues
      anchors.centerIn: parent
      width: parent.width - Style.space(24)
      text: "No " + root.metricLabel().toLowerCase()
        + " values are recorded for this range. Gaps are not zero."
      textFormat: Text.PlainText
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      horizontalAlignment: Text.AlignHCenter
      wrapMode: Text.WordWrap
    }
  }

  Item {
    width: parent.width
    implicitHeight: Math.max(startLabel.implicitHeight, middleLabel.implicitHeight,
      endLabel.implicitHeight)

    Text {
      id: startLabel
      text: root.period ? root.shortDate(root.period.startDate) : ""
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      anchors.left: parent.left
    }

    Text {
      id: middleLabel
      text: root.points.length > 0
        ? root.shortDate(root.points[Math.floor((root.points.length - 1) / 2)].date) : ""
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      anchors.horizontalCenter: parent.horizontalCenter
    }

    Text {
      id: endLabel
      text: root.period ? root.shortDate(root.period.endDate) : ""
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
      anchors.right: parent.right
    }
  }

  BorderSurface {
    width: parent.width
    implicitHeight: selectedText.implicitHeight + Style.space(14)
    color: root.alpha(root.foreground, 0.025)
    borderSpec: Border.controlSpec(root.cursorActive ? "hover-cursor" : "normal",
      root.foreground, Color.accent)
    radius: Style.cornerRadius

    Text {
      id: selectedText
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.margins: Style.space(7)
      text: root.selectedDetailText
      textFormat: Text.PlainText
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      wrapMode: Text.WordWrap
    }
  }
}
