import QtQuick
import QtTest
import "../.."

TestCase {
  name: "GarminPanelSession"

  Component {
    id: sessionComponent
    PanelSession {}
  }

  function createSession() {
    return createTemporaryObject(sessionComponent, this)
  }

  function test_session_opens_on_overview() {
    var session = createSession()
    session.modeIndex = 3
    session.wellnessViewIndex = 1
    session.activityViewMode = "detail"
    session.settingsViewMode = "account"
    session.confirmationKind = "purge"

    session.beginSession()

    compare(session.modeIndex, 0)
    compare(session.wellnessViewIndex, 0)
    compare(session.activityViewMode, "summary")
    compare(session.settingsViewMode, "main")
    compare(session.confirmationKind, "")
  }

  function test_nested_selection_survives_top_level_switches() {
    var session = createSession()
    session.setWellnessView(1)
    session.setActivityView("list")

    session.switchMode(3)
    session.switchMode(1)

    compare(session.wellnessViewIndex, 1)
    compare(session.activityViewMode, "list")
    compare(session.pageKey, "1:1:list:main")
  }

  function test_back_unwinds_confirmation_before_nested_page() {
    var session = createSession()
    session.switchMode(3)
    session.setSettingsView("account")
    session.openConfirmation("purge")

    compare(session.backAction(), "confirmation")
    compare(session.settingsViewMode, "account")
    compare(session.backAction(), "settings")
    compare(session.settingsViewMode, "main")
    compare(session.backAction(), "close")
  }

  function test_activity_back_unwinds_detail_then_list() {
    var session = createSession()
    session.switchMode(2)
    session.setActivityView("detail")

    compare(session.backAction(), "activity-list")
    compare(session.activityViewMode, "list")
    compare(session.backAction(), "activity-summary")
    compare(session.activityViewMode, "summary")
    compare(session.backAction(), "close")
  }

  function test_invalid_nested_states_are_ignored() {
    var session = createSession()

    session.setWellnessView(99)
    session.setActivityView("remote-url")
    session.setSettingsView("tokens")
    session.openConfirmation("upload")

    compare(session.wellnessViewIndex, 1)
    compare(session.activityViewMode, "summary")
    compare(session.settingsViewMode, "main")
    compare(session.confirmationKind, "")
  }
}
