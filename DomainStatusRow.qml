pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Ui

Grid {
  id: root

  property var service: null
  property color foreground: Color.foreground
  property color urgent: Color.urgent
  property string fontFamily: Style.font.family

  readonly property color dim: Qt.darker(foreground, 1.5)
  readonly property bool activityProblem: service
    && ["offline", "rateLimited", "reconnect", "localError", "stale"].indexOf(
      service.connectionState) !== -1
  readonly property int wellnessFailureCount: sourceCount(false)
  readonly property int wellnessUnsupportedCount: sourceCount(true)
  readonly property bool wellnessProblem: service && (wellnessFailureCount > 0
    || (service.wellnessCacheError !== "" && service.wellnessCacheError !== "missing"))
  readonly property string activityText: {
    if (!service) return "Service loading"
    if (service.hasSummary)
      return "Updated " + Qt.formatDateTime(new Date(service.summary.generatedMs), "d MMM, HH:mm")
    return service.statusText
  }
  readonly property string wellnessText: {
    if (!service) return "Service loading"
    if (service.wellness) {
      var prefix = wellnessFailureCount > 0
        ? wellnessFailureCount + (wellnessFailureCount === 1 ? " source failed · " : " sources failed · ")
        : wellnessUnsupportedCount > 0
          ? wellnessUnsupportedCount + (wellnessUnsupportedCount === 1 ? " unsupported · " : " unsupported · ")
          : "Updated "
      return prefix + Qt.formatDateTime(new Date(service.wellness.generatedMs), "d MMM, HH:mm")
    }
    if (service.wellnessCacheError === "missing" || service.wellnessCacheError === "")
      return "No local wellness summary"
    return "Local wellness data unavailable"
  }

  function sourceCount(unsupportedOnly) {
    if (!service || !service.wellness || !Array.isArray(service.wellness.sources)) return 0
    var count = 0
    for (var index = 0; index < service.wellness.sources.length; index++) {
      var failure = service.wellness.sources[index].failure
      if ((unsupportedOnly && failure === "unsupported")
          || (!unsupportedOnly && failure !== null && failure !== "unsupported")) count++
    }
    return count
  }

  columns: width >= Style.space(420) ? 2 : 1
  columnSpacing: Style.space(8)
  rowSpacing: Style.space(8)

  DomainStamp {
    width: (root.width - root.columnSpacing * (root.columns - 1)) / root.columns
    title: "ACTIVITIES"
    valueText: root.activityText
    problem: root.activityProblem
  }

  DomainStamp {
    width: (root.width - root.columnSpacing * (root.columns - 1)) / root.columns
    title: "WELLNESS"
    valueText: root.wellnessText
    problem: root.wellnessProblem
  }

  component DomainStamp: BorderSurface {
    id: stamp
    property string title: ""
    property string valueText: ""
    property bool problem: false

    implicitHeight: stampColumn.implicitHeight + Style.space(12)
    color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.035)
    borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)
    radius: Style.cornerRadius

    Column {
      id: stampColumn
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(7)
      anchors.rightMargin: Style.space(7)
      spacing: Style.space(1)

      Text {
        width: parent.width
        text: stamp.title
        color: stamp.problem ? root.urgent : root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        font.letterSpacing: 0.7
        elide: Text.ElideRight
      }

      Text {
        width: parent.width
        text: stamp.valueText
        textFormat: Text.PlainText
        color: stamp.problem ? root.urgent : root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }
  }
}
