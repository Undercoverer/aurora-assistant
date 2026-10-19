#include "theme.h"

#include <QDir>
#include <QColor>
#include <QMap>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonParseError>
#include <QList>
#include <QStringList>
#include <QSaveFile>
#include <QDebug>

ThemeManager::ThemeManager(const QString &path, QObject *parent)
    : QObject(parent), m_path(QFileInfo(path).absoluteFilePath()) {
    m_reloadTimer.setSingleShot(true);
    m_reloadTimer.setInterval(180);
    connect(&m_reloadTimer, &QTimer::timeout, this, &ThemeManager::reloadConfig);
    connect(&m_watcher, &QFileSystemWatcher::fileChanged,
            this, [this](const QString &) { m_reloadTimer.start(); });
    connect(&m_watcher, &QFileSystemWatcher::directoryChanged,
            this, [this](const QString &) { m_reloadTimer.start(); });
}

bool ThemeManager::readObject(const QString &path, QJsonObject *output) const {
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly)) {
        qWarning().noquote() << "CONFIG: cannot open" << path << f.errorString();
        return false;
    }
    QJsonParseError error;
    const QJsonDocument doc = QJsonDocument::fromJson(f.readAll(), &error);
    if (error.error != QJsonParseError::NoError || !doc.isObject()) {
        qWarning().noquote() << "CONFIG: invalid JSON object in" << path << error.errorString();
        return false;
    }
    *output = doc.object();
    return true;
}

QJsonObject ThemeManager::merge(const QJsonObject &base, const QJsonObject &overlay) {
    QJsonObject result = base;
    for (auto it = overlay.begin(); it != overlay.end(); ++it) {
        if (it.value().isObject() && result.value(it.key()).isObject())
            result.insert(it.key(), merge(result.value(it.key()).toObject(), it.value().toObject()));
        else
            result.insert(it.key(), it.value());
    }
    return result;
}

void ThemeManager::apply(const QJsonObject &next) {
    if (next != m_current) {
        m_current = next;
        emit settingsChanged();
    }
}

void ThemeManager::updateWatchers() {
    const QString dir = QFileInfo(m_path).absolutePath();
    if (QFileInfo::exists(dir) && !m_watcher.directories().contains(dir))
        m_watcher.addPath(dir);
    if (QFileInfo::exists(m_path) && !m_watcher.files().contains(m_path))
        m_watcher.addPath(m_path);
}

bool ThemeManager::initialize() {
    if (!readObject(QStringLiteral(":/localvoice/config/default.json"), &m_defaults))
        return false;
    if (!QFileInfo::exists(m_path)) {
        const QString dir = QFileInfo(m_path).absolutePath();
        if (!QDir().mkpath(dir)) {
            qCritical() << "CONFIG: cannot create directory:" << dir;
            return false;
        }
        QSaveFile file(m_path);
        if (!file.open(QIODevice::WriteOnly)) {
            qCritical() << "CONFIG: cannot create" << m_path << file.errorString();
            return false;
        }
        file.write(QJsonDocument(m_defaults).toJson(QJsonDocument::Indented));
        if (!file.commit()) {
            qCritical() << "CONFIG: cannot save" << m_path << file.errorString();
            return false;
        }
        qInfo().noquote() << "CONFIG CREATED:" << m_path;
    }
    return reloadConfig();
}

bool ThemeManager::reloadConfig() {
    QJsonObject user;
    const bool ok = readObject(m_path, &user);
    updateWatchers(); // QFileSystemWatcher drops paths on atomic replacement.
    if (!ok) return false; // Retain last known-good values.
    apply(merge(m_defaults, user));
    qInfo().noquote() << "CONFIG RELOADED:" << m_path;
    return true;
}

bool ThemeManager::loadPreset(const QString &name) {
    // Prevent a supplied name from selecting arbitrary files.
    if (name != QStringLiteral("northern-lights") &&
        name != QStringLiteral("pink-horizon") &&
        name != QStringLiteral("cyber-blue")) {
        qWarning() << "Unknown preset:" << name;
        return false;
    }
    QJsonObject preset;
    if (!readObject(QStringLiteral(":/localvoice/presets/") + name + QStringLiteral(".json"), &preset))
        return false;
    apply(merge(m_defaults, preset));
    qInfo() << "PRESET APPLIED:" << name << "(in memory; config file not modified)";
    return true;
}


// Color palettes are deliberately NOT full presets. Each file may contain only
// the keys below, so choosing a palette cannot move the orb, alter the text,
// or overwrite any geometry/animation/DPI settings.
QStringList ThemeManager::paletteNames() const {
    return {
        QStringLiteral("aqua-violet"),
        QStringLiteral("northern-jade"),
        QStringLiteral("rose-quartz"),
        QStringLiteral("solar-flare"),
        QStringLiteral("deep-ocean"),
        QStringLiteral("ultraviolet"),
        QStringLiteral("arctic-mist"),
        QStringLiteral("ember-noir"),
        QStringLiteral("lime-electric"),
        QStringLiteral("monochrome")
    };
}

bool ThemeManager::readPalette(const QString &name, QJsonObject *output) const {
    if (!paletteNames().contains(name)) {
        qWarning() << "Unknown color palette:" << name;
        return false;
    }
    QJsonObject obj;
    if (!readObject(QStringLiteral(":/localvoice/palettes/") + name + QStringLiteral(".json"), &obj))
        return false;
    const QMap<QString, QStringList> allowed {
        {QStringLiteral("aurora"), {QStringLiteral("colors"), QStringLiteral("edgeColor")}},
        {QStringLiteral("orb"), {QStringLiteral("colors"), QStringLiteral("borderColor"),
                                  QStringLiteral("glowColor"), QStringLiteral("processingRingColor"),
                                  QStringLiteral("waveformColor")}},
        {QStringLiteral("text"), {QStringLiteral("color"), QStringLiteral("statusColor"),
                                   QStringLiteral("caretColor"), QStringLiteral("contrastColor")}},
        {QStringLiteral("vignette"), {QStringLiteral("color")}}
    };
    if (obj.isEmpty()) return false;
    for (auto groupIt = obj.begin(); groupIt != obj.end(); ++groupIt) {
        if (!allowed.contains(groupIt.key()) || !groupIt.value().isObject()) return false;
        const auto section = groupIt.value().toObject();
        const auto defaults = m_defaults.value(groupIt.key()).toObject();
        for (auto it = section.begin(); it != section.end(); ++it) {
            if (!allowed.value(groupIt.key()).contains(it.key())) return false;
            const auto schema = defaults.value(it.key());
            if (schema.isString()) {
                if (!it.value().isString() || !QColor::isValidColor(it.value().toString())) return false;
            } else if (schema.isArray()) {
                const auto arr = it.value().toArray();
                if (!it.value().isArray() || arr.size() != schema.toArray().size()) return false;
                for (const auto &v : arr) {
                    if (!v.isString() || !QColor::isValidColor(v.toString())) return false;
                }
            } else return false;
        }
    }
    *output = obj;
    return true;
}

QVariantMap ThemeManager::palettePreview(const QString &name) const {
    QJsonObject result;
    return readPalette(name, &result) ? result.toVariantMap() : QVariantMap{};
}

bool ThemeManager::applyPalette(const QString &name) {
    QJsonObject palette;
    if (!readPalette(name, &palette)) return false;
    apply(merge(m_current, palette)); // color fields ONLY; preserves all other settings
    qInfo() << "PALETTE APPLIED:" << name << "(colors only, in memory; SaveConfig persists)";
    return true;
}

namespace {
// Recursively walk a JSON object or array. Numeric path components index
// color arrays (aurora.colors.0, orb.colors.2, etc.).
bool atPath(const QJsonValue &root, const QStringList &parts, int depth,
            QJsonValue *result) {
    if (depth == parts.size()) { *result = root; return true; }
    if (root.isObject()) {
        const auto obj = root.toObject();
        if (!obj.contains(parts[depth])) return false;
        return atPath(obj.value(parts[depth]), parts, depth+1, result);
    }
    if (root.isArray()) {
        bool ok = false;
        int i = parts[depth].toInt(&ok);
        auto arr = root.toArray();
        if (!ok || i < 0 || i >= arr.size()) return false;
        return atPath(arr[i], parts, depth+1, result);
    }
    return false;
}
bool replaceAtPath(QJsonValue *node, const QStringList &parts, int depth,
                   const QJsonValue &replacement) {
    if (depth == parts.size()) { *node = replacement; return true; }
    if (node->isObject()) {
        auto obj = node->toObject();
        if (!obj.contains(parts[depth])) return false;
        auto child = obj.value(parts[depth]);
        if (!replaceAtPath(&child,parts,depth+1,replacement)) return false;
        obj.insert(parts[depth],child);
        *node = obj;
        return true;
    }
    if (node->isArray()) {
        bool ok = false;
        int i = parts[depth].toInt(&ok);
        auto arr = node->toArray();
        if (!ok || i < 0 || i >= arr.size()) return false;
        auto child = arr.at(i);
        if (!replaceAtPath(&child,parts,depth+1,replacement)) return false;
        arr[i] = child;
        *node = arr;
        return true;
    }
    return false;
}
}

bool ThemeManager::setOption(const QString &path, const QString &jsonValue) {
    const QStringList parts = path.split(QLatin1Char('.'),Qt::SkipEmptyParts);
    if (parts.size() < 2 || parts.size() > 5) return false;

    QJsonValue schema;
    if (!atPath(QJsonValue(m_defaults),parts,0,&schema)) return false;
    if (schema.isObject() || schema.isArray() || schema.isNull()) return false;

    // Scalars must keep the same JSON type. Editors send JSON-encoded values,
    // with a fallback to bare strings for shell-friendly color values.
    QJsonParseError parseError;
    auto parsed = QJsonDocument::fromJson(("[" + jsonValue + "]").toUtf8(),&parseError);
    QJsonValue value;
    if (parseError.error == QJsonParseError::NoError && parsed.isArray() && parsed.array().size()==1)
        value = parsed.array().at(0);
    else
        value = jsonValue;
    if (schema.isBool() != value.isBool() ||
        schema.isDouble() != value.isDouble() ||
        schema.isString() != value.isString()) return false;

    QJsonValue updated(m_current);
    if (!replaceAtPath(&updated,parts,0,value) || !updated.isObject()) return false;
    apply(updated.toObject());
    return true;
}

bool ThemeManager::saveConfig() {
    QSaveFile file(m_path);
    if (!file.open(QIODevice::WriteOnly)) {
        qWarning() << "CONFIG: cannot save" << m_path << file.errorString();
        return false;
    }
    file.write(QJsonDocument(m_current).toJson(QJsonDocument::Indented));
    if (!file.commit()) {
        qWarning() << "CONFIG: failed committing" << m_path << file.errorString();
        return false;
    }
    updateWatchers();
    qInfo().noquote() << "CONFIG SAVED:" << m_path;
    return true;
}

bool ThemeManager::resetToDefaults() {
    apply(m_defaults);
    qInfo() << "DEFAULT SILK THEME applied in memory (SaveConfig to persist)";
    return true;
}
