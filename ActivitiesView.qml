pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

Column {
  id: root

  property var service: null
  property string viewMode: "summary"
  property bool imperial: false
  property bool panelCursorActive: false
  property bool hasCursor: false
  property color foreground: Color.foreground
  property color urgent: Color.urgent
  property color dim: Qt.darker(foreground, 1.5)
  property string fontFamily: Style.font.family
  property int periodIndex: 1
  property int chartMetricIndex: 0
  property int cursorIndex: 0
  property int savedListIndex: 0
  property string selectedTypeKey: ""
  property int listOffset: 0
  property string selectedActivityId: ""
  property string notice: ""

  readonly property var periodKeys: ["today", "7Days", "30Days", "90Days"]
  readonly property var chartMetricKeys: [
    "durationSeconds", "distanceMetres", "elevationGainMetres", "energyJoules"
  ]
  readonly property var chartMetricLabels: ["Time", "Distance", "Elevation gain", "Energy"]
  readonly property string periodKey: periodKeys[Math.max(0, Math.min(
    periodIndex, periodKeys.length - 1))]
  readonly property var currentPeriod: service ? Model.periodByKey(service.summary, periodKey) : null
  readonly property var currentTrend: service ? Model.trendByKey(service.activityTrends, periodKey) : null
  readonly property var currentPage: {
    if (!service || !service.activityPage) return null
    var page = service.activityPage
    var expectedType = selectedTypeKey === "" ? null : selectedTypeKey
    return page.periodKey === periodKey
      && page.endDate === (currentPeriod ? currentPeriod.endDate : "")
      && page.typeKey === expectedType && page.offset === listOffset ? page : null
  }
  readonly property var listActivities: currentPage ? currentPage.activities : []
  readonly property var detailActivity: service ? service.activityDetail : null
  readonly property int cursorCount: viewMode === "summary"
    ? (currentPeriod ? currentPeriod.byType.length : 0) + 2
    : viewMode === "list" ? Math.max(1, listActivities.length) : 2

  signal viewRequested(string view)

  function setCursor(index) {
    cursorIndex = Math.max(0, Math.min(cursorCount - 1, index))
  }

  function setPeriod(index) {
    periodIndex = Math.max(0, Math.min(periodKeys.length - 1, index))
    cursorIndex = 0
  }

  function openActivityList(typeKey) {
    if (!service || !currentPeriod || service.processRunning) return
    selectedTypeKey = String(typeKey || "")
    listOffset = 0
    cursorIndex = 0
    notice = ""
    viewRequested("list")
    service.loadActivityPage(periodKey, currentPeriod.endDate,
      selectedTypeKey === "" ? null : selectedTypeKey, listOffset)
  }

  function reloadActivityList() {
    if (!service || !currentPeriod || service.activityViewRunning) return
    service.loadActivityPage(periodKey, currentPeriod.endDate,
      selectedTypeKey === "" ? null : selectedTypeKey, listOffset)
  }

  function openActivityDetail(activity) {
    if (!service || !activity || service.processRunning) return
    selectedActivityId = String(activity.activityId || "")
    savedListIndex = cursorIndex
    cursorIndex = 1
    notice = ""
    viewRequested("detail")
    service.loadActivityDetail(selectedActivityId)
  }

  function back() {
    notice = ""
    if (viewMode === "detail") {
      selectedActivityId = ""
      cursorIndex = Math.max(0, Math.min(savedListIndex, Math.max(0, listActivities.length - 1)))
      viewRequested("list")
      if (!currentPage) reloadActivityList()
    } else if (viewMode === "list") {
      selectedActivityId = ""
      cursorIndex = 0
      viewRequested("summary")
    }
  }

  function moveCursor(dx, dy) {
    if (viewMode === "summary") {
      if (dx !== 0 && cursorIndex === 0) setPeriod(periodIndex + dx)
      else if (dx !== 0 && cursorIndex === 1)
        chartMetricIndex = Math.max(0, Math.min(
          chartMetricKeys.length - 1, chartMetricIndex + dx))
      else if (dy !== 0) setCursor(cursorIndex + dy)
      return
    }
    if (viewMode === "list") {
      if (dx < 0) {
        if (listOffset >= 20) {
          listOffset -= 20
          cursorIndex = 0
          reloadActivityList()
        } else back()
      } else if (dx > 0 && listActivities.length > 0) {
        openActivityDetail(listActivities[cursorIndex])
      } else if (dy > 0 && listActivities.length > 0
          && cursorIndex === listActivities.length - 1 && currentPage && currentPage.hasMore) {
        listOffset = currentPage.nextOffset
        cursorIndex = 0
        reloadActivityList()
      } else if (dy < 0 && cursorIndex === 0 && listOffset >= 20) {
        listOffset -= 20
        cursorIndex = 19
        reloadActivityList()
      } else if (dy !== 0 && listActivities.length > 0) setCursor(cursorIndex + dy)
      return
    }
    if (dx < 0) back()
    else if (dy !== 0) setCursor(cursorIndex + dy)
  }

  function activateCursor() {
    if (!service) return
    if (viewMode === "summary") {
      if (cursorIndex === 1) {
        chartMetricIndex = (chartMetricIndex + 1) % chartMetricKeys.length
        return
      }
      if (!currentPeriod) return
      var typeKey = cursorIndex === 0 ? "" : currentPeriod.byType[cursorIndex - 2].typeKey
      openActivityList(typeKey)
    } else if (viewMode === "list" && listActivities.length > 0) {
      openActivityDetail(listActivities[cursorIndex])
    } else if (viewMode === "detail") {
      if (cursorIndex === 0) back()
      else openGarminConnect()
    }
  }

  function openGarminConnect() {
    if (!detailActivity) return
    var url = Model.garminConnectUrl(String(detailActivity.activityId || ""))
    if (url === "") {
      notice = "This activity cannot be opened safely."
      return
    }
    if (!Qt.openUrlExternally(url)) notice = "The default browser could not be opened."
  }

  function viewErrorText() {
    if (!service || service.activityViewError === "") return ""
    if (service.activityViewError === "timeout") return "The local activity read timed out."
    if (service.activityViewError === "local_storage_error"
        || service.activityViewError === "backend_unavailable")
      return "Local activity data is unavailable."
    return "The local activity response was invalid."
  }

  function detailMetrics() {
    var activity = detailActivity
    if (!activity) return []
    var metrics = []
    if (activity.durationSeconds !== null) metrics.push({ label: "Duration", value: Model.formatDuration(activity.durationSeconds) })
    if (activity.movingDurationSeconds !== null) metrics.push({ label: "Moving time", value: Model.formatDuration(activity.movingDurationSeconds) })
    if (activity.distanceMetres !== null) metrics.push({ label: "Distance", value: Model.formatDistance(activity.distanceMetres, imperial) })
    if (activity.elevationGainMetres !== null) metrics.push({ label: "Elevation gain", value: Model.formatElevation(activity.elevationGainMetres, imperial) })
    if (activity.energyJoules !== null) metrics.push({ label: "Energy", value: Model.formatEnergy(activity.energyJoules, imperial) })
    if (activity.averageHeartRateBpm !== null) metrics.push({ label: "Average heart rate", value: Model.formatIntegerMetric(activity.averageHeartRateBpm, " bpm") })
    if (activity.maximumHeartRateBpm !== null) metrics.push({ label: "Maximum heart rate", value: Model.formatIntegerMetric(activity.maximumHeartRateBpm, " bpm") })
    if (activity.averageSpeedMetresPerSecond !== null) metrics.push({ label: "Average speed", value: Model.formatSpeed(activity.averageSpeedMetresPerSecond, imperial) })
    if (activity.averagePowerWatts !== null) metrics.push({ label: "Average power", value: Model.formatIntegerMetric(activity.averagePowerWatts, " W") })
    if (activity.totalSets !== null) metrics.push({ label: "Sets", value: Model.formatIntegerMetric(activity.totalSets, "") })
    if (activity.totalRepetitions !== null) metrics.push({ label: "Repetitions", value: Model.formatIntegerMetric(activity.totalRepetitions, "") })
    return metrics
  }

  function configuredPeriodIndex(value) {
    var index = periodKeys.indexOf(String(value || ""))
    return index >= 0 ? index : 1
  }

  function resetForSession(configuredPeriod) {
    periodIndex = configuredPeriodIndex(configuredPeriod)
    chartMetricIndex = 0
    cursorIndex = 0
    savedListIndex = 0
    selectedTypeKey = ""
    listOffset = 0
    selectedActivityId = ""
    notice = ""
  }

  Connections {
    target: root.service
    function onActivityPageChanged() {
      root.setCursor(root.listActivities.length === 0 ? 0 : root.cursorIndex)
    }
    function onActivityDetailMissingChanged() {
      if (root.viewMode === "detail" && root.service.activityDetailMissing) {
        root.notice = "That activity is no longer in local data."
        root.cursorIndex = Math.max(0, Math.min(root.savedListIndex,
          Math.max(0, root.listActivities.length - 1)))
        root.viewRequested("list")
        root.reloadActivityList()
      }
    }
    function onRefreshGenerationChanged() {
      if (root.viewMode === "detail" && root.selectedActivityId !== "")
        root.service.loadActivityDetail(root.selectedActivityId)
      else if (root.viewMode === "list") root.reloadActivityList()
    }
  }

  spacing: Style.space(10)

  Text {
    visible: root.notice !== ""
    width: parent.width
    text: root.notice
    textFormat: Text.PlainText
    color: root.urgent
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
    wrapMode: Text.WordWrap
  }

  Column {
    visible: root.viewMode === "summary"
    width: parent.width
    spacing: Style.space(10)

    Row {
      id: periods
      width: parent.width
      spacing: Style.space(5)

      Repeater {
        model: root.periodKeys

        Button {
          required property string modelData
          required property int index
          width: (periods.width - periods.spacing * 3) / 4
          text: Model.periodLabel(modelData)
          tooltipText: "Show " + Model.periodLabel(modelData) + " activities"
          Accessible.name: tooltipText
          selected: root.periodIndex === index
          bordered: true
          foreground: root.foreground
          fontFamily: root.fontFamily
          horizontalPadding: Style.space(4)
          onHovered: function(on) { if (on) root.setCursor(0) }
          onClicked: root.setPeriod(index)
        }
      }
    }

    Text {
      visible: root.currentPeriod !== null
      width: parent.width
      text: root.currentPeriod ? Model.formatCount(root.currentPeriod.overall.activityCount) : ""
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.title
      font.bold: true
    }

    Grid {
      id: metrics
      visible: root.currentPeriod !== null
      width: parent.width
      columns: width >= Style.space(520) ? 3 : 1
      spacing: Style.space(6)

      MetricCard {
        width: (metrics.width - metrics.spacing * (metrics.columns - 1)) / metrics.columns
        label: "DURATION"
        valueText: root.currentPeriod
          ? Model.formatDuration(root.currentPeriod.overall.durationSeconds.value) : "—"
      }
      MetricCard {
        width: (metrics.width - metrics.spacing * (metrics.columns - 1)) / metrics.columns
        label: "DISTANCE"
        valueText: root.currentPeriod
          ? Model.formatDistance(root.currentPeriod.overall.distanceMetres.value, root.imperial) : "—"
      }
      MetricCard {
        width: (metrics.width - metrics.spacing * (metrics.columns - 1)) / metrics.columns
        label: "ENERGY"
        valueText: root.currentPeriod
          ? Model.formatEnergy(root.currentPeriod.overall.energyJoules.value, root.imperial) : "—"
      }
    }

    Grid {
      id: chartMetrics
      width: parent.width
      columns: width >= Style.space(520) ? 4 : (width >= Style.space(320) ? 2 : 1)
      columnSpacing: Style.space(5)
      rowSpacing: Style.space(5)

      Repeater {
        model: root.chartMetricLabels

        Button {
          required property string modelData
          required property int index
          width: (chartMetrics.width - chartMetrics.columnSpacing
            * (chartMetrics.columns - 1)) / chartMetrics.columns
          text: modelData
          tooltipText: "Chart activity " + modelData.toLowerCase()
          Accessible.name: tooltipText
          selected: root.chartMetricIndex === index
          hasCursor: root.panelCursorActive && root.hasCursor && root.cursorIndex === 1
            && root.chartMetricIndex === index
          bordered: true
          foreground: root.foreground
          fontFamily: root.fontFamily
          fontSize: Style.font.caption
          horizontalPadding: Style.space(3)
          onHovered: function(on) { if (on) root.setCursor(1) }
          onClicked: root.chartMetricIndex = index
        }
      }
    }

    ActivityTimeChart {
      width: parent.width
      period: root.currentTrend
      metricKey: root.chartMetricKeys[root.chartMetricIndex]
      imperial: root.imperial
      foreground: root.foreground
      dim: root.dim
      fontFamily: root.fontFamily
    }

    CursorSurface {
      width: parent.width
      implicitHeight: browseRow.implicitHeight + Style.space(16)
      hasCursor: root.panelCursorActive && root.hasCursor && root.cursorIndex === 0
      foreground: root.foreground

      Row {
        id: browseRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.margins: Style.space(9)
        spacing: Style.space(8)
        Text {
          width: parent.width - browseArrow.width - parent.spacing
          text: "Browse all activities"
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          font.bold: true
        }
        Text {
          id: browseArrow
          text: "›"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.title
        }
      }

      MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onEntered: root.setCursor(0)
        onClicked: root.openActivityList("")
      }
    }

    PanelSectionHeader {
      visible: root.currentPeriod && root.currentPeriod.byType.length > 0
      text: "ACTIVITY TYPES"
      foreground: root.foreground
      fontFamily: root.fontFamily
    }

    Repeater {
      model: root.currentPeriod ? root.currentPeriod.byType : []

      CursorSurface {
        id: typeSurface
        required property var modelData
        required property int index
        width: parent.width
        implicitHeight: typeRow.implicitHeight + Style.space(12)
        hasCursor: root.panelCursorActive && root.hasCursor && root.cursorIndex === index + 2
        foreground: root.foreground

        Row {
          id: typeRow
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.margins: Style.space(8)
          spacing: Style.space(8)

          Column {
            width: parent.width - typeStats.width - parent.spacing
            spacing: Style.space(1)
            Text {
              width: parent.width
              text: Model.typeLabel(typeSurface.modelData.typeKey)
              textFormat: Text.PlainText
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              elide: Text.ElideRight
            }
            Text {
              width: parent.width
              text: Model.formatCount(typeSurface.modelData.activityCount)
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }

          Text {
            id: typeStats
            anchors.verticalCenter: parent.verticalCenter
            text: Model.formatDuration(typeSurface.modelData.durationSeconds.value)
              + " · " + Model.formatDistance(
                typeSurface.modelData.distanceMetres.value, root.imperial) + "  ›"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
        }

        MouseArea {
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onEntered: root.setCursor(typeSurface.index + 2)
          onClicked: root.openActivityList(typeSurface.modelData.typeKey)
        }
      }
    }

    Text {
      visible: root.currentPeriod === null
      width: parent.width
      text: "No valid activity summary is available yet."
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      horizontalAlignment: Text.AlignHCenter
      wrapMode: Text.WordWrap
    }
  }

  Column {
    visible: root.viewMode === "list"
    width: parent.width
    spacing: Style.space(10)

    Button {
      text: "Back to Activities"
      iconText: "←"
      tooltipText: "Back to Activities"
      Accessible.name: "Back to Activities"
      bordered: true
      foreground: root.foreground
      fontFamily: root.fontFamily
      onClicked: root.back()
    }

    Text {
      width: parent.width
      text: root.selectedTypeKey === "" ? "All activities" : Model.typeLabel(root.selectedTypeKey)
      textFormat: Text.PlainText
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.title
      font.bold: true
      elide: Text.ElideRight
    }

    Text {
      visible: root.service && root.service.activityViewRunning && root.currentPage === null
      width: parent.width
      text: "Loading local activities…"
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      horizontalAlignment: Text.AlignHCenter
    }

    Text {
      visible: root.viewErrorText() !== ""
      width: parent.width
      text: root.viewErrorText()
      color: root.urgent
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      wrapMode: Text.WordWrap
    }

    Repeater {
      model: root.listActivities

      CursorSurface {
        id: activitySurface
        required property var modelData
        required property int index
        width: parent.width
        implicitHeight: activityRow.implicitHeight + Style.space(14)
        hasCursor: root.panelCursorActive && root.hasCursor && root.cursorIndex === index
        foreground: root.foreground

        Row {
          id: activityRow
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.margins: Style.space(9)
          spacing: Style.space(8)

          Column {
            width: parent.width - activityStats.width - parent.spacing
            spacing: Style.space(2)
            Text {
              width: parent.width
              text: activitySurface.modelData.name === null
                ? Model.typeLabel(activitySurface.modelData.typeKey)
                : activitySurface.modelData.name
              textFormat: Text.PlainText
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              font.bold: true
              elide: Text.ElideRight
            }
            Text {
              width: parent.width
              text: Qt.formatDate(new Date(activitySurface.modelData.localDate + "T12:00:00"), "ddd d MMM")
                + " · " + Model.typeLabel(activitySurface.modelData.typeKey)
              textFormat: Text.PlainText
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
            }
          }

          Text {
            id: activityStats
            anchors.verticalCenter: parent.verticalCenter
            text: Model.formatDuration(activitySurface.modelData.durationSeconds)
              + " · " + Model.activityHeadline(activitySurface.modelData, root.imperial) + "  ›"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
        }

        MouseArea {
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onEntered: root.setCursor(activitySurface.index)
          onClicked: root.openActivityDetail(activitySurface.modelData)
        }
      }
    }

    Text {
      visible: root.currentPage && root.listActivities.length === 0
      width: parent.width
      text: "No matching activities are stored locally."
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      horizontalAlignment: Text.AlignHCenter
      wrapMode: Text.WordWrap
    }

    Row {
      visible: root.currentPage && (root.listOffset > 0 || root.currentPage.hasMore)
      anchors.horizontalCenter: parent.horizontalCenter
      spacing: Style.space(8)

      Button {
        text: "Previous"
        enabled: root.listOffset > 0 && root.service && !root.service.activityViewRunning
        foreground: root.foreground
        fontFamily: root.fontFamily
        bordered: true
        onClicked: {
          root.listOffset -= 20
          root.cursorIndex = 0
          root.reloadActivityList()
        }
      }
      Button {
        text: "Next"
        enabled: root.currentPage && root.currentPage.hasMore
          && root.service && !root.service.activityViewRunning
        foreground: root.foreground
        fontFamily: root.fontFamily
        bordered: true
        onClicked: {
          root.listOffset = root.currentPage.nextOffset
          root.cursorIndex = 0
          root.reloadActivityList()
        }
      }
    }
  }

  Column {
    visible: root.viewMode === "detail"
    width: parent.width
    spacing: Style.space(10)

    Button {
      text: "Back to activity list"
      iconText: "←"
      tooltipText: "Back to activity list"
      Accessible.name: "Back to activity list"
      hasCursor: root.panelCursorActive && root.hasCursor && root.cursorIndex === 0
      foreground: root.foreground
      fontFamily: root.fontFamily
      bordered: true
      onHovered: function(on) { if (on) root.setCursor(0) }
      onClicked: root.back()
    }

    Text {
      visible: root.service && root.service.activityViewRunning && root.detailActivity === null
      width: parent.width
      text: "Loading local activity details…"
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      horizontalAlignment: Text.AlignHCenter
    }

    Text {
      visible: root.viewErrorText() !== ""
      width: parent.width
      text: root.viewErrorText()
      color: root.urgent
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      wrapMode: Text.WordWrap
    }

    Text {
      visible: root.detailActivity !== null
      width: parent.width
      text: root.detailActivity
        ? (root.detailActivity.name === null
          ? Model.typeLabel(root.detailActivity.typeKey) : root.detailActivity.name) : ""
      textFormat: Text.PlainText
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.title
      font.bold: true
      elide: Text.ElideRight
    }

    Text {
      visible: root.detailActivity !== null
      width: parent.width
      text: root.detailActivity
        ? Qt.formatDate(new Date(root.detailActivity.localDate + "T12:00:00"), "dddd d MMMM yyyy")
          + " · " + root.detailActivity.startedAtLocal.slice(11, 16)
          + " · " + Model.typeLabel(root.detailActivity.typeKey) : ""
      textFormat: Text.PlainText
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      wrapMode: Text.WordWrap
    }

    Repeater {
      model: root.detailMetrics()

      Item {
        required property var modelData
        width: parent.width
        implicitHeight: metricLabel.implicitHeight + Style.space(10)
        Text {
          id: metricLabel
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          text: modelData.label
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
        Text {
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          text: modelData.value
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          font.bold: true
        }
      }
    }

    Button {
      visible: root.detailActivity !== null
      anchors.horizontalCenter: parent.horizontalCenter
      text: "Open in Garmin Connect"
      iconText: "↗"
      tooltipText: "Open this activity in Garmin Connect"
      Accessible.name: "Open this activity in Garmin Connect"
      hasCursor: root.panelCursorActive && root.hasCursor && root.cursorIndex === 1
      foreground: root.foreground
      fontFamily: root.fontFamily
      bordered: true
      onHovered: function(on) { if (on) root.setCursor(1) }
      onClicked: root.openGarminConnect()
    }
  }

  component MetricCard: BorderSurface {
    id: metricCard
    property string label: ""
    property string valueText: "—"

    implicitHeight: metricColumn.implicitHeight + Style.space(16)
    color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.035)
    borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)
    radius: Style.cornerRadius

    Column {
      id: metricColumn
      anchors.centerIn: parent
      spacing: Style.space(3)
      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: metricCard.label
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.letterSpacing: 1
      }
      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: metricCard.valueText
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.bold: true
      }
    }
  }
}
