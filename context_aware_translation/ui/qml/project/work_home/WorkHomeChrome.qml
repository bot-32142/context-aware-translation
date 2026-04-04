import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "workHomeChrome"
    color: "#f3efe7"
    property int bodyFontSize: 14
    property int detailFontSize: 13
    property int buttonFontSize: 14
    property int chipFontSize: 13
    property int toggleLabelFontSize: 14
    property int toggleWarningFontSize: 13
    implicitHeight: tipLabel.implicitHeight + importCard.implicitHeight + 48
        + (root.hasSetupBlocker ? setupCard.implicitHeight + 12 : 0)

    signal selectFilesRequested
    signal selectFolderRequested
    signal importRequested
    signal setupActionRequested
    signal importTypeSelected(string documentType)
    signal removeHardWrapsToggled(bool enabled)

    property string tipText: workHome ? workHome.tip_text : ""
    property string selectFilesLabelText: workHome ? workHome.select_files_label : "Select Files"
    property string selectFolderLabelText: workHome ? workHome.select_folder_label : "Select Folder"
    property string importLabelText: workHome ? workHome.import_label : "Import"
    property string removeHardWrapsLabelText: workHome ? workHome.remove_hard_wraps_label : "Remove hard wraps"
    property string removeHardWrapsWarningText: workHome ? workHome.remove_hard_wraps_warning : ""
    property string selectFilesTooltipText: workHome ? workHome.select_files_tooltip : ""
    property string selectFolderTooltipText: workHome ? workHome.select_folder_tooltip : ""
    property string importTooltipText: workHome ? workHome.import_tooltip : ""
    property string contextSummaryText: workHome ? workHome.context_summary : ""
    property string contextBlockerText: workHome ? workHome.context_blocker_text : ""
    property bool hasContextBlocker: workHome ? workHome.has_context_blocker : false
    property bool hasSetupBlocker: workHome ? workHome.has_setup_blocker : false
    property string setupMessageText: workHome ? workHome.setup_message : ""
    property string setupActionLabelText: workHome ? workHome.setup_action_label : ""
    property string setupActionTooltipText: workHome ? workHome.setup_action_tooltip : ""
    property string importSummaryText: workHome ? workHome.import_summary : ""
    property string importMessageText: workHome ? workHome.import_message : ""
    property string importMessageKind: workHome ? workHome.import_message_kind : ""
    property bool hasImportMessage: workHome ? workHome.has_import_message : false
    property bool canImport: workHome ? workHome.can_import : false
    property bool removeHardWrapsEnabled: workHome ? workHome.remove_hard_wraps : false
    property bool canRemoveHardWraps: workHome ? workHome.can_remove_hard_wraps : false
    property bool hasImportTypeOptions: workHome ? workHome.has_import_type_options : false
    property var importTypeOptions: workHome ? workHome.import_type_options : []
    property string selectedImportType: workHome ? workHome.selected_import_type : ""

    Rectangle {
        anchors.fill: parent
        color: "#f3efe7"
    }

    Column {
        anchors.fill: parent
        anchors.margins: 18
        spacing: 10

        Text {
            id: tipLabel
            width: parent.width
            text: root.tipText
            color: "#5d5349"
            font.pixelSize: root.bodyFontSize
            wrapMode: Text.WordWrap
        }

        Rectangle {
            id: importCard
            width: parent.width
            radius: 18
            color: "#fcfaf6"
            border.color: "#d9d0c4"
            border.width: 1
            implicitHeight: importColumn.implicitHeight + 24

            Column {
                id: importColumn
                anchors.fill: parent
                anchors.margins: 14
                spacing: 10

                Row {
                    spacing: 8

                    Repeater {
                        model: [
                            { "label": root.selectFilesLabelText, "signalName": "files" },
                            { "label": root.selectFolderLabelText, "signalName": "folder" },
                            { "label": root.importLabelText, "signalName": "import" }
                        ]

                        delegate: Rectangle {
                            width: Math.max(
                                buttonLabel.implicitWidth + 36,
                                modelData.signalName === "import" ? 108 : 124
                            )
                            height: 40
                            radius: 14
                            color: modelData.signalName === "import" && !root.canImport ? "#ddd4c8" : "#2f251d"
                            opacity: modelData.signalName === "import" && !root.canImport ? 0.65 : 1.0

                            Text {
                                id: buttonLabel
                                anchors.centerIn: parent
                                text: modelData.label
                                color: "#fcfaf6"
                                font.pixelSize: root.buttonFontSize
                                font.bold: true
                            }

                            MouseArea {
                                id: importActionMouseArea
                                anchors.fill: parent
                                enabled: modelData.signalName !== "import" || root.canImport
                                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                onClicked: {
                                    if (modelData.signalName === "files") {
                                        root.selectFilesRequested()
                                    } else if (modelData.signalName === "folder") {
                                        root.selectFolderRequested()
                                    } else {
                                        root.importRequested()
                                    }
                                }
                            }

                            ToolTip.visible: importActionMouseArea.containsMouse && !!(
                                modelData.signalName === "files"
                                ? root.selectFilesTooltipText
                                : modelData.signalName === "folder"
                                ? root.selectFolderTooltipText
                                : root.importTooltipText
                            )
                            ToolTip.text: modelData.signalName === "files"
                                ? root.selectFilesTooltipText
                                : modelData.signalName === "folder"
                                ? root.selectFolderTooltipText
                                : root.importTooltipText
                            ToolTip.delay: 500
                        }
                    }
                }

                Row {
                    visible: root.hasImportTypeOptions
                    spacing: 8

                    Repeater {
                        model: root.importTypeOptions

                        delegate: Rectangle {
                            required property var modelData

                            height: 34
                            radius: 12
                            width: choiceLabel.implicitWidth + 20
                            color: modelData.selected ? "#c79c5d" : "#e8decf"

                            Text {
                                id: choiceLabel
                                anchors.centerIn: parent
                                text: modelData.label
                                color: modelData.selected ? "#2f251d" : "#5d5349"
                                font.pixelSize: root.chipFontSize
                                font.bold: modelData.selected
                            }

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.importTypeSelected(modelData.documentType)
                            }
                        }
                    }
                }

                Rectangle {
                    id: hardWrapCard
                    width: parent.width
                    radius: 14
                    color: root.canRemoveHardWraps ? "#f6efe3" : "#f3ede4"
                    border.color: root.canRemoveHardWraps ? "#d9c7af" : "#ddd4c8"
                    border.width: 1
                    implicitHeight: hardWrapRow.implicitHeight + 18
                    opacity: root.canRemoveHardWraps ? 1.0 : 0.8

                    RowLayout {
                        id: hardWrapRow
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 12

                        Rectangle {
                            id: hardWrapTrack
                            Layout.alignment: Qt.AlignVCenter
                            width: 52
                            height: 30
                            radius: 15
                            color: root.removeHardWrapsEnabled ? "#2f251d" : "#cfc4b5"
                            border.color: root.removeHardWrapsEnabled ? "#2f251d" : "#b7ab9c"
                            border.width: 1

                            Rectangle {
                                id: hardWrapThumb
                                width: 22
                                height: 22
                                radius: 11
                                x: root.removeHardWrapsEnabled ? parent.width - width - 4 : 4
                                y: 4
                                color: "#fcfaf6"

                                Behavior on x {
                                    NumberAnimation {
                                        duration: 120
                                    }
                                }
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2

                            Text {
                                Layout.fillWidth: true
                                text: root.removeHardWrapsLabelText
                                color: root.canRemoveHardWraps ? "#2f251d" : "#8b8174"
                                font.pixelSize: root.toggleLabelFontSize
                                font.bold: true
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                Layout.fillWidth: true
                                text: root.removeHardWrapsWarningText
                                color: root.canRemoveHardWraps ? "#6f6458" : "#9a8f82"
                                font.pixelSize: root.toggleWarningFontSize
                                wrapMode: Text.WordWrap
                            }
                        }
                    }

                    MouseArea {
                        id: hardWrapMouseArea
                        anchors.fill: parent
                        z: 1
                        enabled: root.canRemoveHardWraps
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: root.removeHardWrapsToggled(!root.removeHardWrapsEnabled)
                    }
                }

                Text {
                    width: parent.width
                    text: root.importSummaryText
                    color: "#2f251d"
                    font.pixelSize: root.bodyFontSize
                    wrapMode: Text.WordWrap
                    elide: Text.ElideMiddle
                }

                Text {
                    visible: root.hasImportMessage
                    width: parent.width
                    text: root.importMessageText
                    color: root.importMessageKind === "error" ? "#b42318" : "#027a48"
                    font.pixelSize: root.detailFontSize
                    font.bold: true
                    wrapMode: Text.WordWrap
                }
            }
        }

        Rectangle {
            id: setupCard
            visible: root.hasSetupBlocker
            width: parent.width
            radius: 16
            color: "#fff3e8"
            border.color: "#f0b27a"
            border.width: 1
            implicitHeight: setupRow.implicitHeight + 28

            Row {
                id: setupRow
                anchors.fill: parent
                anchors.margins: 14
                spacing: 12

                Text {
                    width: parent.width - setupButton.width - 24
                    text: root.setupMessageText
                    color: "#6b3b11"
                    font.pixelSize: root.detailFontSize
                    wrapMode: Text.WordWrap
                }

                Rectangle {
                    id: setupButton
                    width: 140
                    height: 42
                    radius: 16
                    color: "#6b3b11"

                    Text {
                        anchors.centerIn: parent
                        text: root.setupActionLabelText
                        color: "#fff9f2"
                        font.pixelSize: root.detailFontSize
                        font.bold: true
                    }

                    MouseArea {
                        id: setupActionMouseArea
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.setupActionRequested()
                    }

                    ToolTip.visible: setupActionMouseArea.containsMouse && !!root.setupActionTooltipText
                    ToolTip.text: root.setupActionTooltipText
                    ToolTip.delay: 500
                }
            }
        }
    }
}
