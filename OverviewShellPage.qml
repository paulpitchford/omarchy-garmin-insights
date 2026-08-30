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
  property color dim: Qt.darker(foreground, 1.5)
  property string fontFamily: Style.font.family

  signal wellnessRequested()
  signal activitiesRequested()

  readonly property var week: service ? Model.periodByKey(service.summary, "7Days") : null
  readonly property var weekTrend: service ? Model.trendByKey(service.activityTrends, "7Days") : null
  readonly property int cursorCount: 2
  property int cursorIndex: 0

  function moveCursor(dx, dy) {
    if (dy !== 0) cursorIndex = Math.max(0, Math.min(cursorCount - 1, cursorIndex + dy))
  }

  function activateCursor() {
    if (cursorIndex === 0) wellnessRequested()
    else activitiesRequested()
  }

  spacing: Style.space(12)

  Item {
    width: parent.width
    implicitHeight: Math.max(overviewTitle.implicitHeight, wellnessButton.implicitHeight)

    Text {
      id: overviewTitle
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      text: "Wellness today"
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.title
      font.bold: true
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
    spacing: Style.space(8)

    Repeater {
      model: ["BODY BATTERY", "SLEEP", "STEPS"]

      BorderSurface {
        required property string modelData
        width: (signals.width - signals.spacing * (signals.columns - 1)) / signals.columns
        implicitHeight: signalColumn.implicitHeight + Style.space(18)
        color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.035)
        borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)
        radius: Style.cornerRadius

        Column {
          id: signalColumn
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.margins: Style.space(9)
          spacing: Style.space(3)

          Text {
            width: parent.width
            text: modelData
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
            font.letterSpacing: 0.7
            elide: Text.ElideRight
          }
          Text {
            width: parent.width
            text: "—"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
          }
          Text {
            width: parent.width
            text: root.service && root.service.wellness
              ? "Presentation remains disabled"
              : "No local value"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }
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

      Text {
        width: parent.width
        text: root.week
          ? Model.formatDuration(root.week.overall.durationSeconds.value)
            + " · " + Model.formatDistance(root.week.overall.distanceMetres.value, root.imperial)
            + "  ›"
          : "Open Activities  ›"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        horizontalAlignment: Text.AlignRight
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
}
