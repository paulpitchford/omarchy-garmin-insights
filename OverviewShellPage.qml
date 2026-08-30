pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

Column {
  id: root

  property var service: null
  property bool wideLayout: true
  property bool imperial: false
  property bool panelCursorActive: false
  property bool hasCursor: false
  property color foreground: Color.foreground
  property color urgent: Color.urgent
  property color dim: Qt.darker(foreground, 1.5)
  property string fontFamily: Style.font.family

  signal wellnessRequested()
  signal activitiesRequested()

  readonly property var wellness: service && service.wellness ? service.wellness : null
  readonly property double nowMs: service && Number(service.nowMs) > 0
    ? Number(service.nowMs) : Date.now()
  readonly property var batteryDay: Model.latestWellnessDay(wellness, "bodyBattery")
  readonly property var sleepDay: Model.latestWellnessDay(wellness, "sleep")
  readonly property var stepsDay: Model.latestWellnessDay(wellness, "steps")
  readonly property var unavailableSignals: unavailableSignalRows()
  readonly property var week: service ? Model.periodByKey(service.summary, "7Days") : null
  readonly property var weekTrend: service ? Model.trendByKey(service.activityTrends, "7Days") : null
  readonly property var latestActivity: service && service.latestActivity
    ? service.latestActivity : null
  readonly property int cursorCount: 2
  property int cursorIndex: 0

  function moveCursor(dx, dy) {
    if (dy !== 0) cursorIndex = Math.max(0, Math.min(cursorCount - 1, cursorIndex + dy))
  }

  function activateCursor() {
    if (cursorIndex === 0) wellnessRequested()
    else activitiesRequested()
  }

  function formatNumber(value) {
    return Number(value).toLocaleString(Qt.locale(), "f", 0)
  }

  function signalSource(category, day) {
    return Model.wellnessSourceForCategory(wellness, category, day ? day.date : null)
  }

  function signalDate(day) {
    if (!day) return ""
    var machineDate = Qt.formatDateTime(new Date(nowMs), "yyyy-MM-dd")
    var prefix = wellness && day.date === wellness.asOfLocalDate
      && day.date === machineDate ? "Today " : "Latest retained "
    return prefix + Qt.formatDate(new Date(day.date + "T12:00:00"), "d MMM")
  }

  function signalIsPartial(category, day) {
    if (!wellness || !day || day.date !== wellness.asOfLocalDate) return false
    var contractKey = category === "steps" ? "steps"
      : category === "bodyBattery" ? "bodyBattery" : ""
    return contractKey !== "" && wellness.partialCurrentDaySources.indexOf(contractKey) !== -1
  }

  function signalFreshness(category, day) {
    var source = signalSource(category, day)
    if (!source || source.refreshedAt === null) return "No successful refresh recorded"
    return "Refreshed " + Qt.formatDateTime(new Date(source.refreshedAt), "d MMM, HH:mm")
  }

  function signalFailure(category, day) {
    var source = signalSource(category, day)
    return source ? Model.wellnessFailureText(source.failure) : ""
  }

  function signalFailureIsProblem(category, day) {
    var source = signalSource(category, day)
    return source !== null && source.failure !== null && source.failure !== "unsupported"
  }

  function batteryValue() {
    if (!batteryDay || batteryDay.bodyBattery.latest === null) return "Level unavailable"
    return formatNumber(batteryDay.bodyBattery.latest) + " / 100"
  }

  function batteryDetail() {
    if (!batteryDay) return ""
    var battery = batteryDay.bodyBattery
    return battery.lowest !== null && battery.highest !== null
      ? "Range " + battery.lowest + "–" + battery.highest : "Daily range unavailable"
  }

  function sleepValue() {
    if (!sleepDay) return ""
    if (sleepDay.sleep.score !== null) return formatNumber(sleepDay.sleep.score) + " / 100"
    if (sleepDay.sleep.totalSeconds !== null) return Model.formatDuration(sleepDay.sleep.totalSeconds)
    return "Value unavailable"
  }

  function sleepDetail() {
    if (!sleepDay) return ""
    return sleepDay.sleep.totalSeconds !== null
      ? "Total " + Model.formatDuration(sleepDay.sleep.totalSeconds)
      : "Total duration unavailable"
  }

  function stepsValue() {
    if (!stepsDay || stepsDay.steps.value === null) return "Count unavailable"
    return formatNumber(stepsDay.steps.value)
  }

  function stepsDetail() {
    if (!stepsDay || stepsDay.steps.goal === null) return "Goal unavailable"
    return "Goal " + formatNumber(stepsDay.steps.goal)
  }

  function unavailableSignalRows() {
    var definitions = [
      { key: "bodyBattery", label: "Body Battery", day: batteryDay },
      { key: "sleep", label: "Sleep", day: sleepDay },
      { key: "steps", label: "Steps", day: stepsDay }
    ]
    var rows = []
    for (var index = 0; index < definitions.length; index++) {
      var definition = definitions[index]
      if (definition.day !== null) continue
      var source = signalSource(definition.key, null)
      rows.push({
        label: definition.label,
        reason: Model.wellnessUnavailableReason(wellness, definition.key),
        problem: source && source.failure !== null && source.failure !== "unsupported"
      })
    }
    return rows
  }

  spacing: Style.space(12)

  Item {
    width: parent.width
    implicitHeight: Math.max(overviewTitle.implicitHeight, wellnessButton.implicitHeight)

    Text {
      id: overviewTitle
      anchors.left: parent.left
      anchors.right: wellnessButton.left
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
      text: "Wellness today"
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.title
      font.bold: true
      wrapMode: Text.WordWrap
    }

    Button {
      id: wellnessButton
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      text: "All wellness"
      iconText: "→"
      tooltipText: "Open Wellness"
      Accessible.name: "Open Wellness"
      hasCursor: root.panelCursorActive && root.hasCursor && root.cursorIndex === 0
      bordered: true
      foreground: root.foreground
      fontFamily: root.fontFamily
      onHovered: function(on) { if (on) root.cursorIndex = 0 }
      onClicked: root.wellnessRequested()
    }
  }

  Grid {
    id: signals
    width: parent.width
    columns: root.wideLayout ? 3 : 1
    columnSpacing: Style.space(8)
    rowSpacing: Style.space(8)

    SignalCard {
      visible: root.batteryDay !== null
      width: (signals.width - signals.columnSpacing * (signals.columns - 1)) / signals.columns
      title: "BODY BATTERY"
      valueText: root.batteryValue()
      detailText: root.batteryDetail()
      dateText: root.signalDate(root.batteryDay)
      freshnessText: root.signalFreshness("bodyBattery", root.batteryDay)
      failureText: root.signalFailure("bodyBattery", root.batteryDay)
      failureProblem: root.signalFailureIsProblem("bodyBattery", root.batteryDay)
      partial: root.signalIsPartial("bodyBattery", root.batteryDay)
    }

    SignalCard {
      visible: root.sleepDay !== null
      width: (signals.width - signals.columnSpacing * (signals.columns - 1)) / signals.columns
      title: "SLEEP"
      valueText: root.sleepValue()
      detailText: root.sleepDetail()
      dateText: root.signalDate(root.sleepDay)
      freshnessText: root.signalFreshness("sleep", root.sleepDay)
      failureText: root.signalFailure("sleep", root.sleepDay)
      failureProblem: root.signalFailureIsProblem("sleep", root.sleepDay)
    }

    SignalCard {
      visible: root.stepsDay !== null
      width: (signals.width - signals.columnSpacing * (signals.columns - 1)) / signals.columns
      title: "STEPS"
      valueText: root.stepsValue()
      detailText: root.stepsDetail()
      dateText: root.signalDate(root.stepsDay)
      freshnessText: root.signalFreshness("steps", root.stepsDay)
      failureText: root.signalFailure("steps", root.stepsDay)
      failureProblem: root.signalFailureIsProblem("steps", root.stepsDay)
      partial: root.signalIsPartial("steps", root.stepsDay)
    }
  }

  BorderSurface {
    visible: root.unavailableSignals.length > 0
    width: parent.width
    implicitHeight: overviewUnavailableColumn.implicitHeight + Style.space(14)
    color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.025)
    borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)
    radius: Style.cornerRadius

    Column {
      id: overviewUnavailableColumn
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.margins: Style.space(7)
      spacing: Style.space(3)

      Repeater {
        model: root.unavailableSignals

        Text {
          required property var modelData
          width: parent.width
          text: modelData.label + " unavailable · " + modelData.reason
          textFormat: Text.PlainText
          color: modelData.problem ? root.urgent : root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }
      }
    }
  }

  PanelSeparator { width: parent.width; foreground: root.foreground }

  Text {
    width: parent.width
    text: root.week ? Model.formatCount(root.week.overall.activityCount) + " this week"
      : "Activities this week"
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.title
    font.bold: true
    wrapMode: Text.WordWrap
  }

  CursorSurface {
    width: parent.width
    implicitHeight: activityColumn.implicitHeight + Style.space(18)
    hasCursor: root.panelCursorActive && root.hasCursor && root.cursorIndex === 1
    foreground: root.foreground
    bordered: true

    Column {
      id: activityColumn
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.margins: Style.space(9)
      spacing: Style.space(8)

      ActivityTimeChart {
        width: parent.width
        period: root.weekTrend
        foreground: root.foreground
        dim: root.dim
        fontFamily: root.fontFamily
      }

      PanelSeparator {
        visible: root.latestActivity !== null
        width: parent.width
        foreground: root.foreground
      }

      Row {
        visible: root.latestActivity !== null
        width: parent.width
        spacing: Style.space(8)

        Column {
          width: parent.width - latestActivityStats.width - parent.spacing
          spacing: Style.space(2)

          Text {
            width: parent.width
            text: root.latestActivity
              ? (root.latestActivity.name === null
                ? Model.typeLabel(root.latestActivity.typeKey) : root.latestActivity.name) : ""
            textFormat: Text.PlainText
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            font.bold: true
            elide: Text.ElideRight
          }

          Text {
            width: parent.width
            text: root.latestActivity
              ? "Latest · " + Qt.formatDate(
                new Date(root.latestActivity.localDate + "T12:00:00"), "ddd d MMM")
                + " · " + Model.typeLabel(root.latestActivity.typeKey) : ""
            textFormat: Text.PlainText
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }
        }

        Text {
          id: latestActivityStats
          anchors.verticalCenter: parent.verticalCenter
          text: root.latestActivity
            ? Model.formatDuration(root.latestActivity.durationSeconds) + " · "
              + Model.activityHeadline(root.latestActivity, root.imperial) + "  ›"
            : ""
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
      }

      Text {
        visible: root.latestActivity === null
        width: parent.width
        text: root.week
          ? Model.formatDuration(root.week.overall.durationSeconds.value)
            + " · " + Model.formatDistance(root.week.overall.distanceMetres.value, root.imperial)
            + " · Open Activities  ›"
          : "Open Activities  ›"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        horizontalAlignment: Text.AlignRight
        wrapMode: Text.WordWrap
      }
    }

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: root.cursorIndex = 1
      onClicked: root.activitiesRequested()
    }
  }

  component SignalCard: BorderSurface {
    id: signalCard

    property string title: ""
    property string valueText: ""
    property string detailText: ""
    property string dateText: ""
    property string freshnessText: ""
    property string failureText: ""
    property bool failureProblem: false
    property bool partial: false

    implicitHeight: signalColumn.implicitHeight + Style.space(16)
    color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.035)
    borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)
    radius: Style.cornerRadius

    Column {
      id: signalColumn
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.margins: Style.space(8)
      spacing: Style.space(2)

      Text {
        width: parent.width
        text: signalCard.title
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        font.letterSpacing: 0.7
        wrapMode: Text.WordWrap
      }
      Text {
        width: parent.width
        text: signalCard.valueText
        textFormat: Text.PlainText
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        font.bold: true
        wrapMode: Text.WordWrap
      }
      Text {
        width: parent.width
        text: signalCard.detailText
        textFormat: Text.PlainText
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
      Text {
        width: parent.width
        text: signalCard.dateText + (signalCard.partial ? " · Partial at last refresh" : "")
          + " · " + signalCard.freshnessText
        textFormat: Text.PlainText
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
      Text {
        visible: signalCard.failureText !== ""
        width: parent.width
        text: signalCard.failureText + " · retained value"
        textFormat: Text.PlainText
        color: signalCard.failureProblem ? root.urgent : root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        wrapMode: Text.WordWrap
      }
    }
  }
}
