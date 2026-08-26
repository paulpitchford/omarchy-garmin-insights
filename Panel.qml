pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "io.github.paulpitchford.garmin-insights"
  manageIpc: false

  property var service: null
  property var anchorItem: null
  property var hostWidget: null
  property int periodIndex: 1
  property string viewMode: "summary"
  property bool cursorActive: false
  property int summaryIndex: 0
  property int listIndex: 0
  property int detailIndex: 1
  property string selectedTypeKey: ""
  property int listOffset: 0
  property string selectedActivityId: ""
  property string panelNotice: ""

  readonly property var periodKeys: ["today", "7Days", "30Days", "90Days"]
  readonly property string periodKey: periodKeys[Math.max(0, Math.min(periodIndex, periodKeys.length - 1))]
  readonly property var currentPeriod: service ? Model.periodByKey(service.summary, periodKey) : null
  readonly property var currentPage: {
    if (!service || !service.activityPage) return null
    var page = service.activityPage
    var expectedType = selectedTypeKey === "" ? null : selectedTypeKey
    return page.periodKey === periodKey && page.endDate === (currentPeriod ? currentPeriod.endDate : "")
      && page.typeKey === expectedType && page.offset === listOffset ? page : null
  }
  readonly property var listActivities: currentPage ? currentPage.activities : []
  readonly property var detailActivity: service ? service.activityDetail : null
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.5)
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property string unitsSetting: String(setting("units", "auto"))
  readonly property bool imperial: unitsSetting === "imperial"
    || (unitsSetting === "auto" && (Qt.locale().measurementSystem === Locale.ImperialUSSystem
      || Qt.locale().measurementSystem === Locale.ImperialUKSystem))
  readonly property int summaryBaseCount: currentPeriod ? currentPeriod.byType.length + 1 : 1
  readonly property bool showUpdateCheck: service && service.updateChecksEnabled
    && service.updateSupported
  readonly property int updateCheckIndex: summaryBaseCount
  readonly property int updateReviewIndex: summaryBaseCount + 1
  readonly property int summaryCursorCount: summaryBaseCount + (showUpdateCheck ? 1 : 0)
    + (service && service.updateAvailable && showUpdateCheck ? 1 : 0)

  function configuredPeriodIndex() {
    var key = String(setting("period", "7Days"))
    var index = periodKeys.indexOf(key)
    return index >= 0 ? index : 1
  }

  function movePeriod(delta) {
    periodIndex = Math.max(0, Math.min(periodKeys.length - 1, periodIndex + delta))
    summaryIndex = 0
  }

  function switchPanel(direction) {
    if (bar && typeof bar.switchPanelFrom === "function")
      return bar.switchPanelFrom(hostWidget || root, direction)
    return false
  }

  function primaryAction() {
    if (!service) return
    if (service.connectionState === "setup") service.launchSetup()
    else if (service.connectionState === "unauthenticated" || service.connectionState === "reconnect") service.launchLogin()
    else if (service.connectionState === "localError" && !service.configured) service.checkAuthentication()
    else service.refresh()
  }

  function actionLabel() {
    if (!service) return "Loading…"
    if (service.connectionState === "setup") return service.uvPath === "" ? "Install uv to continue" : "Set up backend"
    if (service.connectionState === "unauthenticated") return "Connect Garmin"
    if (service.connectionState === "reconnect") return "Reconnect Garmin"
    if (service.connectionState === "localError") return "Retry"
    return service.refreshing ? "Refreshing…" : "Refresh"
  }

  function openActivityList(typeKey) {
    if (!service || !currentPeriod || service.processRunning) return
    selectedTypeKey = String(typeKey || "")
    listOffset = 0
    listIndex = 0
    cursorActive = true
    panelNotice = ""
    viewMode = "list"
    service.loadActivityPage(
      periodKey, currentPeriod.endDate, selectedTypeKey === "" ? null : selectedTypeKey, listOffset)
  }

  function reloadActivityList() {
    if (!service || !currentPeriod || service.activityViewRunning) return
    service.loadActivityPage(
      periodKey, currentPeriod.endDate, selectedTypeKey === "" ? null : selectedTypeKey, listOffset)
  }

  function openActivityDetail(activity) {
    if (!service || !activity || service.processRunning) return
    selectedActivityId = String(activity.activityId || "")
    detailIndex = 1
    panelNotice = ""
    viewMode = "detail"
    service.loadActivityDetail(selectedActivityId)
  }

  function returnToList() {
    viewMode = "list"
    selectedActivityId = ""
    if (!currentPage) reloadActivityList()
  }

  function returnToSummary() {
    viewMode = "summary"
    selectedActivityId = ""
    panelNotice = ""
    cursorActive = false
  }

  function backOrClose() {
    if (viewMode === "detail") returnToList()
    else if (viewMode === "list") returnToSummary()
    else close()
  }

  function ensureItemVisible(item) {
    if (!item) return
    var point = item.mapToItem(contentColumn, 0, 0)
    if (point.y < scroll.contentY) scroll.contentY = Math.max(0, point.y)
    else if (point.y + item.height > scroll.contentY + scroll.height)
      scroll.contentY = Math.max(0, point.y + item.height - scroll.height)
  }

  function ensureSummaryCursorVisible() {
    Qt.callLater(function() {
      if (root.summaryIndex === 0) root.ensureItemVisible(browseAllSurface)
      else if (root.summaryIndex < root.summaryBaseCount)
        root.ensureItemVisible(summaryTypeRepeater.itemAt(root.summaryIndex - 1))
      else if (root.summaryIndex === root.updateCheckIndex)
        root.ensureItemVisible(updateCheckButton)
      else if (root.summaryIndex === root.updateReviewIndex)
        root.ensureItemVisible(updateReviewButton)
    })
  }

  function ensureListCursorVisible() {
    Qt.callLater(function() { root.ensureItemVisible(listRepeater.itemAt(root.listIndex)) })
  }

  function moveCursor(dx, dy) {
    if (!cursorActive) {
      cursorActive = true
      return
    }
    if (viewMode === "summary") {
      if (dx !== 0) movePeriod(dx)
      else if (dy !== 0) {
        summaryIndex = Math.max(0, Math.min(summaryCursorCount - 1, summaryIndex + dy))
        ensureSummaryCursorVisible()
      }
      return
    }
    if (viewMode === "list") {
      if (dx < 0) {
        if (listOffset >= 20) {
          listOffset -= 20
          listIndex = 0
          reloadActivityList()
        } else returnToSummary()
      } else if (dx > 0 && listActivities.length > 0) {
        openActivityDetail(listActivities[listIndex])
      } else if (dy > 0 && listActivities.length > 0
          && listIndex === listActivities.length - 1 && currentPage && currentPage.hasMore) {
        listOffset = currentPage.nextOffset
        listIndex = 0
        reloadActivityList()
      } else if (dy < 0 && listIndex === 0 && listOffset >= 20) {
        listOffset -= 20
        listIndex = 19
        reloadActivityList()
      } else if (dy !== 0 && listActivities.length > 0) {
        listIndex = Math.max(0, Math.min(listActivities.length - 1, listIndex + dy))
        ensureListCursorVisible()
      }
      return
    }
    if (viewMode === "detail") {
      if (dx < 0) returnToList()
      else if (dy !== 0) detailIndex = Math.max(0, Math.min(1, detailIndex + dy))
    }
  }

  function activateCursor() {
    if (!service) return
    if (!cursorActive) cursorActive = true
    if (viewMode === "summary") {
      if (showUpdateCheck && summaryIndex === updateCheckIndex) {
        service.checkUpdatesNow()
        return
      }
      if (showUpdateCheck && service.updateAvailable && summaryIndex === updateReviewIndex) {
        service.launchUpdateReview()
        return
      }
      if (!currentPeriod) {
        primaryAction()
        return
      }
      var typeKey = summaryIndex === 0 ? "" : currentPeriod.byType[summaryIndex - 1].typeKey
      openActivityList(typeKey)
    } else if (viewMode === "list" && listActivities.length > 0) {
      openActivityDetail(listActivities[listIndex])
    } else if (viewMode === "detail") {
      if (detailIndex === 0) returnToList()
      else openGarminConnect()
    }
  }

  function openGarminConnect() {
    if (!detailActivity) return
    var url = Model.garminConnectUrl(String(detailActivity.activityId || ""))
    if (url === "") {
      panelNotice = "This activity cannot be opened safely."
      return
    }
    if (!Qt.openUrlExternally(url)) panelNotice = "The default browser could not be opened."
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

  onSettingsChanged: periodIndex = configuredPeriodIndex()
  onSummaryCursorCountChanged: summaryIndex = Math.min(summaryIndex, summaryCursorCount - 1)
  onOpenedChanged: if (opened) {
    periodIndex = configuredPeriodIndex()
    viewMode = "summary"
    cursorActive = false
    panelNotice = ""
    if (service && service.summaryStale) service.refresh()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }
  Component.onCompleted: periodIndex = configuredPeriodIndex()

  Connections {
    target: root.service
    function onActivityPageChanged() {
      if (root.listActivities.length === 0) root.listIndex = 0
      else root.listIndex = Math.min(root.listIndex, root.listActivities.length - 1)
    }
    function onActivityDetailMissingChanged() {
      if (root.viewMode === "detail" && root.service.activityDetailMissing) {
        root.panelNotice = "That activity is no longer in local data."
        root.viewMode = "list"
        root.reloadActivityList()
      }
    }
    function onRefreshGenerationChanged() {
      if (root.viewMode === "detail" && root.selectedActivityId !== "")
        root.service.loadActivityDetail(root.selectedActivityId)
      else if (root.viewMode === "list") root.reloadActivityList()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.hostWidget || root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(430))
    contentHeight: panel.fittedContentHeight(contentColumn.implicitHeight, Style.space(620))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function(dx, dy) { root.moveCursor(dx, dy) }
      onActivateRequested: root.activateCursor()
      onCloseRequested: root.backOrClose()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(text) {
        if (text === "r" || text === "R") {
          if (root.service) root.service.refresh()
        }
      }

      Flickable {
        id: scroll
        anchors.fill: parent
        contentWidth: width
        contentHeight: contentColumn.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Column {
          id: contentColumn
          width: scroll.width
          spacing: Style.space(14)

          PanelHero {
            width: parent.width
            title: "Garmin Insights"
            meta: root.service ? root.service.statusText : "Service loading"
            detail: root.service && root.service.demoMode ? "UNOFFICIAL · DEMO" : "UNOFFICIAL"
            foreground: root.foreground
            fontFamily: root.fontFamily
            iconComponent: Component {
              Text {
                text: "󰛂"
                color: root.service && ["offline", "rateLimited", "reconnect", "localError"].indexOf(root.service.connectionState) !== -1 ? root.urgent : root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.display
              }
            }
          }

          Text {
            visible: root.service && root.service.hasSummary
            width: parent.width
            text: root.service && root.service.hasSummary
              ? "Updated " + Qt.formatDateTime(new Date(root.service.summary.generatedMs), "ddd d MMM, HH:mm")
              : ""
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          Text {
            visible: root.panelNotice !== ""
            width: parent.width
            text: root.panelNotice
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
              width: parent.width
              spacing: Style.space(5)

              Repeater {
                model: root.periodKeys

                Button {
                  required property string modelData
                  required property int index
                  width: (contentColumn.width - Style.space(15)) / 4
                  text: Model.periodLabel(modelData)
                  selected: root.periodIndex === index
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  horizontalPadding: Style.space(4)
                  onClicked: root.periodIndex = index
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

            Row {
              visible: root.currentPeriod !== null
              width: parent.width
              spacing: Style.space(6)

              MetricCard {
                width: (parent.width - Style.space(12)) / 3
                label: "DURATION"
                value: root.currentPeriod ? Model.formatDuration(root.currentPeriod.overall.durationSeconds.value) : "—"
              }
              MetricCard {
                width: (parent.width - Style.space(12)) / 3
                label: "DISTANCE"
                value: root.currentPeriod ? Model.formatDistance(root.currentPeriod.overall.distanceMetres.value, root.imperial) : "—"
              }
              MetricCard {
                width: (parent.width - Style.space(12)) / 3
                label: "ENERGY"
                value: root.currentPeriod ? Model.formatEnergy(root.currentPeriod.overall.energyJoules.value, root.imperial) : "—"
              }
            }

            CursorSurface {
              id: browseAllSurface
              visible: root.currentPeriod !== null
              width: parent.width
              implicitHeight: browseAllRow.implicitHeight + Style.space(16)
              hasCursor: root.cursorActive && root.summaryIndex === 0
              foreground: root.foreground

              Row {
                id: browseAllRow
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.margins: Style.space(9)
                spacing: Style.space(8)

                Text {
                  width: parent.width - browseArrow.width - Style.space(8)
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
                onEntered: { root.cursorActive = true; root.summaryIndex = 0 }
                onClicked: root.openActivityList("")
              }
            }

            PanelSeparator {
              visible: root.currentPeriod && root.currentPeriod.byType.length > 0
              foreground: root.foreground
            }

            PanelSectionHeader {
              visible: root.currentPeriod && root.currentPeriod.byType.length > 0
              text: "ACTIVITY TYPES"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Column {
              width: parent.width
              spacing: Style.space(4)

              Repeater {
                id: summaryTypeRepeater
                model: root.currentPeriod ? root.currentPeriod.byType : []

                CursorSurface {
                  required property var modelData
                  required property int index
                  width: parent.width
                  implicitHeight: typeRow.implicitHeight + Style.space(10)
                  hasCursor: root.cursorActive && root.summaryIndex === index + 1
                  foreground: root.foreground

                  Row {
                    id: typeRow
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: Style.space(8)
                    anchors.rightMargin: Style.space(8)
                    spacing: Style.space(8)

                    Column {
                      width: parent.width - typeStats.width - Style.space(8)
                      spacing: Style.space(1)

                      Text {
                        width: parent.width
                        text: Model.typeLabel(modelData.typeKey)
                        textFormat: Text.PlainText
                        color: root.foreground
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.body
                        elide: Text.ElideRight
                      }

                      Text {
                        width: parent.width
                        text: Model.formatCount(modelData.activityCount)
                        color: root.dim
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                      }
                    }

                    Column {
                      id: typeStats
                      anchors.verticalCenter: parent.verticalCenter

                      Text {
                        anchors.right: parent.right
                        text: Model.formatDuration(modelData.durationSeconds.value)
                        color: root.foreground
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.bodySmall
                      }
                      Text {
                        anchors.right: parent.right
                        text: Model.formatDistance(modelData.distanceMetres.value, root.imperial)
                        color: root.dim
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                      }
                    }
                  }

                  MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onEntered: { root.cursorActive = true; root.summaryIndex = index + 1 }
                    onClicked: root.openActivityList(modelData.typeKey)
                  }
                }
              }
            }

            PanelSeparator {
              foreground: root.foreground
            }

            Column {
              width: parent.width
              spacing: Style.space(6)

              Text {
                visible: root.service && root.service.updateAvailable && root.showUpdateCheck
                width: parent.width
                text: "󰚰  Update available"
                color: root.urgent
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                font.bold: true
              }

              Row {
                width: parent.width
                spacing: Style.space(8)

                Text {
                  width: parent.width - (updateCheckButton.visible ? updateCheckButton.width + Style.space(8) : 0)
                  anchors.verticalCenter: parent.verticalCenter
                  text: "Installed version " + (root.service ? root.service.installedVersion : "Unknown")
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }

                Button {
                  id: updateCheckButton
                  visible: root.showUpdateCheck
                  text: root.service && root.service.updateCheckRunning ? "Checking…" : "Check again"
                  hasCursor: root.cursorActive && root.summaryIndex === root.updateCheckIndex
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  bordered: true
                  enabled: root.service && !root.service.updateCheckRunning
                  onHovered: function(on) {
                    if (on) { root.cursorActive = true; root.summaryIndex = root.updateCheckIndex }
                  }
                  onClicked: if (root.service) root.service.checkUpdatesNow()
                }
              }

              Button {
                id: updateReviewButton
                visible: root.service && root.service.updateAvailable && root.showUpdateCheck
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Review update"
                iconText: "󰏌"
                hasCursor: root.cursorActive && root.summaryIndex === root.updateReviewIndex
                foreground: root.foreground
                fontFamily: root.fontFamily
                bordered: true
                enabled: root.service && !root.service.updateCheckRunning
                onHovered: function(on) {
                  if (on) { root.cursorActive = true; root.summaryIndex = root.updateReviewIndex }
                }
                onClicked: if (root.service) root.service.launchUpdateReview()
              }

              Text {
                visible: root.service && root.service.updateAvailable && root.showUpdateCheck
                width: parent.width
                text: "Review the diff in the terminal. If pyproject.toml or uv.lock changed, rerun the README dependency setup, then restart the shell."
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
              }
            }

            Text {
              visible: root.currentPeriod === null
              width: parent.width
              text: root.service && root.service.connectionState === "unauthenticated"
                ? "Connect a Garmin account to create the first activity summary."
                : "No valid activity summary is available yet."
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              wrapMode: Text.WordWrap
              horizontalAlignment: Text.AlignHCenter
            }
          }

          Column {
            visible: root.viewMode === "list"
            width: parent.width
            spacing: Style.space(10)

            Row {
              width: parent.width
              spacing: Style.space(8)

              Button {
                text: "Back"
                iconText: "←"
                foreground: root.foreground
                fontFamily: root.fontFamily
                bordered: true
                onClicked: root.returnToSummary()
              }

              Column {
                width: parent.width - Style.space(88)
                anchors.verticalCenter: parent.verticalCenter
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
                  width: parent.width
                  text: Model.periodLabel(root.periodKey)
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }
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

            Column {
              width: parent.width
              spacing: Style.space(4)

              Repeater {
                id: listRepeater
                model: root.listActivities

                CursorSurface {
                  required property var modelData
                  required property int index
                  width: parent.width
                  implicitHeight: activityRow.implicitHeight + Style.space(14)
                  hasCursor: root.cursorActive && root.listIndex === index
                  foreground: root.foreground

                  Row {
                    id: activityRow
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.margins: Style.space(9)
                    spacing: Style.space(8)

                    Column {
                      width: parent.width - activityStats.width - Style.space(8)
                      spacing: Style.space(2)
                      Text {
                        width: parent.width
                        text: modelData.name === null ? Model.typeLabel(modelData.typeKey) : modelData.name
                        textFormat: Text.PlainText
                        color: root.foreground
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.body
                        font.bold: true
                        elide: Text.ElideRight
                      }
                      Text {
                        width: parent.width
                        text: Qt.formatDate(new Date(modelData.localDate + "T12:00:00"), "ddd d MMM")
                          + " · " + Model.typeLabel(modelData.typeKey)
                        textFormat: Text.PlainText
                        color: root.dim
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                        elide: Text.ElideRight
                      }
                    }

                    Column {
                      id: activityStats
                      anchors.verticalCenter: parent.verticalCenter
                      Text {
                        anchors.right: parent.right
                        text: Model.formatDuration(modelData.durationSeconds)
                        color: root.foreground
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.bodySmall
                      }
                      Text {
                        anchors.right: parent.right
                        text: Model.activityHeadline(modelData, root.imperial) + "  ›"
                        color: root.dim
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                      }
                    }
                  }

                  MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onEntered: { root.cursorActive = true; root.listIndex = index }
                    onClicked: root.openActivityDetail(modelData)
                  }
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
                enabled: root.listOffset > 0 && !root.service.activityViewRunning
                foreground: root.foreground
                fontFamily: root.fontFamily
                bordered: true
                onClicked: {
                  root.listOffset -= 20
                  root.listIndex = 0
                  root.reloadActivityList()
                }
              }
              Button {
                text: "Next"
                enabled: root.currentPage && root.currentPage.hasMore && !root.service.activityViewRunning
                foreground: root.foreground
                fontFamily: root.fontFamily
                bordered: true
                onClicked: {
                  root.listOffset = root.currentPage.nextOffset
                  root.listIndex = 0
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
              text: "Back to activities"
              iconText: "←"
              hasCursor: root.cursorActive && root.detailIndex === 0
              foreground: root.foreground
              fontFamily: root.fontFamily
              bordered: true
              onHovered: function(on) { if (on) { root.cursorActive = true; root.detailIndex = 0 } }
              onClicked: root.returnToList()
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

            Column {
              visible: root.detailActivity !== null
              width: parent.width
              spacing: Style.space(4)

              Text {
                width: parent.width
                text: root.detailActivity
                  ? (root.detailActivity.name === null ? Model.typeLabel(root.detailActivity.typeKey) : root.detailActivity.name) : ""
                textFormat: Text.PlainText
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.title
                font.bold: true
                elide: Text.ElideRight
              }
              Text {
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
            }

            Column {
              visible: root.detailActivity !== null
              width: parent.width
              spacing: Style.space(3)

              Repeater {
                model: root.detailMetrics()

                DetailMetricRow {
                  required property var modelData
                  width: parent.width
                  label: modelData.label
                  value: modelData.value
                }
              }
            }

            Button {
              visible: root.detailActivity !== null
              anchors.horizontalCenter: parent.horizontalCenter
              text: "Open in Garmin Connect"
              iconText: "󰏌"
              hasCursor: root.cursorActive && root.detailIndex === 1
              foreground: root.foreground
              fontFamily: root.fontFamily
              bordered: true
              onHovered: function(on) { if (on) { root.cursorActive = true; root.detailIndex = 1 } }
              onClicked: root.openGarminConnect()
            }
          }

          Button {
            visible: root.viewMode === "summary"
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.actionLabel()
            iconText: root.service && root.service.refreshing ? "󰦖" : "󰑐"
            iconSpinning: root.service && root.service.refreshing
            foreground: root.foreground
            fontFamily: root.fontFamily
            enabled: root.service && !root.service.processRunning
              && !(root.service.connectionState === "setup" && root.service.uvPath === "")
            bordered: true
            onClicked: root.primaryAction()
          }

          Text {
            width: parent.width
            text: root.viewMode === "summary"
              ? "Arrows browse · Enter open · R refresh · Tab · Esc"
              : (root.viewMode === "list"
                ? "↑/↓ select · →/Enter open · ←/Esc back · R refresh"
                : "↑/↓ action · Enter · ←/Esc back · R refresh")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
          }
        }
      }
    }
  }

  component MetricCard: BorderSurface {
    property string label: ""
    property string value: "—"

    implicitHeight: metricColumn.implicitHeight + Style.space(16)
    color: Style.normalFillFor(root.foreground, Color.accent)
    borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)
    radius: Style.cornerRadius

    Column {
      id: metricColumn
      anchors.centerIn: parent
      spacing: Style.space(3)

      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: label
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.letterSpacing: 1
      }
      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: value
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.bold: true
      }
    }
  }

  component DetailMetricRow: CursorSurface {
    property string label: ""
    property string value: "—"

    implicitHeight: detailMetricRow.implicitHeight + Style.space(10)
    foreground: root.foreground

    Row {
      id: detailMetricRow
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(9)
      anchors.rightMargin: Style.space(9)
      spacing: Style.space(8)

      Text {
        width: parent.width - detailMetricValue.width - Style.space(8)
        text: label
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
      }
      Text {
        id: detailMetricValue
        text: value
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        font.bold: true
      }
    }
  }
}
