pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "io.github.paulpitchford.garmin-activities"
  manageIpc: false

  property var service: null
  property var anchorItem: null
  property var hostWidget: null
  property int periodIndex: 1

  readonly property var periodKeys: ["today", "7Days", "30Days", "90Days"]
  readonly property string periodKey: periodKeys[Math.max(0, Math.min(periodIndex, periodKeys.length - 1))]
  readonly property var currentPeriod: service ? Model.periodByKey(service.summary, periodKey) : null
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.5)
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property string unitsSetting: String(setting("units", "auto"))
  readonly property bool imperial: unitsSetting === "imperial"
    || (unitsSetting === "auto" && (Qt.locale().measurementSystem === Locale.ImperialUSSystem
      || Qt.locale().measurementSystem === Locale.ImperialUKSystem))

  function configuredPeriodIndex() {
    var key = String(setting("period", "7Days"))
    var index = periodKeys.indexOf(key)
    return index >= 0 ? index : 1
  }

  function movePeriod(delta) {
    periodIndex = Math.max(0, Math.min(periodKeys.length - 1, periodIndex + delta))
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

  onSettingsChanged: periodIndex = configuredPeriodIndex()
  onOpenedChanged: if (opened) {
    periodIndex = configuredPeriodIndex()
    if (service && service.summaryStale) service.refresh()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }
  Component.onCompleted: periodIndex = configuredPeriodIndex()

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
      onMoveRequested: function(dx, dy) {
        if (dx !== 0) root.movePeriod(dx)
        else if (dy !== 0) root.movePeriod(dy)
      }
      onActivateRequested: root.primaryAction()
      onCloseRequested: root.close()
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
            title: "Garmin Activities"
            meta: root.service ? root.service.statusText : "Service loading"
            detail: root.service && root.service.demoMode ? "DEMO" : ""
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

          Column {
            visible: root.currentPeriod !== null
            width: parent.width
            spacing: Style.space(10)

            Text {
              width: parent.width
              text: root.currentPeriod ? Model.formatCount(root.currentPeriod.overall.activityCount) : ""
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.title
              font.bold: true
            }

            Row {
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
                model: root.currentPeriod ? root.currentPeriod.byType : []

                CursorSurface {
                  required property var modelData
                  width: parent.width
                  implicitHeight: typeRow.implicitHeight + Style.space(10)
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
                }
              }
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

          Button {
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
            text: "←/→ period · Enter · R refresh · Tab · Esc close"
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
}
