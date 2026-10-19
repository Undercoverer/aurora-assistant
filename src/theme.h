#pragma once

#include <QFileSystemWatcher>
#include <QJsonObject>
#include <QObject>
#include <QTimer>
#include <QStringList>
#include <QVariantMap>

class ThemeManager final : public QObject {
    Q_OBJECT
    Q_PROPERTY(QVariantMap settings READ settings NOTIFY settingsChanged)
    Q_PROPERTY(QString configPath READ configPath CONSTANT)

public:
    explicit ThemeManager(const QString &path, QObject *parent = nullptr);
    QVariantMap settings() const { return m_current.toVariantMap(); }
    QString configPath() const { return m_path; }
    bool initialize();
    Q_INVOKABLE bool reloadConfig();
    Q_INVOKABLE bool loadPreset(const QString &name);
    Q_INVOKABLE QStringList paletteNames() const;
    Q_INVOKABLE QVariantMap palettePreview(const QString &name) const;
    Q_INVOKABLE bool applyPalette(const QString &name);
    Q_INVOKABLE bool setOption(const QString &path, const QString &jsonValue);
    Q_INVOKABLE bool saveConfig();
    Q_INVOKABLE bool resetToDefaults();

signals:
    void settingsChanged();

private:
    static QJsonObject merge(const QJsonObject &base, const QJsonObject &overlay);
    bool readObject(const QString &path, QJsonObject *output) const;
    bool readPalette(const QString &name, QJsonObject *output) const;
    void apply(const QJsonObject &next);
    void updateWatchers();

    QString m_path;
    QJsonObject m_defaults;
    QJsonObject m_current;
    QFileSystemWatcher m_watcher;
    QTimer m_reloadTimer;
};
