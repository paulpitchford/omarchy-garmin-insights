import QtQuick

QtObject {
  id: root

  readonly property var modeNames: ["Overview", "Wellness", "Activities", "Settings"]
  property int modeIndex: 0
  property int wellnessViewIndex: 0
  property string activityViewMode: "summary"
  property string settingsViewMode: "main"
  property string confirmationKind: ""

  readonly property string pageKey: String(modeIndex) + ":" + String(wellnessViewIndex)
    + ":" + activityViewMode + ":" + settingsViewMode

  function beginSession() {
    modeIndex = 0
    wellnessViewIndex = 0
    activityViewMode = "summary"
    settingsViewMode = "main"
    confirmationKind = ""
  }

  function switchMode(index) {
    modeIndex = Math.max(0, Math.min(modeNames.length - 1, Number(index) || 0))
    confirmationKind = ""
  }

  function setWellnessView(index) {
    wellnessViewIndex = Math.max(0, Math.min(1, Number(index) || 0))
  }

  function setActivityView(view) {
    var value = String(view || "")
    if (["summary", "list", "detail"].indexOf(value) !== -1) activityViewMode = value
  }

  function setSettingsView(view) {
    var value = String(view || "")
    if (["main", "account"].indexOf(value) !== -1) settingsViewMode = value
  }

  function openConfirmation(kind) {
    var value = String(kind || "")
    if (["collection", "logout", "purge"].indexOf(value) !== -1)
      confirmationKind = value
  }

  function backAction() {
    if (confirmationKind !== "") {
      confirmationKind = ""
      return "confirmation"
    }
    if (modeIndex === 2 && activityViewMode === "detail") {
      activityViewMode = "list"
      return "activity-list"
    }
    if (modeIndex === 2 && activityViewMode === "list") {
      activityViewMode = "summary"
      return "activity-summary"
    }
    if (modeIndex === 3 && settingsViewMode === "account") {
      settingsViewMode = "main"
      return "settings"
    }
    return "close"
  }
}
