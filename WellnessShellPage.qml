import QtQuick
import qs.Commons
import qs.Ui

Column {
  id: root

  property var wellness: null
  property int viewIndex: 0
  property bool panelCursorActive: false
  property bool hasCursor: false
  property color foreground: Color.foreground
  property color dim: Qt.darker(foreground, 1.5)
  property string fontFamily: Style.font.family
  property int cursorIndex: 0
  readonly property int cursorCount: 1

  signal viewRequested(int index)

  function moveCursor(dx, dy) {
    if (dx !== 0) viewRequested(Math.max(0, Math.min(1, viewIndex + dx)))
  }

  function activateCursor() {
    viewRequested(viewIndex === 0 ? 1 : 0)
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

  BorderSurface {
    width: parent.width
    implicitHeight: placeholderColumn.implicitHeight + Style.space(32)
    color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.035)
    borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)
    radius: Style.cornerRadius

    Column {
      id: placeholderColumn
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.margins: Style.space(16)
      spacing: Style.space(8)

      Text {
        width: parent.width
        text: root.viewIndex === 0 ? "Wellness Today" : "Wellness Trends"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        font.bold: true
        horizontalAlignment: Text.AlignHCenter
      }

      Text {
        width: parent.width
        text: root.wellness
          ? "Validated local wellness data is available. Presentation remains disabled in this dormant shell."
          : "No validated local wellness summary is available."
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
      }
    }
  }
}
