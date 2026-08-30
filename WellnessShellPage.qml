pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

Column {
  id: root

  property var wellness: null
  property int viewIndex: 0
  property bool wideLayout: true
  property bool panelCursorActive: false
  property bool hasCursor: false
  property double nowMs: Date.now()
  property color foreground: Color.foreground
  property color urgent: Color.urgent
  property color dim: Qt.darker(foreground, 1.5)
  property string fontFamily: Style.font.family
  property int cursorIndex: 0
  readonly property int cursorCount: 1
  readonly property var readinessDay: Model.latestWellnessDay(wellness, "trainingReadiness")
  readonly property var batteryDay: Model.latestWellnessDay(wellness, "bodyBattery")
  readonly property var sleepDay: Model.latestWellnessDay(wellness, "sleep")
  readonly property var stepsDay: Model.latestWellnessDay(wellness, "steps")
  readonly property var hrvDay: Model.latestWellnessDay(wellness, "hrv")
  readonly property var restingDay: Model.latestWellnessDay(wellness, "restingHeartRate")
  readonly property var unavailableCategories: unavailableCategoryRows()

  signal viewRequested(int index)

  function moveCursor(dx, dy) {
    if (dx !== 0) viewRequested(Math.max(0, Math.min(1, viewIndex + dx)))
  }

  function activateCursor() {
    viewRequested(viewIndex === 0 ? 1 : 0)
  }

  function formatDate(value) {
    if (!value) return "Date unavailable"
    return Qt.formatDate(new Date(value + "T12:00:00"), "dddd d MMMM yyyy")
  }

  function dateText(day) {
    if (!day) return ""
    var machineDate = Qt.formatDateTime(new Date(nowMs), "yyyy-MM-dd")
    var current = wellness && day.date === wellness.asOfLocalDate
      && day.date === machineDate ? "Today · " : "Latest retained value · "
    return current + formatDate(day.date)
  }

  function sourceFor(category, day) {
    return Model.wellnessSourceForCategory(wellness, category, day ? day.date : null)
  }

  function freshnessText(source) {
    if (!source || source.refreshedAt === null) return "No successful refresh recorded"
    return "Refreshed " + Qt.formatDateTime(
      new Date(source.refreshedAt), "d MMMM yyyy, HH:mm")
  }

  function failureText(source) {
    return source ? Model.wellnessFailureText(source.failure) : ""
  }

  function categoryIsPartial(category, day) {
    if (!wellness || !day || day.date !== wellness.asOfLocalDate) return false
    var contractKey = category === "steps" ? "steps"
      : category === "bodyBattery" ? "bodyBattery" : ""
    return contractKey !== "" && wellness.partialCurrentDaySources.indexOf(contractKey) !== -1
  }

  function formatNumber(value, decimals) {
    if (value === null || value === undefined) return "—"
    return Number(value).toLocaleString(Qt.locale(), "f", decimals || 0)
  }

  function formatScore(value) {
    return value === null || value === undefined ? "Score unavailable" : formatNumber(value, 0) + " / 100"
  }

  function formatMilliseconds(value) {
    if (value === null || value === undefined) return "—"
    var decimals = Math.round(Number(value)) === Number(value) ? 0 : 1
    return formatNumber(value, decimals) + " ms"
  }

  function sleepStageSegments(sleep) {
    if (!sleep) return []
    return [
      { label: "Deep", value: Number(sleep.deepSeconds || 0), opacity: 0.92 },
      { label: "Light", value: Number(sleep.lightSeconds || 0), opacity: 0.68 },
      { label: "REM", value: Number(sleep.remSeconds || 0), opacity: 0.46 },
      { label: "Awake", value: Number(sleep.awakeSeconds || 0), opacity: 0.24 }
    ]
  }

  function sleepStageText(sleep) {
    if (!sleep) return ""
    var values = []
    if (sleep.deepSeconds !== null) values.push("Deep " + Model.formatDuration(sleep.deepSeconds))
    if (sleep.lightSeconds !== null) values.push("Light " + Model.formatDuration(sleep.lightSeconds))
    if (sleep.remSeconds !== null) values.push("REM " + Model.formatDuration(sleep.remSeconds))
    if (sleep.awakeSeconds !== null) values.push("Awake " + Model.formatDuration(sleep.awakeSeconds))
    return values.join(" · ")
  }

  function batteryDetail(battery) {
    if (!battery) return ""
    var values = []
    if (battery.lowest !== null && battery.highest !== null)
      values.push("Daily range " + battery.lowest + "–" + battery.highest)
    if (battery.charged !== null) values.push("Charged +" + battery.charged)
    if (battery.drained !== null) values.push("Drained −" + battery.drained)
    return values.join(" · ")
  }

  function stepsDetail(steps) {
    if (!steps || steps.goal === null) return "Goal unavailable"
    var percent = steps.value === null || steps.goal <= 0
      ? "" : " · " + Math.round(100 * steps.value / steps.goal) + "%"
    return "Garmin goal " + formatNumber(steps.goal, 0) + percent
  }

  function hrvDetail(hrv) {
    if (!hrv) return ""
    var values = []
    if (hrv.weeklyAverageMs !== null)
      values.push("7-day average " + formatMilliseconds(hrv.weeklyAverageMs))
    if (hrv.status !== null) values.push(hrv.status)
    return values.join(" · ")
  }

  function hrvContext(hrv) {
    if (!hrv || hrv.balancedLowMs === null || hrv.balancedUpperMs === null)
      return "Garmin balanced baseline unavailable"
    return "Garmin balanced baseline " + formatMilliseconds(hrv.balancedLowMs)
      + "–" + formatMilliseconds(hrv.balancedUpperMs)
  }

  function unavailableCategoryRows() {
    var definitions = [
      { key: "trainingReadiness", label: "Training Readiness", day: readinessDay },
      { key: "bodyBattery", label: "Body Battery", day: batteryDay },
      { key: "sleep", label: "Sleep", day: sleepDay },
      { key: "steps", label: "Steps", day: stepsDay },
      { key: "hrv", label: "HRV", day: hrvDay },
      { key: "restingHeartRate", label: "Resting heart rate", day: restingDay }
    ]
    var rows = []
    for (var index = 0; index < definitions.length; index++) {
      var definition = definitions[index]
      if (definition.day !== null) continue
      var source = sourceFor(definition.key, null)
      rows.push({
        label: definition.label,
        reason: Model.wellnessUnavailableReason(wellness, definition.key),
        problem: source && source.failure !== null && source.failure !== "unsupported"
      })
    }
    return rows
  }

  spacing: Style.space(12)

  Row {
    id: wellnessTabs
    width: parent.width
    spacing: Style.space(6)

    Repeater {
      model: ["Today", "Trends"]

      Button {
        required property string modelData
        required property int index
        width: (wellnessTabs.width - wellnessTabs.spacing) / 2
        text: modelData
        tooltipText: "Show Wellness " + modelData
        Accessible.name: "Show Wellness " + modelData
        selected: root.viewIndex === index
        hasCursor: root.panelCursorActive && root.hasCursor && root.cursorIndex === 0
          && root.viewIndex === index
        bordered: true
        foreground: root.foreground
        fontFamily: root.fontFamily
        onClicked: root.viewRequested(index)
      }
    }
  }

  Column {
    visible: root.viewIndex === 0
    width: parent.width
    spacing: Style.space(10)

    Item {
      width: parent.width
      implicitHeight: Math.max(todayTitle.implicitHeight, todayDate.implicitHeight)

      Text {
        id: todayTitle
        anchors.left: parent.left
        anchors.right: todayDate.left
        anchors.rightMargin: Style.space(8)
        text: "Wellness Today"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        font.bold: true
        wrapMode: Text.WordWrap
      }

      Text {
        id: todayDate
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        text: root.wellness ? root.formatDate(root.wellness.asOfLocalDate) : "No local summary"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        horizontalAlignment: Text.AlignRight
        wrapMode: Text.WordWrap
        width: Math.min(implicitWidth, parent.width * 0.52)
      }
    }

    Text {
      visible: root.wellness && !root.wellness.collectionEnabled
      width: parent.width
      text: "Wellness collection is off. Retained values remain visible with their original dates."
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      wrapMode: Text.WordWrap
    }

    Grid {
      id: primaryCards
      width: parent.width
      columns: root.wideLayout ? 2 : 1
      columnSpacing: Style.space(8)
      rowSpacing: Style.space(8)

      TodayCard {
        visible: root.readinessDay !== null
        width: (primaryCards.width - primaryCards.columnSpacing
          * (primaryCards.columns - 1)) / primaryCards.columns
        title: "TRAINING READINESS"
        valueText: root.readinessDay
          ? root.formatScore(root.readinessDay.trainingReadiness.score) : ""
        detailText: root.readinessDay && root.readinessDay.trainingReadiness.level !== null
          ? root.readinessDay.trainingReadiness.level : "Garmin level unavailable"
        dateLabel: root.dateText(root.readinessDay)
        source: root.sourceFor("trainingReadiness", root.readinessDay)
      }

      TodayCard {
        visible: root.batteryDay !== null
        width: (primaryCards.width - primaryCards.columnSpacing
          * (primaryCards.columns - 1)) / primaryCards.columns
        title: "BODY BATTERY"
        valueText: root.batteryDay && root.batteryDay.bodyBattery.latest !== null
          ? root.formatNumber(root.batteryDay.bodyBattery.latest, 0) + " / 100"
          : "Latest level unavailable"
        detailText: root.batteryDay ? root.batteryDetail(root.batteryDay.bodyBattery) : ""
        dateLabel: root.dateText(root.batteryDay)
        source: root.sourceFor("bodyBattery", root.batteryDay)
        partial: root.categoryIsPartial("bodyBattery", root.batteryDay)
        showRange: root.batteryDay && root.batteryDay.bodyBattery.lowest !== null
          && root.batteryDay.bodyBattery.highest !== null
        rangeLow: showRange ? root.batteryDay.bodyBattery.lowest : 0
        rangeHigh: showRange ? root.batteryDay.bodyBattery.highest : 0
        rangePosition: root.batteryDay && root.batteryDay.bodyBattery.latest !== null
          ? root.batteryDay.bodyBattery.latest : rangeHigh
      }
    }

    TodayCard {
      visible: root.sleepDay !== null
      width: parent.width
      title: "SLEEP"
      valueText: root.sleepDay && root.sleepDay.sleep.score !== null
        ? root.formatScore(root.sleepDay.sleep.score) : "Score unavailable"
      detailText: root.sleepDay && root.sleepDay.sleep.totalSeconds !== null
        ? "Total " + Model.formatDuration(root.sleepDay.sleep.totalSeconds)
        : "Total duration unavailable"
      contextText: root.sleepDay ? root.sleepStageText(root.sleepDay.sleep) : ""
      dateLabel: root.dateText(root.sleepDay)
      source: root.sourceFor("sleep", root.sleepDay)
      segments: root.sleepDay ? root.sleepStageSegments(root.sleepDay.sleep) : []
    }

    Grid {
      id: secondaryCards
      width: parent.width
      columns: root.wideLayout ? 3 : 1
      columnSpacing: Style.space(8)
      rowSpacing: Style.space(8)

      TodayCard {
        visible: root.stepsDay !== null
        width: (secondaryCards.width - secondaryCards.columnSpacing
          * (secondaryCards.columns - 1)) / secondaryCards.columns
        title: "STEPS"
        valueText: root.stepsDay && root.stepsDay.steps.value !== null
          ? root.formatNumber(root.stepsDay.steps.value, 0) : "Count unavailable"
        detailText: root.stepsDay ? root.stepsDetail(root.stepsDay.steps) : ""
        dateLabel: root.dateText(root.stepsDay)
        source: root.sourceFor("steps", root.stepsDay)
        partial: root.categoryIsPartial("steps", root.stepsDay)
        progress: root.stepsDay && root.stepsDay.steps.value !== null
          && root.stepsDay.steps.goal !== null && root.stepsDay.steps.goal > 0
          ? Math.min(1, root.stepsDay.steps.value / root.stepsDay.steps.goal) : -1
      }

      TodayCard {
        visible: root.hrvDay !== null
        width: (secondaryCards.width - secondaryCards.columnSpacing
          * (secondaryCards.columns - 1)) / secondaryCards.columns
        title: "HRV"
        valueText: root.hrvDay && root.hrvDay.hrv.lastNightAverageMs !== null
          ? root.formatMilliseconds(root.hrvDay.hrv.lastNightAverageMs) + " last night"
          : "Last-night average unavailable"
        detailText: root.hrvDay ? root.hrvDetail(root.hrvDay.hrv) : ""
        contextText: root.hrvDay ? root.hrvContext(root.hrvDay.hrv) : ""
        dateLabel: root.dateText(root.hrvDay)
        source: root.sourceFor("hrv", root.hrvDay)
      }

      TodayCard {
        visible: root.restingDay !== null
        width: (secondaryCards.width - secondaryCards.columnSpacing
          * (secondaryCards.columns - 1)) / secondaryCards.columns
        title: "RESTING HEART RATE"
        valueText: root.restingDay && root.restingDay.restingHeartRate.beatsPerMinute !== null
          ? root.formatNumber(root.restingDay.restingHeartRate.beatsPerMinute, 0) + " bpm"
          : "Value unavailable"
        detailText: "Daily resting value"
        dateLabel: root.dateText(root.restingDay)
        source: root.sourceFor("restingHeartRate", root.restingDay)
      }
    }

    BorderSurface {
      visible: root.unavailableCategories.length > 0
      width: parent.width
      implicitHeight: unavailableColumn.implicitHeight + Style.space(18)
      color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.025)
      borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)
      radius: Style.cornerRadius

      Column {
        id: unavailableColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.margins: Style.space(9)
        spacing: Style.space(6)

        Text {
          width: parent.width
          text: "UNAVAILABLE"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
          font.letterSpacing: 0.7
        }

        Repeater {
          model: root.unavailableCategories

          Text {
            required property var modelData
            width: parent.width
            text: modelData.label + " · " + modelData.reason
            textFormat: Text.PlainText
            color: modelData.problem ? root.urgent : root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WordWrap
          }
        }
      }
    }
  }

  BorderSurface {
    visible: root.viewIndex === 1
    width: parent.width
    implicitHeight: trendsColumn.implicitHeight + Style.space(32)
    color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.035)
    borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)
    radius: Style.cornerRadius

    Column {
      id: trendsColumn
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.margins: Style.space(16)
      spacing: Style.space(8)

      Text {
        width: parent.width
        text: "Wellness Trends"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        font.bold: true
        horizontalAlignment: Text.AlignHCenter
      }

      Text {
        width: parent.width
        text: "Focused wellness history remains planned for the next phase."
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
      }
    }
  }

  component TodayCard: BorderSurface {
    id: card

    property string title: ""
    property string valueText: ""
    property string detailText: ""
    property string contextText: ""
    property string dateLabel: ""
    property var source: null
    property bool partial: false
    property real progress: -1
    property bool showRange: false
    property real rangeLow: 0
    property real rangeHigh: 0
    property real rangePosition: 0
    property var segments: []
    readonly property real segmentTotal: {
      var total = 0
      for (var index = 0; index < segments.length; index++) total += segments[index].value
      return total
    }
    readonly property string failureLabel: root.failureText(source)

    implicitHeight: cardColumn.implicitHeight + Style.space(18)
    color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.035)
    borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)
    radius: Style.cornerRadius

    Column {
      id: cardColumn
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.margins: Style.space(9)
      spacing: Style.space(5)

      Text {
        width: parent.width
        text: card.title
        textFormat: Text.PlainText
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        font.letterSpacing: 0.7
        wrapMode: Text.WordWrap
      }

      Text {
        width: parent.width
        text: card.valueText
        textFormat: Text.PlainText
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        font.bold: true
        wrapMode: Text.WordWrap
      }

      Text {
        visible: card.detailText !== ""
        width: parent.width
        text: card.detailText
        textFormat: Text.PlainText
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.WordWrap
      }

      Item {
        visible: card.progress >= 0
        width: parent.width
        implicitHeight: Style.space(6)

        Rectangle {
          anchors.fill: parent
          radius: height / 2
          color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.10)
        }
        Rectangle {
          anchors.left: parent.left
          anchors.top: parent.top
          anchors.bottom: parent.bottom
          width: parent.width * Math.max(0, Math.min(1, card.progress))
          radius: height / 2
          color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.72)
        }
      }

      Item {
        visible: card.showRange
        width: parent.width
        implicitHeight: Style.space(8)

        Rectangle {
          anchors.fill: parent
          radius: height / 2
          color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.10)
        }
        Rectangle {
          x: parent.width * Math.max(0, Math.min(1, card.rangeLow / 100))
          width: parent.width * Math.max(0, Math.min(1,
            (card.rangeHigh - card.rangeLow) / 100))
          anchors.top: parent.top
          anchors.bottom: parent.bottom
          radius: height / 2
          color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.54)
        }
        Rectangle {
          x: Math.max(0, Math.min(parent.width - width,
            parent.width * card.rangePosition / 100 - width / 2))
          anchors.top: parent.top
          anchors.bottom: parent.bottom
          width: Math.max(Style.space(2), 2)
          color: root.foreground
        }
      }

      Row {
        visible: card.segmentTotal > 0
        width: parent.width
        height: Style.space(8)
        spacing: 0

        Repeater {
          model: card.segments

          Rectangle {
            required property var modelData
            width: card.segmentTotal > 0
              ? parent.width * modelData.value / card.segmentTotal : 0
            height: parent.height
            color: Qt.rgba(root.foreground.r, root.foreground.g,
              root.foreground.b, modelData.opacity)
          }
        }
      }

      Text {
        visible: card.contextText !== ""
        width: parent.width
        text: card.contextText
        textFormat: Text.PlainText
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }

      Text {
        width: parent.width
        text: card.dateLabel + (card.partial ? " · Partial at last refresh" : "")
        textFormat: Text.PlainText
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }

      Text {
        width: parent.width
        text: root.freshnessText(card.source)
        textFormat: Text.PlainText
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }

      Text {
        visible: card.failureLabel !== ""
        width: parent.width
        text: card.failureLabel + " · showing retained value"
        textFormat: Text.PlainText
        color: card.source && card.source.failure === "unsupported" ? root.dim : root.urgent
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        wrapMode: Text.WordWrap
      }
    }
  }
}
