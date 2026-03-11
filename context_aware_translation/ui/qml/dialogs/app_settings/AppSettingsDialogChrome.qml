import QtQuick

Rectangle {
    id: root
    objectName: "appSettingsDialogChrome"
    color: "#f4efe6"
    height: 92

    signal closeRequested

    property string titleText: appSettingsDialog ? appSettingsDialog.title : "App Settings"
    property string subtitleText: appSettingsDialog ? appSettingsDialog.subtitle : ""

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

        Column {
            anchors.left: parent.left
            anchors.leftMargin: 22
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: closeButton.left
            anchors.rightMargin: 16
            spacing: 4

            Text {
                text: root.titleText
                color: "#2f251d"
                font.pixelSize: 20
                font.bold: true
                elide: Text.ElideRight
            }

            Text {
                text: root.subtitleText
                color: "#786b5e"
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
        }

        Rectangle {
            id: closeButton
            anchors.right: parent.right
            anchors.rightMargin: 22
            anchors.verticalCenter: parent.verticalCenter
            width: 36
            height: 36
            radius: 18
            color: "#ddd4c8"

            Text {
                anchors.centerIn: parent
                text: "\u00d7"
                color: "#2f251d"
                font.pixelSize: 20
                font.bold: true
            }

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.closeRequested()
            }
        }
    }
}
