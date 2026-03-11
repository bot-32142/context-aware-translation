import QtQuick

Rectangle {
    id: root
    objectName: "projectShellChrome"
    color: "#f6f3ed"
    height: 88

    signal workRequested
    signal termsRequested
    signal queueRequested
    signal projectSettingsRequested
    signal backRequested

    property bool hasCurrentProject: projectShell ? projectShell.has_current_project : false
    property string currentProjectName: projectShell ? projectShell.current_project_name : ""
    property string surfaceTitle: projectShell ? projectShell.surface_title : ""
    property string workLabel: projectShell ? projectShell.work_label : "Work"
    property string termsLabel: projectShell ? projectShell.terms_label : "Terms"
    property string queueLabelText: projectShell ? projectShell.queue_label : "Queue"
    property string projectSettingsLabelText: projectShell ? projectShell.project_settings_label : "Project Settings"
    property string backToProjectsLabelText: projectShell ? projectShell.back_to_projects_label : "Back to Projects"
    property bool workSelected: projectShell ? projectShell.work_selected : true
    property bool termsSelected: projectShell ? projectShell.terms_selected : false

    Rectangle {
        anchors.fill: parent
        color: "#f6f3ed"

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: "#d8d0c6"
        }

        Column {
            anchors.left: parent.left
            anchors.leftMargin: 24
            anchors.verticalCenter: parent.verticalCenter
            spacing: 4

            Text {
                text: root.surfaceTitle
                color: "#2d241d"
                font.pixelSize: 20
                font.bold: true
            }

            Row {
                spacing: 10

                Rectangle {
                    width: workText.implicitWidth + 28
                    height: 36
                    radius: 18
                    color: root.workSelected ? "#2d241d" : "#e8dfd3"

                    Text {
                        id: workText
                        anchors.centerIn: parent
                        text: root.workLabel
                        color: root.workSelected ? "#fcfaf6" : "#2d241d"
                        font.pixelSize: 13
                        font.bold: true
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.workRequested()
                    }
                }

                Rectangle {
                    width: termsText.implicitWidth + 28
                    height: 36
                    radius: 18
                    color: root.termsSelected ? "#2d241d" : "#e8dfd3"

                    Text {
                        id: termsText
                        anchors.centerIn: parent
                        text: root.termsLabel
                        color: root.termsSelected ? "#fcfaf6" : "#2d241d"
                        font.pixelSize: 13
                        font.bold: true
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.termsRequested()
                    }
                }
            }
        }

        Row {
            anchors.right: parent.right
            anchors.rightMargin: 24
            anchors.verticalCenter: parent.verticalCenter
            spacing: 12

            Rectangle {
                width: queueText.implicitWidth + 26
                height: 36
                radius: 18
                color: "#e8dfd3"

                Text {
                    id: queueText
                    anchors.centerIn: parent
                    text: root.queueLabelText
                    color: "#2d241d"
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
                width: projectSetupText.implicitWidth + 26
                height: 36
                radius: 18
                color: "#e8dfd3"

                Text {
                    id: projectSetupText
                    anchors.centerIn: parent
                    text: root.projectSettingsLabelText
                    color: "#2d241d"
                    font.pixelSize: 13
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.projectSettingsRequested()
                }
            }

            Rectangle {
                width: backText.implicitWidth + 28
                height: 36
                radius: 18
                color: "#fffaf1"
                border.color: "#d8d0c6"
                border.width: 1

                Text {
                    id: backText
                    anchors.centerIn: parent
                    text: root.backToProjectsLabelText
                    color: "#2d241d"
                    font.pixelSize: 13
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.backRequested()
                }
            }
        }
    }
}
