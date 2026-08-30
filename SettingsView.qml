pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Ui

Column {
  id: root

  property var service: null
  property var settings: ({})
  property string viewMode: "main"
  property bool wideLayout: true
  property bool panelCursorActive: false
  property bool hasCursor: false
  property color foreground: Color.foreground
  property color urgent: Color.urgent
  property color dim: Qt.darker(foreground, 1.5)
  property string fontFamily: Style.font.family
  property int cursorIndex: 0

  readonly property int cursorCount: viewMode === "main" ? 7 : 3
  readonly property var unitKeys: ["auto", "metric", "imperial"]
  readonly property var unitLabels: ["Auto", "Metric", "Imperial"]
  readonly property int unitsIndex: Math.max(0, unitKeys.indexOf(String(setting("units", "auto"))))
  readonly property int refreshMinutes: normalizedCadence(setting("refreshMinutes", 30))
  readonly property var cadenceValues: cadenceChoices(refreshMinutes)
  readonly property var cadenceLabels: cadenceValues.map(function(value) { return value + " min" })
  readonly property int cadenceIndex: cadenceValues.indexOf(refreshMinutes)
  readonly property bool updateChecksEnabled: setting("checkForUpdates", true) !== false
  readonly property bool collectionEnabled: !service || !service.wellness
    ? true : service.wellness.collectionEnabled === true
  readonly property bool sensitiveActionsEnabled: service && !service.demoMode
    && !service.processRunning

  signal settingsRequested(var values)
  signal updateActionRequested()
  signal helpRequested()
  signal accountRequested()
  signal backRequested()
  signal confirmationRequested(string kind)

  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  function normalizedCadence(value) {
    var minutes = Math.round(Number(value) / 5) * 5
    if (!isFinite(minutes)) minutes = 30
    return Math.max(5, Math.min(360, minutes))
  }

  function cadenceChoices(minutes) {
    var values = []
    var candidates = [Math.max(5, minutes - 5), minutes, Math.min(360, minutes + 5)]
    for (var index = 0; index < candidates.length; index++)
      if (values.indexOf(candidates[index]) === -1) values.push(candidates[index])
    return values
  }

  function setCursor(index) {
    cursorIndex = Math.max(0, Math.min(cursorCount - 1, index))
  }

  function moveCursor(dx, dy) {
    if (dy !== 0) setCursor(cursorIndex + dy)
    if (dx === 0 || viewMode !== "main") return
    if (cursorIndex === 1) {
      var nextUnits = Math.max(0, Math.min(unitKeys.length - 1, unitsIndex + dx))
      settingsRequested({ units: unitKeys[nextUnits] })
    } else if (cursorIndex === 2) {
      settingsRequested({ refreshMinutes: normalizedCadence(refreshMinutes + dx * 5) })
    } else if (cursorIndex === 3) {
      settingsRequested({ checkForUpdates: dx > 0 })
    }
  }

  function activateCursor() {
    if (viewMode === "account") {
      if (cursorIndex === 0) backRequested()
      else if (sensitiveActionsEnabled && cursorIndex === 1) confirmationRequested("logout")
      else if (sensitiveActionsEnabled) confirmationRequested("purge")
      return
    }
    if (cursorIndex === 0 && sensitiveActionsEnabled) confirmationRequested("collection")
    else if (cursorIndex === 1) settingsRequested({ units: unitKeys[(unitsIndex + 1) % unitKeys.length] })
    else if (cursorIndex === 2)
      settingsRequested({ refreshMinutes: normalizedCadence(refreshMinutes + 5) })
    else if (cursorIndex === 3) settingsRequested({ checkForUpdates: !updateChecksEnabled })
    else if (cursorIndex === 4) updateActionRequested()
    else if (cursorIndex === 5) helpRequested()
    else accountRequested()
  }

  spacing: Style.space(12)

  Column {
    visible: root.viewMode === "main"
    width: parent.width
    spacing: Style.space(12)

    Item {
      width: parent.width
      implicitHeight: Math.max(settingsTitle.implicitHeight, versionText.implicitHeight)

      Text {
        id: settingsTitle
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        text: "Settings"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        font.bold: true
      }
      Text {
        id: versionText
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        text: "VERSION " + (root.service ? root.service.installedVersion : "Unknown")
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        font.letterSpacing: 0.7
      }
    }

    PanelSectionHeader {
      text: "PREFERENCES"
      foreground: root.foreground
      fontFamily: root.fontFamily
    }

    BorderSurface {
      width: parent.width
      implicitHeight: preferenceColumn.implicitHeight + Style.space(20)
      color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.035)
      borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)
      radius: Style.cornerRadius

      Column {
        id: preferenceColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.margins: Style.space(10)
        spacing: Style.space(9)

        ActionSetting {
          width: parent.width
          title: "Wellness collection"
          detail: root.collectionEnabled
            ? "On · stopping future requests retains local data"
            : "Off · retained local data remains"
          actionText: root.collectionEnabled ? "Stop collection…" : "Enable collection…"
          settingIndex: 0
          actionEnabled: root.sensitiveActionsEnabled
          onTriggered: root.confirmationRequested("collection")
        }
        PanelSeparator { width: parent.width; foreground: root.foreground }
        ChoiceSetting {
          width: parent.width
          title: "Units"
          detail: "Converted only for presentation"
          settingIndex: 1
          options: root.unitLabels
          selectedIndex: root.unitsIndex
          onSelected: function(index) { root.settingsRequested({ units: root.unitKeys[index] }) }
        }
        PanelSeparator { width: parent.width; foreground: root.foreground }
        ChoiceSetting {
          width: parent.width
          title: "Activity refresh"
          detail: "Wellness keeps its separate bounded cadence"
          settingIndex: 2
          options: root.cadenceLabels
          selectedIndex: root.cadenceIndex
          onSelected: function(index) {
            root.settingsRequested({ refreshMinutes: root.cadenceValues[index] })
          }
        }
        PanelSeparator { width: parent.width; foreground: root.foreground }
        ChoiceSetting {
          width: parent.width
          title: "Update checks"
          detail: "Fixed public Git check, at most once per 24 hours"
          settingIndex: 3
          options: ["Off", "On"]
          selectedIndex: root.updateChecksEnabled ? 1 : 0
          onSelected: function(index) { root.settingsRequested({ checkForUpdates: index === 1 }) }
        }
      }
    }

    PanelSectionHeader {
      text: "STATUS"
      foreground: root.foreground
      fontFamily: root.fontFamily
    }

    DomainStatusRow {
      width: parent.width
      service: root.service
      foreground: root.foreground
      urgent: root.urgent
      fontFamily: root.fontFamily
    }

    ActionSetting {
      width: parent.width
      title: root.service && root.service.updateAvailable ? "Update available" : "Plugin updates"
      detail: root.service && root.service.updateAvailable
        ? "Review the update in a visible terminal"
        : "Check the supported install against the fixed public repository"
      actionText: root.service && root.service.updateAvailable ? "Review update" : "Check now"
      settingIndex: 4
      actionEnabled: root.service && root.service.updateChecksEnabled
        && root.service.updateSupported && !root.service.updateCheckRunning
      onTriggered: root.updateActionRequested()
    }

    Grid {
      id: secondaryActions
      width: parent.width
      columns: root.wideLayout ? 2 : 1
      columnSpacing: Style.space(8)
      rowSpacing: Style.space(8)

      Button {
        width: (secondaryActions.width - secondaryActions.columnSpacing
          * (secondaryActions.columns - 1)) / secondaryActions.columns
        text: "Help and privacy"
        iconText: "?"
        tooltipText: "Open Garmin Insights help and privacy"
        Accessible.name: "Open Garmin Insights help and privacy"
        hasCursor: root.panelCursorActive && root.hasCursor && root.cursorIndex === 5
        bordered: true
        foreground: root.foreground
        fontFamily: root.fontFamily
        onHovered: function(on) { if (on) root.setCursor(5) }
        onClicked: root.helpRequested()
      }

      Button {
        width: (secondaryActions.width - secondaryActions.columnSpacing
          * (secondaryActions.columns - 1)) / secondaryActions.columns
        text: "Account and data"
        iconText: "→"
        tooltipText: "Manage Garmin connection and retained local data"
        Accessible.name: "Manage Garmin connection and retained local data"
        hasCursor: root.panelCursorActive && root.hasCursor && root.cursorIndex === 6
        bordered: true
        foreground: root.foreground
        fontFamily: root.fontFamily
        onHovered: function(on) { if (on) root.setCursor(6) }
        onClicked: root.accountRequested()
      }
    }
  }

  Column {
    visible: root.viewMode === "account"
    width: parent.width
    spacing: Style.space(12)

    Button {
      text: "Back to Settings"
      iconText: "←"
      tooltipText: "Back to Settings"
      Accessible.name: "Back to Settings"
      hasCursor: root.panelCursorActive && root.hasCursor && root.cursorIndex === 0
      bordered: true
      foreground: root.foreground
      fontFamily: root.fontFamily
      onHovered: function(on) { if (on) root.setCursor(0) }
      onClicked: root.backRequested()
    }

    Text {
      width: parent.width
      text: "Account and data"
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.title
      font.bold: true
    }

    PanelSectionHeader {
      text: "SENSITIVE ACTIONS"
      foreground: root.foreground
      fontFamily: root.fontFamily
    }

    ActionSetting {
      width: parent.width
      title: "Garmin connection"
      detail: "Logout removes saved tokens but retains local insights"
      actionText: "Log out…"
      settingIndex: 1
      actionEnabled: root.sensitiveActionsEnabled
      onTriggered: root.confirmationRequested("logout")
    }

    ActionSetting {
      width: parent.width
      title: "Retained local data"
      detail: "Purge removes authentication, activities, wellness, and display caches"
      actionText: "Purge…"
      settingIndex: 2
      urgentAction: true
      actionEnabled: root.sensitiveActionsEnabled
      onTriggered: root.confirmationRequested("purge")
    }

    Text {
      width: parent.width
      text: "Stopping wellness collection, logging out, and purging are separate actions. Each requires explicit confirmation."
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      wrapMode: Text.WordWrap
    }
  }

  component ActionSetting: CursorSurface {
    id: actionSetting
    property string title: ""
    property string detail: ""
    property string actionText: ""
    property int settingIndex: -1
    property bool urgentAction: false
    property bool actionEnabled: true
    signal triggered()

    implicitHeight: (root.wideLayout ? actionRow.implicitHeight
      : narrowActionColumn.implicitHeight) + Style.space(16)
    hasCursor: root.panelCursorActive && root.hasCursor
      && root.cursorIndex === actionSetting.settingIndex
    foreground: root.foreground

    Row {
      id: actionRow
      visible: root.wideLayout
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.margins: Style.space(8)
      spacing: Style.space(10)

      Column {
        width: parent.width - actionButton.width - parent.spacing
        spacing: Style.space(2)
        Text {
          width: parent.width
          text: actionSetting.title
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          font.bold: true
          wrapMode: Text.WordWrap
        }
        Text {
          width: parent.width
          text: actionSetting.detail
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }
      }

      Button {
        id: actionButton
        anchors.verticalCenter: parent.verticalCenter
        text: actionSetting.actionText
        tooltipText: actionSetting.actionText + ": " + actionSetting.title
        Accessible.name: tooltipText
        enabled: actionSetting.actionEnabled
        bordered: true
        foreground: actionSetting.urgentAction ? root.urgent : root.foreground
        fontFamily: root.fontFamily
        onHovered: function(on) { if (on) root.setCursor(actionSetting.settingIndex) }
        onClicked: actionSetting.triggered()
      }
    }

    Column {
      id: narrowActionColumn
      visible: !root.wideLayout
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.margins: Style.space(8)
      spacing: Style.space(6)

      Text {
        width: parent.width
        text: actionSetting.title
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.bold: true
        wrapMode: Text.WordWrap
      }
      Text {
        width: parent.width
        text: actionSetting.detail
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
      Button {
        width: parent.width
        text: actionSetting.actionText
        tooltipText: actionSetting.actionText + ": " + actionSetting.title
        Accessible.name: tooltipText
        enabled: actionSetting.actionEnabled
        bordered: true
        foreground: actionSetting.urgentAction ? root.urgent : root.foreground
        fontFamily: root.fontFamily
        onHovered: function(on) { if (on) root.setCursor(actionSetting.settingIndex) }
        onClicked: actionSetting.triggered()
      }
    }
  }

  component ChoiceSetting: Column {
    id: choiceSetting
    property string title: ""
    property string detail: ""
    property int settingIndex: -1
    property var options: []
    property int selectedIndex: 0
    signal selected(int index)

    spacing: Style.space(6)

    Grid {
      id: choiceLabels
      width: parent.width
      columns: root.wideLayout ? 2 : 1
      columnSpacing: Style.space(8)
      rowSpacing: Style.space(2)
      Text {
        width: root.wideLayout ? choiceLabels.width * 0.40 : choiceLabels.width
        text: choiceSetting.title
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.bold: true
        wrapMode: Text.WordWrap
      }
      Text {
        width: root.wideLayout
          ? choiceLabels.width * 0.60 - choiceLabels.columnSpacing : choiceLabels.width
        text: choiceSetting.detail
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        horizontalAlignment: root.wideLayout ? Text.AlignRight : Text.AlignLeft
        wrapMode: Text.WordWrap
      }
    }

    Row {
      id: optionRow
      width: parent.width
      spacing: Style.space(5)

      Repeater {
        model: choiceSetting.options

        Button {
          required property string modelData
          required property int index
          width: (optionRow.width - optionRow.spacing
            * Math.max(0, choiceSetting.options.length - 1))
            / Math.max(1, choiceSetting.options.length)
          text: modelData
          tooltipText: choiceSetting.title + ": " + modelData
          Accessible.name: tooltipText
          selected: choiceSetting.selectedIndex === index
          hasCursor: root.panelCursorActive && root.hasCursor
            && root.cursorIndex === choiceSetting.settingIndex
            && choiceSetting.selectedIndex === index
          bordered: true
          foreground: root.foreground
          fontFamily: root.fontFamily
          fontSize: Style.font.caption
          horizontalPadding: Style.space(3)
          onHovered: function(on) { if (on) root.setCursor(choiceSetting.settingIndex) }
          onClicked: choiceSetting.selected(index)
        }
      }
    }
  }
}
