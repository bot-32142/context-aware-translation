import QtQuick

Rectangle {
    id: root
    objectName: "documentTranslationPaneChrome"
    color: "#f7f2ea"
    implicitHeight: 128

    signal polishToggled(bool enabled)
    signal translateRequested
    signal batchRequested

    property string tipText: translationPane ? translationPane.tip_text : ""
    property string polishLabelText: translationPane ? translationPane.polish_label : "Enable polish pass"
    property string translateLabelText: translationPane ? translationPane.translate_label : "Translate"
    property string batchLabelText: translationPane ? translationPane.batch_label : "Submit Batch Task"
    property string progressText: translationPane ? translationPane.progress_text : ""
    property bool polishEnabled: translationPane ? translationPane.polish_enabled : true
    property bool canTranslate: translationPane ? translationPane.can_translate : false
    property bool supportsBatch: translationPane ? translationPane.supports_batch : false
    property bool canBatch: translationPane ? translationPane.can_batch : false

    function buttonColor(enabled) {
        return enabled ? "#2f251d" : "#d7cebf"
    }

    function labelColor(enabled) {
        return enabled ? "#fcfaf6" : "#786b5e"
    }

    Column {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10

        Text {
            width: parent.width
            text: root.tipText
            color: "#5f5447"
            font.pixelSize: 12
            wrapMode: Text.WordWrap
        }

        Text {
            width: parent.width
            text: root.progressText
            color: "#666666"
            font.pixelSize: 12
            wrapMode: Text.WordWrap
            visible: text.length > 0
        }

        Row {
            spacing: 8

            Rectangle {
                width: 150
                height: 38
                radius: 14
                color: root.polishEnabled ? "#c79c5d" : "#e6dccd"

                Text {
                    anchors.centerIn: parent
                    text: root.polishLabelText
                    color: "#2f251d"
                    font.pixelSize: 12
                    font.bold: root.polishEnabled
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.polishToggled(!root.polishEnabled)
                }
            }

            Rectangle {
                width: 96
                height: 38
                radius: 14
                color: root.buttonColor(root.canTranslate)

                Text {
                    anchors.centerIn: parent
                    text: root.translateLabelText
                    color: root.labelColor(root.canTranslate)
                    font.pixelSize: 12
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: root.canTranslate
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.translateRequested()
                }
            }

            Rectangle {
                visible: root.supportsBatch
                width: 156
                height: 38
                radius: 14
                color: root.buttonColor(root.canBatch)

                Text {
                    anchors.centerIn: parent
                    text: root.batchLabelText
                    color: root.labelColor(root.canBatch)
                    font.pixelSize: 12
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: root.canBatch
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.batchRequested()
                }
            }
        }
    }
}
