import QtQuick

Rectangle {
    id: root
    objectName: "queueShellChrome"
    color: "#f6f3ef"
    height: 72

    signal closeRequested

    property string titleText: queueShell ? queueShell.title : "Queue"
    property string subtitleText: queueShell ? queueShell.subtitle : ""

    Rectangle {
        anchors.fill: parent
        color: "#f6f3ef"

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: "#d9d0c4"
        }

        Column {
            anchors.left: parent.left
            anchors.leftMargin: 18
            anchors.verticalCenter: parent.verticalCenter
            spacing: 3

            Text {
                text: root.titleText
                color: "#2f251d"
                font.pixelSize: 18
                font.bold: true
            }

            Text {
                text: root.subtitleText
                color: "#786b5e"
                font.pixelSize: 11
            }
        }

        Rectangle {
            anchors.right: parent.right
            anchors.rightMargin: 18
            anchors.verticalCenter: parent.verticalCenter
            width: 32
            height: 32
            radius: 16
            color: "#e7ddd0"

            Text {
                anchors.centerIn: parent
                text: "×"
                color: "#2f251d"
                font.pixelSize: 18
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
