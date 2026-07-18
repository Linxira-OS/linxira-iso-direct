import QtQuick 2.15
import calamares.slideshow 1.0

Presentation {
    id: presentation

    Slide {
        anchors.fill: parent

        Rectangle {
            anchors.fill: parent
            color: "#101419"

            Row {
                anchors.centerIn: parent
                width: Math.min(parent.width - 96, 760)
                height: 220
                spacing: 48

                Image {
                    width: 200
                    height: 200
                    anchors.verticalCenter: parent.verticalCenter
                    source: "linxira-logo.svg"
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                }

                Column {
                    width: parent.width - 248
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 16

                    Text {
                        width: parent.width
                        text: "Linxira OS"
                        color: "#f3f6f7"
                        font.pixelSize: 48
                        font.weight: Font.DemiBold
                        wrapMode: Text.Wrap
                    }

                    Rectangle {
                        width: 64
                        height: 4
                        color: "#14b8a6"
                    }

                    Text {
                        width: parent.width
                        text: "Installing the stable workstation baseline"
                        color: "#aab4bc"
                        font.pixelSize: 18
                        wrapMode: Text.Wrap
                    }
                }
            }
        }
    }

    function onActivate() {
        presentation.currentSlide = 0
    }

    function onLeave() {}
}
