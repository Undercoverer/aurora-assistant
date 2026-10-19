self: { config, lib, pkgs, ... }:
let
  cfg = config.programs.aurora-assistant;
  types = lib.types;
  packages = self.packages.${pkgs.stdenv.hostPlatform.system};
  runtimeConfig = pkgs.writeText "aurora-assistant.json" (builtins.toJSON {
    apps = cfg.applications;
    dbus_actions = cfg.dbusActions;
    commands = {
      wpctl = "${pkgs.wireplumber}/bin/wpctl";
      playerctl = "${pkgs.playerctl}/bin/playerctl";
      gtk-launch = "${pkgs.gtk3}/bin/gtk-launch";
    };
    llm = { url = "http://127.0.0.1:11434/v1"; model = cfg.ollama.model; };
    tts = { url = "http://127.0.0.1:${toString cfg.ttsPort}/v1";
      model = "supertonic-3"; voice = cfg.voice; };
    stt = {
      model = cfg.sttModel;
      realtime_model = cfg.realtimeSttModel;
      wake_model = cfg.wakeModel;
      embedding_model = "${cfg.modelDirectory}/embedding_model.onnx";
      melspectrogram_model = "${cfg.modelDirectory}/melspectrogram.onnx";
      silero_model = "${cfg.modelDirectory}/silero_vad.onnx";
      silence_seconds = cfg.silenceSeconds;
      wake_threshold = cfg.wakeThreshold;
      wake_timeout = cfg.wakeTimeout;
      max_utterance_seconds = cfg.maxUtteranceSeconds;
      device = "cpu";
      compute_type = "int8";
      language = cfg.language;
      input_device = cfg.inputDevice;
    };
  });
  common = {
    partOf = [ "aurora-assistant.target" "graphical-session.target" ];
    unitConfig.ConditionUser = cfg.user;
    serviceConfig = {
      Restart = "on-failure";
      RestartSec = 3;
      TimeoutStopSec = 15;
      NoNewPrivileges = true;
      UMask = "0077";
    };
  };
  offline = {
    HF_HUB_OFFLINE = "1";
    TRANSFORMERS_OFFLINE = "1";
    HF_HUB_DISABLE_TELEMETRY = "1";
    DO_NOT_TRACK = "1";
  };
in {
  options.programs.aurora-assistant = {
    enable = lib.mkEnableOption "local Aurora voice assistant for Plasma Wayland";
    user = lib.mkOption { type = types.str; description = "Desktop account that runs the assistant."; };
    package = lib.mkOption { type = types.package; default = packages.assistant; };
    overlayPackage = lib.mkOption { type = types.package; default = packages.default; };
    modelDirectory = lib.mkOption { type = types.str; default = "/var/lib/aurora-models";
      description = "Absolute directory of pre-provisioned local speech models."; };
    wakeModel = lib.mkOption { type = types.str; default = "${cfg.modelDirectory}/wake.onnx";
      description = "Absolute path to the trained openWakeWord ONNX wake-phrase model."; };
    sttModel = lib.mkOption { type = types.str; default = "${cfg.modelDirectory}/whisper";
      description = "Absolute path to the final CTranslate2 speech recognition model."; };
    realtimeSttModel = lib.mkOption { type = types.str; default = "${cfg.modelDirectory}/whisper-realtime";
      description = "Absolute path to the provisional CTranslate2 speech recognition model."; };
    wakeTimeout = lib.mkOption { type = types.numbers.between 1 60; default = 8; };
    maxUtteranceSeconds = lib.mkOption { type = types.numbers.between 5 300; default = 45; };
    dbusActions = lib.mkOption {
      default = {};
      description = "Explicit D-Bus capabilities. The model selects aliases, never endpoints or arguments.";
      type = types.attrsOf (types.submodule {
        options = {
          description = lib.mkOption { type = types.str; };
          bus = lib.mkOption { type = types.enum [ "session" "system" ]; default = "session"; };
          destination = lib.mkOption { type = types.str; };
          path = lib.mkOption { type = types.str; };
          interface = lib.mkOption { type = types.str; };
          member = lib.mkOption { type = types.str; };
          signature = lib.mkOption { type = types.str; default = ""; };
          arguments = lib.mkOption { type = types.listOf types.anything; default = []; };
          expectedReply = lib.mkOption { type = types.nullOr (types.listOf types.anything); default = null; };
          successMessage = lib.mkOption { type = types.str; default = "D-Bus action completed."; };
        };
      });
    };
    applications = lib.mkOption { type = types.attrsOf types.str;
      default = { dolphin = "org.kde.dolphin.desktop"; };
      description = "Allowed spoken aliases mapped to installed desktop entry filenames."; };
    silenceSeconds = lib.mkOption { type = types.numbers.between 0.2 5; default = 0.7; };
    wakeThreshold = lib.mkOption { type = types.numbers.between 0 1; default = 0.5; };
    language = lib.mkOption { type = types.str; default = "en"; };
    inputDevice = lib.mkOption { type = types.nullOr (types.either types.int types.str); default = null; };
    voice = lib.mkOption { type = types.enum [ "M1" "M2" "M3" "M4" "M5" "F1" "F2" "F3" "F4" "F5" ]; default = "F1"; };
    ttsPort = lib.mkOption { type = types.port; default = 7788; };
    ollama.enable = lib.mkOption { type = types.bool; default = true;
      description = "Manage the system Ollama service in local-only mode."; };
    ollama.model = lib.mkOption { type = types.str; default = "qwen3:4b"; };
  };
  config = lib.mkIf cfg.enable {
    assertions = [{ assertion = lib.hasPrefix "/" cfg.modelDirectory;
      message = "programs.aurora-assistant.modelDirectory must be absolute."; }];
    environment.systemPackages = [ cfg.package cfg.overlayPackage ];
    services.ollama = lib.mkIf cfg.ollama.enable { enable = true; host = "127.0.0.1"; };
    systemd.services.ollama.environment = lib.mkIf cfg.ollama.enable { OLLAMA_NO_CLOUD = "1"; };
    systemd.user.targets.aurora-assistant = {
      description = "Aurora local voice assistant";
      wantedBy = [ "graphical-session.target" ];
      after = [ "graphical-session.target" ];
      partOf = [ "graphical-session.target" ];
      wants = [ "aurora-controller.service" ];
      unitConfig.ConditionUser = cfg.user;
    };
    systemd.user.services.aurora-voice-overlay = lib.recursiveUpdate common {
      description = "Aurora Wayland overlay";
      serviceConfig = { Type = "dbus"; BusName = "org.example.VoiceOverlay";
        ExecStart = "${cfg.overlayPackage}/bin/aurora-voice-overlay"; };
      environment.QT_QPA_PLATFORM = "wayland";
    };
    systemd.user.services.aurora-tts = lib.recursiveUpdate common {
      description = "Local Supertonic speech API";
      environment = offline;
      serviceConfig.ExecStart = lib.escapeShellArgs [ "${cfg.package}/bin/aurora-tts"
        "--model-dir" "${cfg.modelDirectory}/supertonic" "--port" (toString cfg.ttsPort) ];
    };
    systemd.user.services.aurora-controller = lib.recursiveUpdate common {
      description = "Aurora microphone and action controller";
      wants = [ "aurora-voice-overlay.service" "aurora-tts.service" ];
      after = [ "aurora-voice-overlay.service" "aurora-tts.service" ];
      environment = offline;
      serviceConfig.ExecStart = "${cfg.package}/bin/aurora-assistant --config ${runtimeConfig}";
    };
  };
}
