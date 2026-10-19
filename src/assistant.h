#pragma once

#include <QDBusAbstractAdaptor>
#include <QObject>
#include <QString>
#include <QTimer>

class Assistant final : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString state READ state NOTIFY stateChanged)
    Q_PROPERTY(QString message READ message NOTIFY messageChanged)
    Q_PROPERTY(double level READ level NOTIFY levelChanged)

public:
    explicit Assistant(QObject *parent = nullptr);
    QString state() const { return m_state; }
    QString message() const { return m_message; }
    double level() const { return m_level; }

    Q_INVOKABLE bool setState(const QString &state);
    Q_INVOKABLE void setMessage(const QString &message);
    void appendMessage(const QString &fragment);
    void clearMessage();
    Q_INVOKABLE void setLevel(double value);
    void reset();

signals:
    void stateChanged();
    void messageChanged();
    void levelChanged();

private:
    void flushPending();
    QString m_state = QStringLiteral("idle");
    QString m_message;
    QString m_pending;
    double m_level = 0.0;
    QTimer m_flushTimer;
};

class ThemeManager;

class AssistantAdaptor final : public QDBusAbstractAdaptor {
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "org.example.VoiceOverlay1")
public:
    explicit AssistantAdaptor(Assistant *assistant, ThemeManager *theme);

public slots:
    bool SetState(const QString &state);
    void SetMessage(const QString &message);
    void AppendMessage(const QString &fragment);
    void ClearMessage();
    void SetLevel(double level);
    void Reset();
    QString GetState();
    QString Ping();
    bool ReloadConfig();
    bool SaveConfig();
    bool ResetTheme();
    bool LoadPreset(const QString &name);
    bool LoadPalette(const QString &name);
    bool SetOption(const QString &path, const QString &jsonValue);
    QString GetConfigPath();

private:
    Assistant *m_assistant;
    ThemeManager *m_theme;
};
