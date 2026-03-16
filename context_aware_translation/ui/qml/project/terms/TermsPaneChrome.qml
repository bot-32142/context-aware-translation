import QtQuick
import QtQuick.Controls

Rectangle {
    id: root
    objectName: "termsPaneChrome"
    color: "#f4efe6"
    width: parent ? parent.width : 960
    implicitHeight: contentColumn.implicitHeight + 36

    signal buildRequested
    signal translateRequested
    signal reviewRequested
    signal filterRequested
    signal importRequested
    signal exportRequested

    property string titleText: termsPane ? termsPane.title : "Terms"
    property bool showTitle: termsPane ? termsPane.show_title : true
    property string tipText: termsPane ? termsPane.tip_text : ""
    property string buildLabelText: termsPane ? termsPane.build_label : "Build Terms"
    property string translateLabelText: termsPane ? termsPane.translate_label : "Translate Untranslated"
    property string reviewLabelText: termsPane ? termsPane.review_label : "Review Terms"
    property string filterLabelText: termsPane ? termsPane.filter_label : "Filter Rare"
    property string importLabelText: termsPane ? termsPane.import_label : "Import Terms"
    property string exportLabelText: termsPane ? termsPane.export_label : "Export Terms"
    property string buildTooltipText: termsPane ? termsPane.build_tooltip : ""
    property string translateTooltipText: termsPane ? termsPane.translate_tooltip : ""
    property string reviewTooltipText: termsPane ? termsPane.review_tooltip : ""
    property string filterTooltipText: termsPane ? termsPane.filter_tooltip : ""
    property string importTooltipText: termsPane ? termsPane.import_tooltip : ""
    property string exportTooltipText: termsPane ? termsPane.export_tooltip : ""
    property bool showBuild: termsPane ? termsPane.show_build : false
    property bool showImport: termsPane ? termsPane.show_import : true
    property bool showExport: termsPane ? termsPane.show_export : true
    property bool canBuild: termsPane ? termsPane.can_build : false
    property bool canTranslate: termsPane ? termsPane.can_translate : false
    property bool canReview: termsPane ? termsPane.can_review : false
    property bool canFilter: termsPane ? termsPane.can_filter : false
    property bool canImport: termsPane ? termsPane.can_import : false
    property bool canExport: termsPane ? termsPane.can_export : false

    function buttonColor(enabled) {
        return enabled ? "#2f251d" : "#d7cebf"
    }

    function labelColor(enabled) {
        return enabled ? "#fcfaf6" : "#786b5e"
    }

    Column {
        id: contentColumn
        anchors.fill: parent
        anchors.margins: 18
        spacing: 12

        Text {
            visible: root.showTitle
            text: root.titleText
            color: "#2f251d"
            font.pixelSize: 24
            font.bold: true
        }

        Text {
            width: parent.width
            text: root.tipText
            color: "#675b4e"
            font.pixelSize: 13
            wrapMode: Text.WordWrap
        }

        Flow {
            width: parent.width
            spacing: 8

            Repeater {
                model: [
                    { "label": root.buildLabelText, "enabled": root.canBuild, "kind": "build", "visible": root.showBuild, "tooltip": root.buildTooltipText },
                    { "label": root.translateLabelText, "enabled": root.canTranslate, "kind": "translate", "tooltip": root.translateTooltipText },
                    { "label": root.reviewLabelText, "enabled": root.canReview, "kind": "review", "tooltip": root.reviewTooltipText },
                    { "label": root.filterLabelText, "enabled": root.canFilter, "kind": "filter", "tooltip": root.filterTooltipText },
                    { "label": root.importLabelText, "enabled": root.canImport, "kind": "import", "visible": root.showImport, "tooltip": root.importTooltipText },
                    { "label": root.exportLabelText, "enabled": root.canExport, "kind": "export", "visible": root.showExport, "tooltip": root.exportTooltipText }
                ]

                delegate: Rectangle {
                    required property var modelData

                    visible: modelData.visible === undefined ? true : modelData.visible
                    width: Math.max(buttonLabel.implicitWidth + 28, 152)
                    height: 40
                    radius: 14
                    color: root.buttonColor(modelData.enabled)

                    Text {
                        id: buttonLabel
                        anchors.centerIn: parent
                        text: modelData.label
                        color: root.labelColor(modelData.enabled)
                        font.pixelSize: 12
                        font.bold: true
                    }

                    MouseArea {
                        id: buttonMouseArea
                        anchors.fill: parent
                        hoverEnabled: true
                        enabled: modelData.enabled
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: {
                            if (modelData.kind === "build") {
                                root.buildRequested()
                            } else if (modelData.kind === "translate") {
                                root.translateRequested()
                            } else if (modelData.kind === "review") {
                                root.reviewRequested()
                            } else if (modelData.kind === "filter") {
                                root.filterRequested()
                            } else if (modelData.kind === "import") {
                                root.importRequested()
                            } else {
                                root.exportRequested()
                            }
                        }
                    }

                    ToolTip.visible: buttonMouseArea.containsMouse && !!modelData.tooltip
                    ToolTip.text: modelData.tooltip
                    ToolTip.delay: 500
                }
            }
        }
    }
}
