import QtQuick

Rectangle {
    id: root
    objectName: "appShellChrome"
    color: "#f4efe6"
    height: 78

    signal projectsRequested
    signal appSettingsRequested
    signal queueRequested
    signal closeProjectRequested

    property bool hasCurrentProject: appShell ? appShell.has_current_project : false
    property string currentProjectName: appShell ? appShell.current_project_name : ""
    property string appName: appShell ? appShell.app_name : "Context-Aware Translation"
    property string projectsLabel: appShell ? appShell.projects_label : "Projects"
    property string queueLabelText: appShell ? appShell.queue_label : "Queue"
    property string appSettingsLabelText: appShell ? appShell.app_settings_label : "App Settings"
    property string backToProjectsLabelText: appShell ? appShell.back_to_projects_label : "Back to Projects"
    property string surfaceTitle: appShell ? appShell.surface_title : root.projectsLabel

    Rectangle {
        anchors.fill: parent
        color: "#f4efe6"

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: "#d9d0c4"
        }

        Row {
            anchors.left: parent.left
            anchors.leftMargin: 22
            anchors.verticalCenter: parent.verticalCenter
            spacing: 16

            Column {
                spacing: 3

                Text {
                    text: root.appName
                    color: "#2f251d"
                    font.pixelSize: 20
                    font.bold: true
                }

                Text {
                    text: root.surfaceTitle
                    color: "#786b5e"
                    font.pixelSize: 12
                }
            }

            Rectangle {
                width: 1
                height: 36
                color: "#d9d0c4"
            }

            Rectangle {
                width: projectsLabel.implicitWidth + 28
                height: 38
                radius: 19
                color: "#2f251d"

                Text {
                    id: projectsLabel
                    anchors.centerIn: parent
                    text: root.projectsLabel
                    color: "#fcfaf6"
                    font.pixelSize: 14
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.projectsRequested()
                }
            }
        }

        Row {
            anchors.right: parent.right
            anchors.rightMargin: 22
            anchors.verticalCenter: parent.verticalCenter
            spacing: 12

            Rectangle {
                visible: root.hasCurrentProject
                width: visible ? queueLabel.implicitWidth + 26 : 0
                height: 36
                radius: 18
                color: "#e7ddd0"

                Text {
                    id: queueLabel
                    anchors.centerIn: parent
                    text: root.queueLabelText
                    color: "#2f251d"
                    font.pixelSize: 13
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.queueRequested()
                }
            }

            Rectangle {
                width: appSettingsLabel.implicitWidth + 28
                height: 36
                radius: 18
                color: "#ddd4c8"

                Text {
                    id: appSettingsLabel
                    anchors.centerIn: parent
                    text: root.appSettingsLabelText
                    color: "#2f251d"
                    font.pixelSize: 13
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.appSettingsRequested()
                }
            }

            Rectangle {
                visible: root.hasCurrentProject
                width: visible ? closeProjectLabel.implicitWidth + 28 : 0
                height: 36
                radius: 18
                color: "#fff8ee"
                border.color: "#d9d0c4"
                border.width: 1

                Text {
                    id: closeProjectLabel
                    anchors.centerIn: parent
                    text: root.backToProjectsLabelText
                    color: "#2f251d"
                    font.pixelSize: 13
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.closeProjectRequested()
                }
            }
        }
    }
}
