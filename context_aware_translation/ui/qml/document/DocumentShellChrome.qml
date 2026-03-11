import QtQuick

Rectangle {
    id: root
    objectName: "documentShellChrome"
    color: "#f5f0e8"
    implicitWidth: 240

    signal backRequested
    signal ocrRequested
    signal termsRequested
    signal translationRequested
    signal imagesRequested
    signal exportRequested

    property string surfaceTitleText: documentShell ? documentShell.surface_title : ""
    property string scopeTipText: documentShell ? documentShell.scope_tip : ""
    property string backToWorkLabelText: documentShell ? documentShell.back_to_work_label : "Back to Work"
    property string ocrLabelText: documentShell ? documentShell.ocr_label : "OCR"
    property string termsLabelText: documentShell ? documentShell.terms_label : "Terms"
    property string translationLabelText: documentShell ? documentShell.translation_label : "Translation"
    property string imagesLabelText: documentShell ? documentShell.images_label : "Images"
    property string exportLabelText: documentShell ? documentShell.export_label : "Export"
    property bool ocrSelected: documentShell ? documentShell.ocr_selected : true
    property bool termsSelected: documentShell ? documentShell.terms_selected : false
    property bool translationSelected: documentShell ? documentShell.translation_selected : false
    property bool imagesSelected: documentShell ? documentShell.images_selected : false
    property bool exportSelected: documentShell ? documentShell.export_selected : false

    Rectangle {
        anchors.fill: parent
        color: "#f5f0e8"

        Rectangle {
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.right: parent.right
            width: 1
            color: "#d7cebf"
        }

        Column {
            anchors.fill: parent
            anchors.margins: 20
            spacing: 18

            Rectangle {
                width: parent.width
                height: 38
                radius: 19
                color: "#fffaf1"
                border.color: "#d7cebf"
                border.width: 1

                Text {
                    anchors.centerIn: parent
                    text: root.backToWorkLabelText
                    color: "#2f251d"
                    font.pixelSize: 13
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.backRequested()
                }
            }

            Column {
                width: parent.width
                spacing: 6

                Text {
                    width: parent.width
                    text: root.surfaceTitleText
                    color: "#2f251d"
                    font.pixelSize: 22
                    font.bold: true
                    wrapMode: Text.WordWrap
                }

                Text {
                    width: parent.width
                    text: root.scopeTipText
                    color: "#76695d"
                    font.pixelSize: 12
                    lineHeight: 1.2
                    wrapMode: Text.WordWrap
                }
            }

            Column {
                width: parent.width
                spacing: 10

                Rectangle {
                    width: parent.width
                    height: 42
                    radius: 14
                    color: root.ocrSelected ? "#2f251d" : "#e7ddd0"

                    Text {
                        anchors.centerIn: parent
                        text: root.ocrLabelText
                        color: root.ocrSelected ? "#fcfaf6" : "#2f251d"
                        font.pixelSize: 13
                        font.bold: true
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.ocrRequested()
                    }
                }

                Rectangle {
                    width: parent.width
                    height: 42
                    radius: 14
                    color: root.termsSelected ? "#2f251d" : "#e7ddd0"

                    Text {
                        anchors.centerIn: parent
                        text: root.termsLabelText
                        color: root.termsSelected ? "#fcfaf6" : "#2f251d"
                        font.pixelSize: 13
                        font.bold: true
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.termsRequested()
                    }
                }

                Rectangle {
                    width: parent.width
                    height: 42
                    radius: 14
                    color: root.translationSelected ? "#2f251d" : "#e7ddd0"

                    Text {
                        anchors.centerIn: parent
                        text: root.translationLabelText
                        color: root.translationSelected ? "#fcfaf6" : "#2f251d"
                        font.pixelSize: 13
                        font.bold: true
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.translationRequested()
                    }
                }

                Rectangle {
                    width: parent.width
                    height: 42
                    radius: 14
                    color: root.imagesSelected ? "#2f251d" : "#e7ddd0"

                    Text {
                        anchors.centerIn: parent
                        text: root.imagesLabelText
                        color: root.imagesSelected ? "#fcfaf6" : "#2f251d"
                        font.pixelSize: 13
                        font.bold: true
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.imagesRequested()
                    }
                }

                Rectangle {
                    width: parent.width
                    height: 42
                    radius: 14
                    color: root.exportSelected ? "#2f251d" : "#e7ddd0"

                    Text {
                        anchors.centerIn: parent
                        text: root.exportLabelText
                        color: root.exportSelected ? "#fcfaf6" : "#2f251d"
                        font.pixelSize: 13
                        font.bold: true
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.exportRequested()
                    }
                }
            }

        }
    }
}
