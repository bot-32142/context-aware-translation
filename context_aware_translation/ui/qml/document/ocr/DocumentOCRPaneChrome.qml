import QtQuick

Rectangle {
    id: root
    objectName: "documentOcrPaneChrome"
    color: "#faf6ef"

    signal firstRequested
    signal previousRequested
    signal nextRequested
    signal lastRequested
    signal goRequested(int pageNumber)
    signal runCurrentRequested
    signal runPendingRequested
    signal saveRequested
    signal cancelRequested

    property string tipText: ocrPane ? ocrPane.tip_text : ""
    property string pageLabelText: ocrPane ? ocrPane.page_label : ""
    property string pageStatusText: ocrPane ? ocrPane.page_status_text : ""
    property string pageStatusColor: ocrPane ? ocrPane.page_status_color : "#b54708"
    property string firstLabelText: ocrPane ? ocrPane.first_label : "|<"
    property string previousLabelText: ocrPane ? ocrPane.previous_label : "<"
    property string nextLabelText: ocrPane ? ocrPane.next_label : ">"
    property string lastLabelText: ocrPane ? ocrPane.last_label : ">|"
    property string goToLabelText: ocrPane ? ocrPane.go_to_label : "Go to:"
    property string goLabelText: ocrPane ? ocrPane.go_label : "Go"
    property string runCurrentLabelText: ocrPane ? ocrPane.run_current_label : "(Re)run OCR (Current Page)"
    property string runPendingLabelText: ocrPane ? ocrPane.run_pending_label : "Run OCR for Pending Pages"
    property string saveLabelText: ocrPane ? ocrPane.save_label : "Save"
    property string cancelLabelText: ocrPane ? ocrPane.cancel_label : "Cancel"
    property string progressLabelText: ocrPane ? ocrPane.progress_label : ""
    property string messageText: ocrPane ? ocrPane.message_text : ""
    property string emptyText: ocrPane ? ocrPane.empty_text : ""
    property string pageInputText: ocrPane ? ocrPane.page_input_text : "1"
    property bool hasPages: ocrPane ? ocrPane.has_pages : false
    property bool firstEnabled: ocrPane ? ocrPane.first_enabled : false
    property bool previousEnabled: ocrPane ? ocrPane.previous_enabled : false
    property bool nextEnabled: ocrPane ? ocrPane.next_enabled : false
    property bool lastEnabled: ocrPane ? ocrPane.last_enabled : false
    property bool goEnabled: ocrPane ? ocrPane.go_enabled : false
    property bool runCurrentEnabled: ocrPane ? ocrPane.run_current_enabled : false
    property bool runPendingEnabled: ocrPane ? ocrPane.run_pending_enabled : false
    property bool saveEnabled: ocrPane ? ocrPane.save_enabled : false
    property bool progressVisible: ocrPane ? ocrPane.progress_visible : false
    property bool progressCanCancel: ocrPane ? ocrPane.progress_can_cancel : false
    property bool emptyVisible: ocrPane ? ocrPane.empty_visible : true
    width: parent ? parent.width : 960
    implicitHeight: tipCard.implicitHeight + navigationRow.implicitHeight + actionFlow.implicitHeight + 52
        + (progressRow.visible ? progressRow.height + 10 : 0)
        + (messageTextItem.visible ? messageTextItem.implicitHeight + 10 : 0)
        + (emptyStateText.visible ? emptyStateText.implicitHeight + 10 : 0)

    function actionButtonColor(enabled) {
        return enabled ? "#2f251d" : "#d5cdc0"
    }

    function actionLabelColor(enabled) {
        return enabled ? "#fcfaf6" : "#726454"
    }

    Column {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10

        Rectangle {
            id: tipCard
            width: parent.width
            radius: 10
            color: "#f2eadf"
            border.color: "#ddd1c0"
            border.width: 1
            implicitHeight: 40

            Text {
                anchors.fill: parent
                anchors.margins: 12
                text: root.tipText
                color: "#5e5144"
                wrapMode: Text.WordWrap
                verticalAlignment: Text.AlignVCenter
                font.pixelSize: 12
            }
        }

        Row {
            id: navigationRow
            width: parent.width
            spacing: 8

            Rectangle {
                width: 44
                height: 34
                radius: 10
                color: root.firstEnabled ? "#2f251d" : "#d5cdc0"

                Text {
                    anchors.centerIn: parent
                    text: root.firstLabelText
                    color: root.firstEnabled ? "#fcfaf6" : "#726454"
                    font.pixelSize: 12
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: root.firstEnabled
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.firstRequested()
                }
            }

            Rectangle {
                width: 44
                height: 34
                radius: 10
                color: root.previousEnabled ? "#2f251d" : "#d5cdc0"

                Text {
                    anchors.centerIn: parent
                    text: root.previousLabelText
                    color: root.previousEnabled ? "#fcfaf6" : "#726454"
                    font.pixelSize: 12
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: root.previousEnabled
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.previousRequested()
                }
            }

            Text {
                height: 34
                text: root.pageLabelText
                color: "#2f251d"
                font.pixelSize: 13
                font.bold: true
                verticalAlignment: Text.AlignVCenter
            }

            Text {
                height: 34
                text: root.pageStatusText
                color: root.pageStatusColor
                font.pixelSize: 13
                font.bold: true
                verticalAlignment: Text.AlignVCenter
            }

            Rectangle {
                width: 44
                height: 34
                radius: 10
                color: root.nextEnabled ? "#2f251d" : "#d5cdc0"

                Text {
                    anchors.centerIn: parent
                    text: root.nextLabelText
                    color: root.nextEnabled ? "#fcfaf6" : "#726454"
                    font.pixelSize: 12
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: root.nextEnabled
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.nextRequested()
                }
            }

            Rectangle {
                width: 44
                height: 34
                radius: 10
                color: root.lastEnabled ? "#2f251d" : "#d5cdc0"

                Text {
                    anchors.centerIn: parent
                    text: root.lastLabelText
                    color: root.lastEnabled ? "#fcfaf6" : "#726454"
                    font.pixelSize: 12
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: root.lastEnabled
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.lastRequested()
                }
            }

            Item { width: 12; height: 1 }

            Text {
                height: 34
                text: root.goToLabelText
                color: "#5e5144"
                font.pixelSize: 12
                verticalAlignment: Text.AlignVCenter
            }

            Rectangle {
                width: 64
                height: 34
                radius: 10
                color: "#ffffff"
                border.color: "#d5cdc0"
                border.width: 1

                TextInput {
                    id: pageInput
                    anchors.fill: parent
                    anchors.margins: 10
                    text: root.pageInputText
                    color: "#2f251d"
                    font.pixelSize: 12
                    selectByMouse: true
                    horizontalAlignment: TextInput.AlignHCenter
                    verticalAlignment: TextInput.AlignVCenter
                }
            }

            Rectangle {
                width: 52
                height: 34
                radius: 10
                color: root.goEnabled ? "#efe1cc" : "#d5cdc0"

                Text {
                    anchors.centerIn: parent
                    text: root.goLabelText
                    color: root.goEnabled ? "#2f251d" : "#726454"
                    font.pixelSize: 12
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: root.goEnabled
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.goRequested(parseInt(pageInput.text || "0"))
                }
            }

        }

        Flow {
            id: actionFlow
            width: parent.width
            spacing: 8

            Rectangle {
                width: Math.max(runCurrentText.implicitWidth + 28, 88)
                height: 36
                radius: 12
                color: root.actionButtonColor(root.runCurrentEnabled)

                Text {
                    id: runCurrentText
                    anchors.centerIn: parent
                    text: root.runCurrentLabelText
                    color: root.actionLabelColor(root.runCurrentEnabled)
                    font.pixelSize: 12
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: root.runCurrentEnabled
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.runCurrentRequested()
                }
            }

            Rectangle {
                width: Math.max(runPendingText.implicitWidth + 28, 88)
                height: 36
                radius: 12
                color: root.actionButtonColor(root.runPendingEnabled)

                Text {
                    id: runPendingText
                    anchors.centerIn: parent
                    text: root.runPendingLabelText
                    color: root.actionLabelColor(root.runPendingEnabled)
                    font.pixelSize: 12
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: root.runPendingEnabled
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.runPendingRequested()
                }
            }

            Rectangle {
                width: Math.max(saveText.implicitWidth + 28, 88)
                height: 36
                radius: 12
                color: root.actionButtonColor(root.saveEnabled)

                Text {
                    id: saveText
                    anchors.centerIn: parent
                    text: root.saveLabelText
                    color: root.actionLabelColor(root.saveEnabled)
                    font.pixelSize: 12
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: root.saveEnabled
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.saveRequested()
                }
            }
        }

        Rectangle {
            id: progressRow
            visible: root.progressVisible
            height: 36
            radius: 12
            color: "#e4eefc"
            border.color: "#b3cdf3"
            border.width: 1
            width: Math.max(180, progressText.width + cancelText.width + 48)

            Row {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 10

                Text {
                    id: progressText
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.progressLabelText
                    color: "#1d4b8f"
                    font.pixelSize: 12
                    font.bold: true
                }

                Rectangle {
                    visible: root.progressCanCancel
                    width: cancelText.width + 18
                    height: 24
                    radius: 12
                    color: "#dbeafe"

                    Text {
                        id: cancelText
                        anchors.centerIn: parent
                        text: root.cancelLabelText
                        color: "#1d4b8f"
                        font.pixelSize: 11
                        font.bold: true
                    }

                    MouseArea {
                        anchors.fill: parent
                        enabled: root.progressCanCancel
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: root.cancelRequested()
                    }
                }
            }
        }

        Text {
            id: messageTextItem
            visible: root.messageText.length > 0
            text: root.messageText
            color: "#2563eb"
            font.pixelSize: 12
            font.bold: true
            verticalAlignment: Text.AlignVCenter
        }

        Text {
            id: emptyStateText
            visible: root.emptyVisible
            text: root.emptyText
            color: "#5e5144"
            font.pixelSize: 12
            verticalAlignment: Text.AlignVCenter
        }
    }
}
