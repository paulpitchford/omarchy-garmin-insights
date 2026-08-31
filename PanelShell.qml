pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as Controls
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "io.github.paulpitchford.garmin-insights"
  manageIpc: false

  property var service: null
  property var anchorItem: null
  property var hostWidget: null
  property bool cursorActive: false
  property string focusArea: "nav"
  property int navCursorIndex: 0
  property var scrollPositions: ({})

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.5)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property string unitsSetting: String(setting("units", "auto"))
  readonly property bool imperial: unitsSetting === "imperial"
    || (unitsSetting === "auto" && (Qt.locale().measurementSystem === Locale.ImperialUSSystem
      || Qt.locale().measurementSystem === Locale.ImperialUKSystem))
  readonly property bool wideLayout: panel.contentWidth >= Style.space(520)

  signal wellnessCollectionChangeRequested(bool enabled)
  signal logoutRequested()
  signal purgeRequested()
  signal helpRequested()

  onWellnessCollectionChangeRequested: function(enabled) {
    if (service) service.setWellnessCollection(enabled)
  }
  onLogoutRequested: if (service) service.logout()
  onPurgeRequested: if (service) service.purge()
  onHelpRequested: if (service) service.openHelp()

  function switchPanel(direction) {
    if (bar && typeof bar.switchPanelFrom === "function")
      return bar.switchPanelFrom(hostWidget || root, direction)
    return false
  }

  function primaryAction() {
    if (!service) return
    if (service.connectionState === "setup") service.launchSetup()
    else if (service.connectionState === "unauthenticated"
        || service.connectionState === "reconnect") service.launchLogin()
    else if (service.connectionState === "localError" && !service.configured)
      service.checkAuthentication()
    else service.refresh()
  }

  function actionLabel() {
    if (!service) return "Service loading"
    if (service.connectionState === "setup")
      return service.uvPath === "" ? "Install uv to continue" : "Set up backend"
    if (service.connectionState === "unauthenticated") return "Connect Garmin"
    if (service.connectionState === "reconnect") return "Reconnect Garmin"
    if (service.connectionState === "localError") return "Retry Garmin backend"
    return service.refreshing ? "Refreshing Garmin insights" : "Refresh Garmin insights"
  }

  function currentPage() {
    if (session.modeIndex === 0) return overviewPage
    if (session.modeIndex === 1) return wellnessPage
    if (session.modeIndex === 2) return activitiesPage
    return settingsPage
  }

  function saveScroll() {
    scrollPositions[session.pageKey] = pageScroll.contentY
  }

  function restoreScroll() {
    var key = session.pageKey
    Qt.callLater(function() {
      if (!pageScroll) return
      pageScroll.contentY = Math.max(0, Math.min(Number(root.scrollPositions[key] || 0),
        Math.max(0, pageScroll.contentHeight - pageScroll.height)))
    })
  }

  function followKeyboardCursor(delta) {
    if (delta === 0) return
    Qt.callLater(function() {
      pageScroll.contentY = Math.max(0, Math.min(
        pageScroll.contentY + delta * Style.space(56),
        Math.max(0, pageScroll.contentHeight - pageScroll.height)))
    })
  }

  function switchMode(index) {
    saveScroll()
    session.switchMode(index)
    navCursorIndex = session.modeIndex
    focusArea = "nav"
    restoreScroll()
  }

  function setWellnessView(index) {
    saveScroll()
    session.setWellnessView(index)
    wellnessPage.cursorIndex = 0
    restoreScroll()
  }

  function setActivityView(view) {
    saveScroll()
    session.setActivityView(view)
    restoreScroll()
  }

  function setSettingsView(view) {
    saveScroll()
    session.setSettingsView(view)
    settingsPage.cursorIndex = 0
    restoreScroll()
  }

  function persistSettings(values) {
    var entry = { id: moduleName }
    for (var existing in settings) if (existing !== "id") entry[existing] = settings[existing]
    for (var key in values) entry[key] = values[key]
    settings = entry
    if (hostWidget && "settings" in hostWidget) hostWidget.settings = entry
    if (bar && bar.shell && typeof bar.shell.updateEntryInline === "function")
      bar.shell.updateEntryInline(moduleName, entry)
  }

  function runUpdateAction() {
    if (!service || service.updateCheckRunning) return
    if (service.updateAvailable) service.launchUpdateReview()
    else service.checkUpdatesNow()
  }

  function openConfirmation(kind) {
    session.openConfirmation(kind)
    confirmation.selectedIndex = 0
  }

  function cancelConfirmation() {
    session.confirmationKind = ""
    confirmation.selectedIndex = 0
  }

  function confirmSensitiveAction() {
    var kind = session.confirmationKind
    cancelConfirmation()
    if (kind === "collection")
      wellnessCollectionChangeRequested(!settingsPage.collectionEnabled)
    else if (kind === "logout") logoutRequested()
    else if (kind === "purge") purgeRequested()
  }

  function confirmationMessage() {
    if (session.confirmationKind === "collection")
      return settingsPage.collectionEnabled
        ? "Stop future wellness collection? Existing wellness data remains until explicitly purged."
        : "Enable wellness collection? Approved Garmin wellness requests will resume on their bounded cadence."
    if (session.confirmationKind === "logout")
      return "Log out of Garmin? Saved tokens will be removed, but retained local insights will remain."
    if (session.confirmationKind === "purge")
      return "Purge authentication, activities, wellness, and display caches? This cannot be undone."
    return ""
  }

  function confirmationButtonText() {
    if (session.confirmationKind === "collection")
      return settingsPage.collectionEnabled ? "Stop" : "Enable"
    if (session.confirmationKind === "logout") return "Log out"
    return "Purge data"
  }

  function backOrClose() {
    if (session.confirmationKind !== "") {
      cancelConfirmation()
      return
    }
    if (session.modeIndex === 2 && session.activityViewMode !== "summary") {
      activitiesPage.back()
      return
    }
    if (session.modeIndex === 3 && session.settingsViewMode === "account") {
      setSettingsView("main")
      return
    }
    close()
  }

  function moveCursor(dx, dy) {
    pagePointerGate.reset()
    cursorActive = true
    if (session.confirmationKind !== "") {
      if (dx !== 0 || dy !== 0) confirmation.selectedIndex = confirmation.selectedIndex === 0 ? 1 : 0
      return
    }
    if (focusArea === "header") {
      if (dy > 0) focusArea = "nav"
      return
    }
    if (focusArea === "nav") {
      if (dx !== 0) switchMode(navCursorIndex + dx)
      else if (dy < 0) focusArea = "header"
      else if (dy > 0) {
        currentPage().cursorIndex = 0
        focusArea = "content"
      }
      return
    }
    var page = currentPage()
    var nestedActivity = session.modeIndex === 2 && session.activityViewMode !== "summary"
    var nestedSettings = session.modeIndex === 3 && session.settingsViewMode !== "main"
    if (dy < 0 && page.cursorIndex === 0 && !nestedActivity && !nestedSettings) {
      focusArea = "nav"
      return
    }
    page.moveCursor(dx, dy)
    followKeyboardCursor(dy)
  }

  function activateCursor() {
    pagePointerGate.reset()
    cursorActive = true
    if (session.confirmationKind !== "") {
      if (confirmation.selectedIndex === 0) cancelConfirmation()
      else confirmSensitiveAction()
      return
    }
    if (focusArea === "header") {
      primaryAction()
      return
    }
    if (focusArea === "nav") {
      switchMode(navCursorIndex)
      return
    }
    currentPage().activateCursor()
  }

  function footerText() {
    if (session.confirmationKind !== "") return "←/→ choose · Enter confirm · Esc cancel"
    if (focusArea === "header") return "Enter refresh · ↓ navigation · Tab switch · Esc close"
    if (session.modeIndex === 2 && session.activityViewMode === "list")
      return "↑/↓ select · →/Enter open · ←/Esc back · R refresh · Tab switch"
    if (session.modeIndex === 2 && session.activityViewMode === "detail")
      return "↑/↓ action · Enter · ←/Esc back · R refresh · Tab switch"
    return "Arrows browse · Enter open · R refresh · Tab switch · Esc back/close"
  }

  onOpenedChanged: if (opened) {
    session.beginSession()
    activitiesPage.resetForSession(setting("period", "7Days"))
    navCursorIndex = 0
    focusArea = "nav"
    cursorActive = false
    pagePointerGate.reset()
    scrollPositions = ({})
    pageScroll.contentY = 0
    if (service && service.summaryStale) service.refresh()
    Qt.callLater(function() {
      keyCatcher.forceActiveFocus()
      if (service) service.loadLatestActivity()
    })
  }

  Connections {
    target: root.service
    function onSummaryChanged() {
      if (root.opened && root.service)
        Qt.callLater(function() { root.service.loadLatestActivity() })
    }
    function onRefreshingChanged() {
      if (root.opened && root.service && !root.service.refreshing)
        Qt.callLater(function() { root.service.loadLatestActivity() })
    }
  }

  PanelSession { id: session }

  PointerMoveGate {
    id: pagePointerGate
    referenceItem: keyCatcher
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.hostWidget || root
    bar: root.bar
    open: root.opened
    centerOnBar: false
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(600))
    contentHeight: panel.fittedContentHeight(
      Style.space(session.modeIndex === 0 ? 560 : 760),
      Style.space(session.modeIndex === 0 ? 600 : 800))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function(dx, dy) { root.moveCursor(dx, dy) }
      onActivateRequested: root.activateCursor()
      onCloseRequested: root.backOrClose()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(text) {
        if (text === "r" || text === "R") root.primaryAction()
      }

      Column {
        id: shellHeader
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: Style.space(9)

        PanelHero {
          width: parent.width
          title: "Garmin Insights"
          meta: root.service ? root.service.statusText : "Service loading"
          foreground: root.foreground
          fontFamily: root.fontFamily
          iconComponent: Component {
            Text {
              text: "G"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.display
              font.bold: true
            }
          }
          trailingControl: Component {
            PanelActionButton {
              iconText: root.service && root.service.refreshing ? "…" : "↻"
              tooltipText: root.actionLabel()
              Accessible.name: root.actionLabel()
              hasCursor: root.cursorActive && root.focusArea === "header"
              bordered: true
              foreground: root.foreground
              fontFamily: root.fontFamily
              enabled: root.service && !root.service.processRunning
                && !(root.service.connectionState === "setup" && root.service.uvPath === "")
              onHovered: function(on) { if (on) { root.cursorActive = true; root.focusArea = "header" } }
              onClicked: root.primaryAction()
            }
          }
        }

        DomainStatusRow {
          width: parent.width
          service: root.service
          foreground: root.foreground
          urgent: root.urgent
          fontFamily: root.fontFamily
        }

        Row {
          id: topNavigation
          width: parent.width
          spacing: Style.space(6)

          Repeater {
            model: session.modeNames

            Button {
              required property string modelData
              required property int index
              width: (topNavigation.width - topNavigation.spacing * 3) / 4
              text: modelData
              tooltipText: "Open " + modelData
              Accessible.name: "Open " + modelData
              selected: session.modeIndex === index
              hasCursor: root.cursorActive && root.focusArea === "nav"
                && root.navCursorIndex === index
              bordered: true
              foreground: root.foreground
              fontFamily: root.fontFamily
              fontSize: Style.font.bodySmall
              horizontalPadding: Style.space(3)
              onHovered: function(on) {
                if (on) {
                  root.cursorActive = true
                  root.focusArea = "nav"
                  root.navCursorIndex = index
                }
              }
              onClicked: root.switchMode(index)
            }
          }
        }

        PanelSeparator { width: parent.width; foreground: root.foreground }
      }

      Flickable {
        id: pageScroll
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: shellHeader.bottom
        anchors.topMargin: Style.space(10)
        anchors.bottom: shellFooter.top
        anchors.bottomMargin: Style.space(10)
        contentWidth: width
        contentHeight: pageColumn.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        Controls.ScrollBar.vertical: Controls.ScrollBar {
          policy: Controls.ScrollBar.AsNeeded
          active: pageScroll.interactive
        }

        HoverHandler {
          id: pagePointer
          onPointChanged: {
            if (!hovered || !pagePointerGate.moved(pageScroll, {
                x: point.position.x, y: point.position.y
              })) return
            root.cursorActive = true
            root.focusArea = "content"
          }
        }

        Column {
          id: pageColumn
          width: pageScroll.width

          OverviewShellPage {
            id: overviewPage
            visible: session.modeIndex === 0
            width: parent.width
            service: root.service
            wideLayout: root.wideLayout
            imperial: root.imperial
            panelCursorActive: root.cursorActive
            hasCursor: root.focusArea === "content"
            foreground: root.foreground
            urgent: root.urgent
            dim: root.dim
            fontFamily: root.fontFamily
            onWellnessRequested: root.switchMode(1)
            onActivitiesRequested: root.switchMode(2)
          }

          WellnessShellPage {
            id: wellnessPage
            visible: session.modeIndex === 1
            width: parent.width
            wellness: root.service ? root.service.wellness : null
            viewIndex: session.wellnessViewIndex
            wideLayout: root.wideLayout
            panelCursorActive: root.cursorActive
            hasCursor: root.focusArea === "content"
            nowMs: root.service ? root.service.nowMs : Date.now()
            foreground: root.foreground
            urgent: root.urgent
            dim: root.dim
            fontFamily: root.fontFamily
            onViewRequested: function(index) { root.setWellnessView(index) }
          }

          ActivitiesView {
            id: activitiesPage
            visible: session.modeIndex === 2
            width: parent.width
            service: root.service
            viewMode: session.activityViewMode
            imperial: root.imperial
            panelCursorActive: root.cursorActive
            hasCursor: root.focusArea === "content"
            foreground: root.foreground
            urgent: root.urgent
            dim: root.dim
            fontFamily: root.fontFamily
            onViewRequested: function(view) { root.setActivityView(view) }
          }

          SettingsView {
            id: settingsPage
            visible: session.modeIndex === 3
            width: parent.width
            service: root.service
            settings: root.settings
            viewMode: session.settingsViewMode
            wideLayout: root.wideLayout
            panelCursorActive: root.cursorActive
            hasCursor: root.focusArea === "content"
            foreground: root.foreground
            urgent: root.urgent
            dim: root.dim
            fontFamily: root.fontFamily
            onSettingsRequested: function(values) { root.persistSettings(values) }
            onUpdateActionRequested: root.runUpdateAction()
            onHelpRequested: root.helpRequested()
            onAccountRequested: root.setSettingsView("account")
            onBackRequested: root.setSettingsView("main")
            onConfirmationRequested: function(kind) { root.openConfirmation(kind) }
          }
        }
      }

      Column {
        id: shellFooter
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        spacing: Style.space(5)

        PanelSeparator { width: parent.width; foreground: root.foreground }

        Text {
          width: parent.width
          text: root.footerText()
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          horizontalAlignment: Text.AlignHCenter
          wrapMode: Text.WordWrap
        }
      }

      ConfirmDialog {
        id: confirmation
        anchors.fill: parent
        opened: session.confirmationKind !== ""
        message: root.confirmationMessage()
        cancelText: "Cancel"
        confirmText: root.confirmationButtonText()
        foreground: root.foreground
        background: Color.popups.background
        selectedText: session.confirmationKind === "collection" ? root.foreground : root.urgent
        fontFamily: root.fontFamily
        onCanceled: root.cancelConfirmation()
        onConfirmed: root.confirmSensitiveAction()
      }
    }
  }
}
