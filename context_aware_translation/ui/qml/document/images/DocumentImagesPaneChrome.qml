import QtQuick
import QtQuick.Controls

Rectangle {
    id: root
    objectName: "documentImagesPaneChrome"
    color: "#f8f2ea"
    width: parent ? parent.width : 960
    implicitHeight: tipCard.implicitHeight + navigationRow.implicitHeight + actionFlow.implicitHeight + 52
        + (blockerCard.visible ? blockerCard.implicitHeight + 10 : 0)
        + (messageTextItem.visible ? messageTextItem.implicitHeight + 10 : 0)
        + (progressTextItem.visible ? progressTextItem.implicitHeight + 10 : 0)
        + (emptyTextItem.visible ? emptyTextItem.implicitHeight + 10 : 0)

    signal blockerActionRequested
    signal firstRequested
    signal previousRequested
    signal nextRequested
    signal lastRequested
    signal goRequested(int pageNumber)
    signal toggleRequested
    signal runSelectedRequested
    signal runPendingRequested
    signal forceAllRequested
    signal cancelRequested

    property string tipText: imagesPane ? imagesPane.tip_text : ""
    property string blockerText: imagesPane ? imagesPane.blocker_text : ""
    property string blockerActionLabelText: imagesPane ? imagesPane.blocker_action_label : ""
    property bool blockerActionVisible: imagesPane ? imagesPane.blocker_action_visible : false
    property string pageLabelText: imagesPane ? imagesPane.page_label : ""
    property string statusText: imagesPane ? imagesPane.status_text : ""
    property string statusColor: imagesPane ? imagesPane.status_color : "#b54708"
    property string toggleLabelText: imagesPane ? imagesPane.toggle_label : ""
    property string firstLabelText: imagesPane ? imagesPane.first_label : "|<"
    property string previousLabelText: imagesPane ? imagesPane.previous_label : "<"
    property string nextLabelText: imagesPane ? imagesPane.next_label : ">"
    property string lastLabelText: imagesPane ? imagesPane.last_label : ">|"
    property string goToLabelText: imagesPane ? imagesPane.go_to_label : "Go to:"
    property string goLabelText: imagesPane ? imagesPane.go_label : "Go"
    property string runSelectedLabelText: imagesPane ? imagesPane.run_selected_label : "Reembed This Image"
    property string runPendingLabelText: imagesPane ? imagesPane.run_pending_label : "Reembed Pending"
    property string forceAllLabelText: imagesPane ? imagesPane.force_all_label : "Force Reembed All"
    property string toggleTooltipText: imagesPane ? imagesPane.toggle_tooltip : ""
    property string runSelectedTooltipText: imagesPane ? imagesPane.run_selected_tooltip : ""
    property string runPendingTooltipText: imagesPane ? imagesPane.run_pending_tooltip : ""
    property string forceAllTooltipText: imagesPane ? imagesPane.force_all_tooltip : ""
    property string cancelLabelText: imagesPane ? imagesPane.cancel_label : "Cancel"
    property string messageText: imagesPane ? imagesPane.message_text : ""
    property string progressText: imagesPane ? imagesPane.progress_text : ""
    property string emptyText: imagesPane ? imagesPane.empty_text : ""
    property string pageInputText: imagesPane ? imagesPane.page_input_text : "1"
    property bool firstEnabled: imagesPane ? imagesPane.first_enabled : false
    property bool previousEnabled: imagesPane ? imagesPane.previous_enabled : false
    property bool nextEnabled: imagesPane ? imagesPane.next_enabled : false
    property bool lastEnabled: imagesPane ? imagesPane.last_enabled : false
    property bool goEnabled: imagesPane ? imagesPane.go_enabled : false
    property bool toggleEnabled: imagesPane ? imagesPane.toggle_enabled : false
    property bool runSelectedEnabled: imagesPane ? imagesPane.run_selected_enabled : false
    property bool runPendingEnabled: imagesPane ? imagesPane.run_pending_enabled : false
    property bool forceAllEnabled: imagesPane ? imagesPane.force_all_enabled : false
    property bool messageVisible: imagesPane ? imagesPane.message_visible : false
    property bool progressVisible: imagesPane ? imagesPane.progress_visible : false
    property bool progressCanCancel: imagesPane ? imagesPane.progress_can_cancel : false
    property bool emptyVisible: imagesPane ? imagesPane.empty_visible : true

    function primaryButtonColor(enabled) {
        return enabled ? "#2f251d" : "#d9d0c1"
    }

    function primaryLabelColor(enabled) {
        return enabled ? "#fcfaf6" : "#7b6d5e"
    }

    function secondaryButtonColor(enabled) {
        return enabled ? "#efe0ca" : "#e5dbcd"
    }

    function secondaryLabelColor(enabled) {
        return enabled ? "#2f251d" : "#7b6d5e"
    }

    Column {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10

        Rectangle {
            id: tipCard
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
                color: "#5f5448"
                wrapMode: Text.WordWrap
                verticalAlignment: Text.AlignVCenter
                font.pixelSize: 12
            }
        }

        Rectangle {
            id: blockerCard
            width: parent.width
            visible: root.blockerText.length > 0
            radius: 10
            color: "#fff4e5"
            border.color: "#f0c58a"
            border.width: 1
            implicitHeight: blockerRow.implicitHeight + 20

            Row {
                id: blockerRow
                anchors.fill: parent
                anchors.margins: 10
                spacing: 10

                Text {
                    width: root.blockerActionVisible ? parent.width - blockerButton.width - 10 : parent.width
                    text: root.blockerText
                    color: "#8c3d00"
                    wrapMode: Text.WordWrap
                    font.pixelSize: 12
                }

                Rectangle {
                    id: blockerButton
                    visible: root.blockerActionVisible
                    width: implicitWidth
                    height: 34
                    radius: 10
                    color: "#2f251d"
                    implicitWidth: blockerButtonText.implicitWidth + 26

                    Text {
                        id: blockerButtonText
                        anchors.centerIn: parent
                        text: root.blockerActionLabelText
                        color: "#fcfaf6"
                        font.pixelSize: 12
                        font.bold: true
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.blockerActionRequested()
                    }
                }
            }
        }

        Row {
            id: navigationRow
            width: parent.width
            spacing: 8

            Repeater {
                model: [
                    { label: root.firstLabelText, enabled: root.firstEnabled, signalName: "first" },
                    { label: root.previousLabelText, enabled: root.previousEnabled, signalName: "previous" },
                    { label: root.nextLabelText, enabled: root.nextEnabled, signalName: "next" },
                    { label: root.lastLabelText, enabled: root.lastEnabled, signalName: "last" }
                ]

                delegate: Rectangle {
                    required property var modelData
                    width: 44
                    height: 34
                    radius: 10
                    color: root.primaryButtonColor(modelData.enabled)

                    Text {
                        anchors.centerIn: parent
                        text: modelData.label
                        color: root.primaryLabelColor(modelData.enabled)
                        font.pixelSize: 12
                        font.bold: true
                    }

                    MouseArea {
                        anchors.fill: parent
                        enabled: parent.modelData.enabled
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: {
                            if (parent.modelData.signalName === "first") {
                                root.firstRequested()
                            } else if (parent.modelData.signalName === "previous") {
                                root.previousRequested()
                            } else if (parent.modelData.signalName === "next") {
                                root.nextRequested()
                            } else {
                                root.lastRequested()
                            }
                        }
                    }
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
                text: root.statusText
                color: root.statusColor
                font.pixelSize: 13
                font.bold: true
                visible: text.length > 0
            }

            Item {
                width: 12
                height: 1
            }

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: root.goToLabelText
                color: "#5f5448"
                font.pixelSize: 12
            }

            Rectangle {
                width: 64
                height: 34
                radius: 10
                color: "#ffffff"
                border.color: "#d8cdbf"
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
                color: root.secondaryButtonColor(root.goEnabled)

                Text {
                    anchors.centerIn: parent
                    text: root.goLabelText
                    color: root.secondaryLabelColor(root.goEnabled)
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
                width: 8
                height: 1
            }

            Rectangle {
                width: Math.max(toggleText.implicitWidth + 26, 120)
                height: 34
                radius: 10
                color: root.secondaryButtonColor(root.toggleEnabled)

                Text {
                    id: toggleText
                    anchors.centerIn: parent
                    text: root.toggleLabelText
                    color: root.secondaryLabelColor(root.toggleEnabled)
                    font.pixelSize: 12
                    font.bold: true
                }

                MouseArea {
                    id: toggleMouseArea
                    anchors.fill: parent
                    enabled: root.toggleEnabled
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.toggleRequested()
                }

                ToolTip.visible: toggleMouseArea.containsMouse && !!root.toggleTooltipText
                ToolTip.text: root.toggleTooltipText
                ToolTip.delay: 500
            }
        }

        Flow {
            id: actionFlow
            width: parent.width
            spacing: 8

            Rectangle {
                width: Math.max(runSelectedText.implicitWidth + 28, 148)
                height: 36
                radius: 12
                color: root.primaryButtonColor(root.runSelectedEnabled)

                Text {
                    id: runSelectedText
                    anchors.centerIn: parent
                    text: root.runSelectedLabelText
                    color: root.primaryLabelColor(root.runSelectedEnabled)
                    font.pixelSize: 12
                    font.bold: true
                }

                MouseArea {
                    id: runSelectedMouseArea
                    anchors.fill: parent
                    enabled: root.runSelectedEnabled
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.runSelectedRequested()
                }

                ToolTip.visible: runSelectedMouseArea.containsMouse && !!root.runSelectedTooltipText
                ToolTip.text: root.runSelectedTooltipText
                ToolTip.delay: 500
            }

            Rectangle {
                width: Math.max(runPendingText.implicitWidth + 28, 148)
                height: 36
                radius: 12
                color: root.primaryButtonColor(root.runPendingEnabled)

                Text {
                    id: runPendingText
                    anchors.centerIn: parent
                    text: root.runPendingLabelText
                    color: root.primaryLabelColor(root.runPendingEnabled)
                    font.pixelSize: 12
                    font.bold: true
                }

                MouseArea {
                    id: runPendingMouseArea
                    anchors.fill: parent
                    enabled: root.runPendingEnabled
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.runPendingRequested()
                }

                ToolTip.visible: runPendingMouseArea.containsMouse && !!root.runPendingTooltipText
                ToolTip.text: root.runPendingTooltipText
                ToolTip.delay: 500
            }

            Rectangle {
                width: Math.max(forceAllText.implicitWidth + 28, 148)
                height: 36
                radius: 12
                color: root.primaryButtonColor(root.forceAllEnabled)

                Text {
                    id: forceAllText
                    anchors.centerIn: parent
                    text: root.forceAllLabelText
                    color: root.primaryLabelColor(root.forceAllEnabled)
                    font.pixelSize: 12
                    font.bold: true
                }

                MouseArea {
                    id: forceAllMouseArea
                    anchors.fill: parent
                    enabled: root.forceAllEnabled
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.forceAllRequested()
                }

                ToolTip.visible: forceAllMouseArea.containsMouse && !!root.forceAllTooltipText
                ToolTip.text: root.forceAllTooltipText
                ToolTip.delay: 500
            }

            Rectangle {
                visible: root.progressVisible && root.progressCanCancel
                height: 36
                radius: 12
                color: "#fff4e5"
                border.color: "#f0c58a"
                border.width: 1
                implicitWidth: cancelText.implicitWidth + 26

                Text {
                    id: cancelText
                    anchors.centerIn: parent
                    text: root.cancelLabelText
                    color: "#8c3d00"
                    font.pixelSize: 12
                    font.bold: true
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.cancelRequested()
                }
            }
        }

        Text {
            id: messageTextItem
            width: parent.width
            text: root.messageText
            visible: root.messageVisible
            color: "#2563eb"
            font.pixelSize: 12
            wrapMode: Text.WordWrap
        }

        Text {
            id: progressTextItem
            width: parent.width
            text: root.progressText
            visible: root.progressVisible
            color: "#5f5448"
            font.pixelSize: 12
            wrapMode: Text.WordWrap
        }

        Text {
            id: emptyTextItem
            width: parent.width
            text: root.emptyText
            visible: root.emptyVisible
            color: "#5f5448"
            font.pixelSize: 12
            wrapMode: Text.WordWrap
        }
    }
}
