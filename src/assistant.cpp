#include "assistant.h"
#include "theme.h"

#include <QtGlobal>
#include <QStringList>
#include <cmath>

namespace {
constexpr int kMaxText = 8192;
}

Assistant::Assistant(QObject *parent) : QObject(parent) {
    m_flushTimer.setSingleShot(true);
    m_flushTimer.setInterval(33); // Avoid a QML redraw for every token.
    connect(&m_flushTimer, &QTimer::timeout, this, &Assistant::flushPending);
}

bool Assistant::setState(const QString &value) {
    static const QStringList allowed = {
        QStringLiteral("idle"), QStringLiteral("wake"),
        QStringLiteral("listening"), QStringLiteral("transcribing"),
        QStringLiteral("thinking"), QStringLiteral("executing"),
        QStringLiteral("speaking"), QStringLiteral("success"),
        QStringLiteral("error")
    };
    if (!allowed.contains(value)) return false;
    if (m_state != value) {
        m_state = value;
        emit stateChanged();
    }
    return true;
}

void Assistant::setMessage(const QString &message) {
    m_flushTimer.stop();
    m_pending.clear();
    const auto trimmed = message.right(kMaxText);
    if (trimmed != m_message) {
        m_message = trimmed;
        emit messageChanged();
    }
}

void Assistant::appendMessage(const QString &fragment) {
    if (fragment.isEmpty()) return;
    m_pending = (m_pending + fragment).right(kMaxText);
    if (!m_flushTimer.isActive()) m_flushTimer.start();
}

void Assistant::flushPending() {
    if (m_pending.isEmpty()) return;
    const auto combined = (m_message + m_pending).right(kMaxText);
    m_pending.clear();
    if (combined != m_message) {
        m_message = combined;
        emit messageChanged();
    }
}

void Assistant::clearMessage() { setMessage(QString()); }

void Assistant::setLevel(double value) {
    if (!std::isfinite(value)) value = 0.0;
    value = qBound(0.0, value, 1.0);
    if (!qFuzzyCompare(m_level + 1.0, value + 1.0)) {
        m_level = value;
        emit levelChanged();
    }
}

void Assistant::reset() {
    setLevel(0.0);
    clearMessage();
    setState(QStringLiteral("idle"));
}

AssistantAdaptor::AssistantAdaptor(Assistant *assistant, ThemeManager *theme)
    : QDBusAbstractAdaptor(assistant), m_assistant(assistant), m_theme(theme) {}

bool AssistantAdaptor::SetState(const QString &state) { return m_assistant->setState(state); }
void AssistantAdaptor::SetMessage(const QString &message) { m_assistant->setMessage(message); }
void AssistantAdaptor::AppendMessage(const QString &fragment) { m_assistant->appendMessage(fragment); }
void AssistantAdaptor::ClearMessage() { m_assistant->clearMessage(); }
void AssistantAdaptor::SetLevel(double level) { m_assistant->setLevel(level); }
void AssistantAdaptor::Reset() { m_assistant->reset(); }
QString AssistantAdaptor::GetState() { return m_assistant->state(); }
QString AssistantAdaptor::Ping() { return QStringLiteral("pong"); }

bool AssistantAdaptor::ReloadConfig() { return m_theme->reloadConfig(); }
bool AssistantAdaptor::SaveConfig() { return m_theme->saveConfig(); }
bool AssistantAdaptor::ResetTheme() { return m_theme->resetToDefaults(); }
bool AssistantAdaptor::LoadPreset(const QString &name) { return m_theme->loadPreset(name); }
bool AssistantAdaptor::LoadPalette(const QString &name) { return m_theme->applyPalette(name); }
bool AssistantAdaptor::SetOption(const QString &path, const QString &value) { return m_theme->setOption(path, value); }
QString AssistantAdaptor::GetConfigPath() { return m_theme->configPath(); }
