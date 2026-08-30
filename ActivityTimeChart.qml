pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

Column {
  id: root

  property var period: null
  property string metricKey: "durationSeconds"
  property bool imperial: false
  property color foreground: Color.foreground
  property color dim: Color.muted
  property string fontFamily: Style.font.family

  readonly property var points: period && Array.isArray(period.points) ? period.points : []
  readonly property var metricKeys: [
    "durationSeconds", "distanceMetres", "elevationGainMetres", "energyJoules"
  ]
  readonly property string normalizedMetricKey: metricKeys.indexOf(metricKey) === -1
    ? "durationSeconds" : metricKey
  readonly property real peakValue: metricPeak()
  readonly property int activePointCount: {
    var count = 0
    for (var i = 0; i < points.length; i++)
      if (points[i].activityCount > 0) count++
    return count
  }
  readonly property bool daily: points.length === 7 || points.length === 30
  readonly property int barGap: points.length > 20 ? Style.space(1) : Style.space(3)

  function alpha(color, opacity) {
    return Qt.rgba(color.r, color.g, color.b, opacity)
  }

  function shortDate(value) {
    if (typeof value !== "string" || value.length !== 10) return ""
    var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return String(Number(value.slice(8, 10))) + " " + months[Number(value.slice(5, 7)) - 1]
  }

  function pointDateText(point) {
    if (!point) return ""
    return point.startDate === point.endDate
      ? shortDate(point.startDate)
      : shortDate(point.startDate) + "–" + shortDate(point.endDate)
  }

  function metricLabel() {
    if (normalizedMetricKey === "distanceMetres") return "Distance"
    if (normalizedMetricKey === "elevationGainMetres") return "Elevation"
    if (normalizedMetricKey === "energyJoules") return "Energy"
    return "Time"
  }

  function metricPeak() {
    var peak = 0
    for (var index = 0; index < points.length; index++) {
      var metric = points[index][normalizedMetricKey]
      if (metric && metric.value !== null) peak = Math.max(peak, Number(metric.value))
    }
    return peak
  }

  function formatMetric(value) {
    if (normalizedMetricKey === "distanceMetres") return Model.formatDistance(value, imperial)
    if (normalizedMetricKey === "elevationGainMetres") return Model.formatElevation(value, imperial)
    if (normalizedMetricKey === "energyJoules") return Model.formatEnergy(value, imperial)
    return Model.formatDuration(value)
  }

  function pointTooltip(point) {
    if (!point || !point[normalizedMetricKey]) return ""
    var value = point[normalizedMetricKey].value
    var missingLabel = normalizedMetricKey === "durationSeconds"
      ? "duration" : metricLabel().toLowerCase()
    var metric = value === null ? "No " + missingLabel + " data" : formatMetric(value)
    var suffix = point.partial ? " · partial" : ""
    return pointDateText(point) + " · " + Model.formatCount(point.activityCount)
      + " · " + metric + suffix
  }

  function summaryText() {
    if (!period || points.length === 0) return ""
    var unit = daily ? (activePointCount === 1 ? "active day" : "active days")
      : (activePointCount === 1 ? "active bucket" : "active buckets")
    var grain = daily ? "daily" : "6-day oldest, then 12 weekly"
    return shortDate(period.startDate) + "–" + shortDate(period.endDate)
      + " · " + activePointCount + " " + unit + " · " + grain + " · current point partial"
  }

  width: parent ? parent.width : 0
  spacing: Style.space(6)
  visible: period !== null && points.length > 0

  PanelSectionHeader {
    width: parent.width
    text: "ACTIVITY " + root.metricLabel().toUpperCase()
    foreground: root.foreground
    fontFamily: root.fontFamily
  }

  Text {
    width: parent.width
    text: root.summaryText()
    textFormat: Text.PlainText
    color: root.dim
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
  }

  Item {
    id: chartArea
    width: parent.width
    height: Style.space(92)

    Rectangle {
      anchors.fill: parent
      radius: Style.cornerRadius
      color: root.alpha(root.foreground, 0.035)
    }

    Rectangle {
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.bottom: parent.bottom
      height: Math.max(1, Style.space(1))
      color: root.alpha(root.foreground, 0.22)
    }

    Row {
      anchors.fill: parent
      anchors.leftMargin: Style.space(4)
      anchors.rightMargin: Style.space(4)
      anchors.topMargin: Style.space(6)
      anchors.bottomMargin: Style.space(1)
      spacing: root.barGap

      Repeater {
        model: root.points

        Item {
          id: pointItem
          required property var modelData
          required property int index
          width: Math.max(1, (chartArea.width - Style.space(8)
            - root.barGap * Math.max(0, root.points.length - 1)) / Math.max(1, root.points.length))
          height: parent.height

          Rectangle {
            id: barTrack
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: Math.max(2, Math.min(parent.width, Style.space(16)))
            radius: Math.min(width / 2, Style.cornerRadius)
            color: root.alpha(root.foreground, 0.055)
          }

          Rectangle {
            visible: pointItem.modelData[root.normalizedMetricKey].value !== null
              && pointItem.modelData[root.normalizedMetricKey].value > 0
            anchors.left: barTrack.left
            anchors.right: barTrack.right
            anchors.bottom: barTrack.bottom
            height: root.peakValue > 0
              ? Math.max(Style.space(2), barTrack.height
                * pointItem.modelData[root.normalizedMetricKey].value / root.peakValue) : 0
            radius: barTrack.radius
            color: pointItem.modelData.partial
              ? root.foreground : root.alpha(root.foreground, 0.58)
          }

          Rectangle {
            visible: pointItem.modelData[root.normalizedMetricKey].value === null
            anchors.horizontalCenter: barTrack.horizontalCenter
            anchors.bottom: barTrack.bottom
            width: barTrack.width
            height: Style.space(4)
            radius: Math.min(width / 2, Style.cornerRadius)
            color: "transparent"
            border.width: Math.max(1, Style.space(1))
            border.color: root.dim
          }

          MouseArea {
            id: pointHover
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.NoButton
          }

          PanelToolTip {
            visible: pointHover.containsMouse
            text: root.pointTooltip(pointItem.modelData)
            fontFamily: root.fontFamily
          }
        }
      }
    }
  }

  Item {
    width: parent.width
    implicitHeight: Math.max(startLabel.implicitHeight, middleLabel.implicitHeight, endLabel.implicitHeight)

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
        ? root.shortDate(root.points[Math.floor((root.points.length - 1) / 2)].startDate) : ""
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
}
