import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

BarWidget {
  id: root
  moduleName: "io.github.paulpitchford.garmin-insights"

  readonly property var service: bar && bar.shell ? bar.shell.serviceFor(moduleName) : null
  readonly property string selectedPeriodKey: String(setting("period", "7Days"))
  readonly property var selectedPeriod: service ? Model.periodByKey(service.summary, selectedPeriodKey) : null
  readonly property int activityCount: selectedPeriod ? selectedPeriod.overall.activityCount : 0
  readonly property bool problemState: service && ["stale", "offline", "rateLimited", "reconnect", "setup", "localError"].indexOf(service.connectionState) !== -1

  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    target.bar = root.bar
    target.settings = root.settings
    target.anchorItem = button
    target.hostWidget = root
    target.service = root.service
  }

  function configureService() {
    if (service) service.configure(setting("refreshMinutes", 30), setting("demoMode", false))
    injectPanel()
  }

  function open() {
    if (panelLoader.item) panelLoader.item.open()
  }

  function close() {
    if (panelLoader.item) panelLoader.item.close()
  }

  function toggle() {
    if (panelLoader.item) panelLoader.item.toggle()
  }

  function closeForPopoutSwitch() {
    if (panelLoader.item) panelLoader.item.closeForPopoutSwitch()
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: configureService()
  onServiceChanged: configureService()
  Component.onCompleted: configureService()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.vertical ? "󰛂" : "󰛂  " + (root.selectedPeriod ? String(root.activityCount) : "—")
    active: root.problemState
    keepSpace: true
    tooltipText: {
      var period = Model.periodLabel(root.selectedPeriodKey)
      var total = root.selectedPeriod ? Model.formatCount(root.activityCount) : "No cached summary"
      var status = root.service ? root.service.statusText : "Service loading"
      return "Garmin Insights · " + period + " · " + total + " · " + status
    }

    onPressed: function(buttonCode) {
      if (buttonCode === Qt.MiddleButton) {
        if (root.service) root.service.refresh()
      } else if (buttonCode === Qt.RightButton) {
        if (!root.service) return
        if (root.service.connectionState === "setup") root.service.launchSetup()
        else if (root.service.connectionState === "unauthenticated" || root.service.connectionState === "reconnect") root.service.launchLogin()
        else if (root.service.connectionState === "localError" && !root.service.configured) root.service.checkAuthentication()
        else root.service.refresh()
      } else {
        root.toggle()
      }
    }
  }
}
