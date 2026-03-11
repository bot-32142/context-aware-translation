import QtQuick

Rectangle {
    id: root
    objectName: "appSettingsPaneChrome"
    color: "#fcfaf6"
    implicitHeight: contentColumn.implicitHeight + 36

    signal tabRequested(string tabName)
    signal actionRequested(string actionName)

    property string tipText: appSettingsPane ? appSettingsPane.tip_text : ""
    property string connectionsTabLabel: appSettingsPane ? appSettingsPane.connections_tab_label : "Connections"
    property string profilesTabLabel: appSettingsPane ? appSettingsPane.profiles_tab_label : "Workflow Profiles"
    property string currentTab: appSettingsPane ? appSettingsPane.current_tab : "connections"
    property var actionButtons: appSettingsPane ? appSettingsPane.action_buttons : []

    function tabFill(selected) {
        return selected ? "#2f251d" : "#e7ddd0"
    }

    function tabText(selected) {
        return selected ? "#fcfaf6" : "#2f251d"
    }

    function actionFill(button) {
        if (!button.enabled) {
            return "#d7cebf"
        }
        return button.primary ? "#2f251d" : "#e7ddd0"
    }

    function actionText(button) {
        if (!button.enabled) {
            return "#786b5e"
        }
        return button.primary ? "#fcfaf6" : "#2f251d"
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
            text: root.tipText
            color: "#675b4e"
            font.pixelSize: 13
            wrapMode: Text.WordWrap
        }

        Row {
            spacing: 8

            Repeater {
                model: [
                    { "tab": "connections", "label": root.connectionsTabLabel, "selected": root.currentTab === "connections" },
                    { "tab": "profiles", "label": root.profilesTabLabel, "selected": root.currentTab === "profiles" }
                ]

                delegate: Rectangle {
                    required property var modelData

                    width: tabLabel.implicitWidth + 28
                    height: 38
                    radius: 14
                    color: root.tabFill(modelData.selected)

                    Text {
                        id: tabLabel
                        anchors.centerIn: parent
                        text: modelData.label
                        color: root.tabText(modelData.selected)
                        font.pixelSize: 12
                        font.bold: true
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.tabRequested(modelData.tab)
                    }
                }
            }
        }

        Flow {
            width: parent.width
            spacing: 8

            Repeater {
                model: root.actionButtons

                delegate: Rectangle {
                    required property var modelData

                    width: actionLabel.implicitWidth + 28
                    height: 40
                    radius: 14
                    color: root.actionFill(modelData)

                    Text {
                        id: actionLabel
                        anchors.centerIn: parent
                        text: modelData.label
                        color: root.actionText(modelData)
                        font.pixelSize: 12
                        font.bold: true
                    }

                    MouseArea {
                        anchors.fill: parent
                        enabled: modelData.enabled
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: root.actionRequested(modelData.action)
                    }
                }
            }
        }
    }
}
