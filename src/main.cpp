#include "assistant.h"
#include "theme.h"

#include <QCommandLineOption>
#include <QCommandLineParser>
#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDBusConnection>
#include <QDBusError>
#include <QFile>
#include <QGuiApplication>
#include <QMargins>
#include <QQmlContext>
#include <QQmlApplicationEngine>
#include <QQuickView>
#include <QQuickItem>
#include <QVariant>
#include <QScreen>
#include <QStandardPaths>
#include <QStringList>
#include <QDebug>

#include <LayerShellQt/Window>

namespace {
constexpr auto kQmlPath = ":/qt/qml/LocalVoice/AuroraOverlayV3/Overlay.qml";
constexpr auto kShaderPath = ":/localvoice/shaders/aurora.frag.qsb";
constexpr auto kDefaultPath = ":/localvoice/config/default.json";
constexpr auto kMarker = "AURORA_CONFIGURABLE_V3_RESOURCE_MARKER";

// Qt Quick's visual parent tree is not necessarily its QObject ownership tree.
// QObject::findChild() can miss a visible ShaderEffect even when QML loaded.
QQuickItem *findVisualItem(QQuickItem *parent, const QString &name) {
    if (!parent) return nullptr;
    if (parent->objectName() == name) return parent;
    for (QQuickItem *child : parent->childItems()) {
        if (auto *found = findVisualItem(child, name)) return found;
    }
    return nullptr;
}

int checkResources() {
    QFile qml(QString::fromLatin1(kQmlPath));
    if (!qml.open(QIODevice::ReadOnly)) {
        qCritical() << "FATAL QML resource missing:" << kQmlPath;
        return 2;
    }
    const auto data = qml.readAll();
    if (!data.contains(kMarker)) {
        qCritical() << "FATAL: Unexpected embedded Overlay.qml (marker mismatch)";
        return 3;
    }
    qInfo().noquote() << "QML_RESOURCE=" << kQmlPath;
    qInfo().noquote() << "QML_SHA256=" << QCryptographicHash::hash(data, QCryptographicHash::Sha256).toHex();
    for (const auto *path : {kShaderPath, kDefaultPath}) {
        QFile f(QString::fromLatin1(path));
        if (!f.open(QIODevice::ReadOnly) || f.size() < 100) {
            qCritical() << "FATAL: missing or empty resource" << path;
            return 4;
        }
        qInfo().noquote() << "RESOURCE=" << path << "BYTES=" << f.size();
    }
    return 0;
}
} // namespace

int main(int argc, char **argv) {
    // This mode runs with no graphical session, D-Bus, or Wayland.
    if (argc >= 2 && QString::fromLocal8Bit(argv[1]) == QStringLiteral("--check-resources")) {
        QCoreApplication app(argc, argv);
        return checkResources();
    }

    // Development policy: prevent previously compiled QML from a different
    // executable being used for the same qrc URL. This is intentionally
    // conservative: the source QML is small and packaged in the executable.
    // QML_FORCE_DISK_CACHE overrides the disable flag, so remove it too.
    qunsetenv("QML_FORCE_DISK_CACHE");
    qputenv("QML_DISABLE_DISK_CACHE", "1");
    QGuiApplication app(argc, argv);
    qInfo() << "QML disk cache disabled for this development build";
    QCoreApplication::setApplicationName(QStringLiteral("aurora-voice-overlay"));
    const int resources = checkResources();
    if (resources != 0) return resources;

    QCommandLineParser parser;
    parser.setApplicationDescription(QStringLiteral("Themeable voice assistant overlay for Plasma Wayland"));
    parser.addHelpOption();
    QCommandLineOption configOption({QStringLiteral("c"), QStringLiteral("config")},
                                    QStringLiteral("Config JSON file (otherwise XDG_CONFIG_HOME)"),
                                    QStringLiteral("file"));
    parser.addOption(configOption);
    QCommandLineOption editorOption(QStringLiteral("editor"),
                                    QStringLiteral("Open the live theme editor alongside the overlay"));
    parser.addOption(editorOption);
    parser.process(app);

    const QString defaultPath = QStandardPaths::writableLocation(QStandardPaths::ConfigLocation)
                                + QStringLiteral("/aurora-voice-overlay/config.json");
    ThemeManager theme(parser.isSet(configOption) ? parser.value(configOption) : defaultPath);
    if (!theme.initialize()) return 5;
    qInfo().noquote() << "ACTIVE CONFIG:" << theme.configPath();

    Assistant assistant;
    new AssistantAdaptor(&assistant, &theme);

    QQuickView view;
    view.setColor(Qt::transparent);
    view.setResizeMode(QQuickView::SizeRootObjectToView);
    view.setFlags(Qt::FramelessWindowHint | Qt::WindowTransparentForInput);
    QScreen *screen = app.primaryScreen();
    if (screen) {
        view.setScreen(screen);
        view.resize(screen->geometry().size());
    } else {
        view.resize(1280, 800);
    }
    view.rootContext()->setContextProperty(QStringLiteral("assistant"), &assistant);
    view.rootContext()->setContextProperty(QStringLiteral("themeManager"), &theme);

    auto *layer = LayerShellQt::Window::get(&view);
    if (!layer) {
        qCritical() << "Cannot create LayerShellQt window; start inside Plasma Wayland";
        return 6;
    }
    layer->setLayer(LayerShellQt::Window::LayerOverlay);
    auto anchors = LayerShellQt::Window::Anchors(LayerShellQt::Window::AnchorLeft);
    anchors |= LayerShellQt::Window::AnchorRight;
    anchors |= LayerShellQt::Window::AnchorTop;
    anchors |= LayerShellQt::Window::AnchorBottom;
    layer->setAnchors(anchors);
    layer->setMargins(QMargins(0, 0, 0, 0));
    layer->setExclusiveZone(-1);
    layer->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityNone);
    layer->setScope(QStringLiteral("voice-overlay"));

    // Unique embedded QML module, without qrc:/Overlay.qml or absolute paths.
    view.loadFromModule("LocalVoice.AuroraOverlayV3", "Overlay");
    if (view.status() != QQuickView::Ready) {
        qCritical() << "QML load failed:" << view.source();
        for (const auto &error : view.errors()) qCritical().noquote() << error.toString();
        return 7;
    }
    qInfo().noquote() << "QML MODULE LOADED:" << view.source();

    // Inspect the *visual* Qt Quick tree. A QObject findChild() lookup may
    // incorrectly report "not found" for a rendered QML ShaderEffect.
    auto *shader = findVisualItem(view.rootObject(), QStringLiteral("auroraShader"));
    if (!shader) {
        qCritical() << "FATAL: the loaded QML does not contain the expected auroraShader."
                    << "A different QML version or a cache may have been loaded.";
        view.rootObject()->dumpItemTree();
        return 11;
    } else {
        qInfo() << "SHADER VISUAL ITEM FOUND:" << shader->objectName();
        for (const char *key : {"speed", "heightFactor", "brightness", "density",
                                "colorA", "edgeColor", "vignetteStrength"}) {
            const auto value = shader->property(key);
            if (!value.isValid()) {
                qCritical() << "FATAL: shader uniform has no valid QML property:" << key;
                return 12;
            } else {
                qInfo() << "SHADER UNIFORM PROPERTY:" << key << "=" << value;
            }
        }
    }

    auto bus = QDBusConnection::sessionBus(); // Must not be const: registration mutates it.
    if (!bus.isConnected()) {
        qCritical() << "Session D-Bus unavailable:" << bus.lastError().message();
        return 8;
    }
    if (!bus.registerService(QStringLiteral("org.example.VoiceOverlay"))) {
        qCritical() << "D-Bus name already owned; stop old overlay:" << bus.lastError().message();
        return 9;
    }
    if (!bus.registerObject(QStringLiteral("/org/example/VoiceOverlay"), &assistant,
                            QDBusConnection::ExportAdaptors)) {
        qCritical() << "D-Bus registration failed:" << bus.lastError().message();
        bus.unregisterService(QStringLiteral("org.example.VoiceOverlay"));
        return 10;
    }

    view.show();

    // --editor creates one overlay + one conventional input-capable window.
    // Both share a ThemeManager, so sliders update ShaderEffect uniforms
    // immediately. The editor is not a layer-shell surface.
    QQmlApplicationEngine editorEngine;
    if (parser.isSet(editorOption)) {
        assistant.setState(QStringLiteral("thinking"));
        assistant.setMessage(QStringLiteral(
            "Here is a live preview of the assistant text. Change the Silk aurora, "
            "orb and placement while this overlay is visible."));
        editorEngine.rootContext()->setContextProperty(QStringLiteral("themeManager"), &theme);
        editorEngine.rootContext()->setContextProperty(QStringLiteral("assistant"), &assistant);
        editorEngine.loadFromModule("LocalVoice.AuroraOverlayV3", "Editor");
        if (editorEngine.rootObjects().isEmpty()) {
            qCritical() << "EDITOR QML load failed";
            return 13;
        }
        qInfo() << "AURORA STUDIO: editor and overlay share live theme state";
    }
    return app.exec();
}
