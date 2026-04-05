// swift-tools-version: 6.1
import PackageDescription

let package = Package(
    name: "VoiceBridge",
    platforms: [
        .macOS(.v13),
        .iOS(.v17)
    ],
    products: [
        .library(
            name: "BridgeCore",
            targets: ["BridgeCore"]
        )
    ],
    targets: [
        .target(
            name: "BridgeCore"
        ),
        .testTarget(
            name: "BridgeCoreTests",
            dependencies: ["BridgeCore"]
        )
    ]
)
