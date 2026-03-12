import QtQuick

Rectangle {
    id: root
    objectName: "projectSettingsPaneChrome"
    color: "#fcfaf6"
    implicitHeight: contentColumn.implicitHeight + 36

    signal saveRequested
    signal openAppSetupRequested

    property string titleText: projectSettingsPane ? projectSettingsPane.title_text : "Project Setup"
    property string tipText: projectSettingsPane ? projectSettingsPane.tip_text : ""
    property string customProfileLabel: projectSettingsPane ? projectSettingsPane.custom_profile_label : "Custom profile"
    property string blockerText: projectSettingsPane ? projectSettingsPane.blocker_text : ""
    property bool hasBlocker: projectSettingsPane ? projectSettingsPane.has_blocker : false
    property string messageText: projectSettingsPane ? projectSettingsPane.message_text : ""
    property bool hasMessage: projectSettingsPane ? projectSettingsPane.has_message : false
    property string messageKind: projectSettingsPane ? projectSettingsPane.message_kind : ""
    property string customProfileText: projectSettingsPane ? projectSettingsPane.custom_profile_text : ""
    property bool showCustomProfile: projectSettingsPane ? projectSettingsPane.show_custom_profile : false
    property bool showOpenAppSetup: projectSettingsPane ? projectSettingsPane.show_open_app_setup : false
    property bool canSave: projectSettingsPane ? projectSettingsPane.can_save : false
    property string routesHintText: projectSettingsPane ? projectSettingsPane.routes_hint_text : ""
    property string openAppSetupLabel: projectSettingsPane ? projectSettingsPane.open_app_setup_label : "Open App Setup"
    property string saveLabel: projectSettingsPane ? projectSettingsPane.save_label : "Save"

    function primaryButtonColor(enabled) {
        return enabled ? "#2f251d" : "#d7cebf"
    }

    function primaryLabelColor(enabled) {
        return enabled ? "#fcfaf6" : "#786b5e"
    }

    function secondaryButtonColor() {
        return "#e7ddd0"
    }

    function secondaryLabelColor() {
        return "#2f251d"
    }

    function messageFill(kind) {
        return kind === "error" ? "#fff2f0" : "#eefbf3"
    }

    function messageStroke(kind) {
        return kind === "error" ? "#f7b3ad" : "#9ddbb5"
    }

    function messageTextColor(kind) {
        return kind === "error" ? "#b42318" : "#027a48"
    }

    Column {
        id: contentColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 18
        spacing: 12

        Text {
            width: parent.width
            text: root.titleText
            color: "#2f251d"
            font.pixelSize: 24
            font.bold: true
            wrapMode: Text.WordWrap
        }

        Text {
            width: parent.width
            text: root.tipText
            color: "#675b4e"
            font.pixelSize: 13
            wrapMode: Text.WordWrap
        }

        Rectangle {
            visible: root.hasBlocker
            width: parent.width
            implicitHeight: blockerColumn.implicitHeight + 24
            radius: 16
            color: "#fff7ed"
            border.width: 1
            border.color: "#fed7aa"

            Column {
                id: blockerColumn
                anchors.fill: parent
                anchors.margins: 12
                spacing: 10

                Text {
                    width: parent.width
                    text: root.blockerText
                    color: "#9a3412"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }

                Rectangle {
                    visible: root.showOpenAppSetup
                    width: blockerButtonLabel.implicitWidth + 28
                    height: 38
                    radius: 14
                    color: root.secondaryButtonColor()

                    Text {
                        id: blockerButtonLabel
                        anchors.centerIn: parent
                        text: root.openAppSetupLabel
                        color: root.secondaryLabelColor()
                        font.pixelSize: 12
                        font.bold: true
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.openAppSetupRequested()
                    }
                }
            }
        }

        Rectangle {
            visible: root.hasMessage
            width: parent.width
            implicitHeight: messageLabel.implicitHeight + 20
            radius: 14
            color: root.messageFill(root.messageKind)
            border.width: 1
            border.color: root.messageStroke(root.messageKind)

            Text {
                id: messageLabel
                anchors.fill: parent
                anchors.margins: 10
                text: root.messageText
                color: root.messageTextColor(root.messageKind)
                font.pixelSize: 12
                font.bold: true
                wrapMode: Text.WordWrap
            }
        }

        Rectangle {
            visible: root.showCustomProfile
            width: parent.width
            implicitHeight: customColumn.implicitHeight + 24
            radius: 16
            color: "#f3eee5"
            border.width: 1
            border.color: "#ddd4c8"

            Column {
                id: customColumn
                anchors.fill: parent
                anchors.margins: 12
                spacing: 6

                Text {
                    width: parent.width
                    text: root.customProfileLabel
                    color: "#2f251d"
                    font.pixelSize: 13
                    font.bold: true
                    wrapMode: Text.WordWrap
                }

                Text {
                    width: parent.width
                    text: root.customProfileText
                    color: "#5f5447"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }

                Text {
                    width: parent.width
                    text: root.routesHintText
                    color: "#786b5e"
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }
            }
        }

        Row {
            spacing: 8

            Rectangle {
                width: saveButtonLabel.implicitWidth + 28
                height: 40
                radius: 14
                color: root.primaryButtonColor(root.canSave)

                Text {
                    id: saveButtonLabel
                    anchors.centerIn: parent
                    text: root.saveLabel
                    color: root.primaryLabelColor(root.canSave)
                    font.pixelSize: 12
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: root.canSave
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.saveRequested()
                }
            }
        }
    }
}
