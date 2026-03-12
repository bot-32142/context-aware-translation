import QtQuick

Rectangle {
    id: root
    objectName: "documentExportPaneChrome"
    color: "#f7f2ea"
    width: parent ? parent.width : 960
    implicitHeight: contentColumn.implicitHeight + 32

    signal exportRequested

    property string tipText: exportPane ? exportPane.tip_text : ""
    property string exportLabelText: exportPane ? exportPane.export_label : "Export This Document"
    property bool canExport: exportPane ? exportPane.can_export : false
    property bool hasResult: exportPane ? exportPane.has_result : false
    property string resultText: exportPane ? exportPane.result_text : ""

    Column {
        id: contentColumn
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10

        Rectangle {
            width: parent.width
            radius: 10
            color: "#efe6d8"
            border.color: "#dbcdb9"
            border.width: 1
            implicitHeight: 40

            Text {
                anchors.fill: parent
                anchors.margins: 12
                text: root.tipText
                color: "#5f5447"
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                verticalAlignment: Text.AlignVCenter
            }
        }

        Flow {
            width: parent.width
            spacing: 10

            Rectangle {
                width: Math.max(170, exportButtonText.implicitWidth + 30)
                height: 40
                radius: 14
                color: root.canExport ? "#2f251d" : "#d7cebf"

                Text {
                    id: exportButtonText
                    anchors.centerIn: parent
                    text: root.exportLabelText
                    color: root.canExport ? "#fcfaf6" : "#786b5e"
                    font.pixelSize: 12
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: root.canExport
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.exportRequested()
                }
            }

            Text {
                visible: root.hasResult
                width: Math.max(0, parent.width - 220)
                text: root.resultText
                color: "#15803d"
                font.pixelSize: 12
                font.bold: true
                wrapMode: Text.WordWrap
                verticalAlignment: Text.AlignVCenter
            }
        }
    }
}
