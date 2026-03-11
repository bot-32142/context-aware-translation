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
    implicitHeight: 168

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
                anchors.verticalCenter: parent.verticalCenter
                text: root.pageLabelText
                color: "#2f251d"
                font.pixelSize: 13
                font.bold: true
            }

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: root.pageStatusText
                color: root.pageStatusColor
                font.pixelSize: 13
                font.bold: true
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
                anchors.verticalCenter: parent.verticalCenter
                text: root.goToLabelText
                color: "#5e5144"
                font.pixelSize: 12
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

            Item {
                width: Math.max(0, parent.width - 700)
                height: 1
            }
        }

        Row {
            width: parent.width
            spacing: 8

            Repeater {
                model: [
                    { label: root.runCurrentLabelText, enabled: root.runCurrentEnabled, signalName: "current" },
                    { label: root.runPendingLabelText, enabled: root.runPendingEnabled, signalName: "pending" },
                    { label: root.saveLabelText, enabled: root.saveEnabled, signalName: "save" }
                ]

                delegate: Rectangle {
                    width: index === 1 ? 196 : (index === 0 ? 204 : 88)
                    height: 36
                    radius: 12
                    color: root.actionButtonColor(modelData.enabled)

                    Text {
                        anchors.centerIn: parent
                        text: modelData.label
                        color: root.actionLabelColor(modelData.enabled)
                        font.pixelSize: 12
                        font.bold: true
                    }

                    MouseArea {
                        anchors.fill: parent
                        enabled: modelData.enabled
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: {
                            if (modelData.signalName === "current") {
                                root.runCurrentRequested()
                            } else if (modelData.signalName === "pending") {
                                root.runPendingRequested()
                            } else {
                                root.saveRequested()
                            }
                        }
                    }
                }
            }

            Rectangle {
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
                visible: root.messageText.length > 0
                anchors.verticalCenter: parent.verticalCenter
                text: root.messageText
                color: "#2563eb"
                font.pixelSize: 12
                font.bold: true
            }

            Text {
                visible: root.emptyVisible
                anchors.verticalCenter: parent.verticalCenter
                text: root.emptyText
                color: "#5e5144"
                font.pixelSize: 12
            }
        }
    }
}
