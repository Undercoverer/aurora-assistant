self: { config, lib, pkgs, ... }:
let
  cfg = config.programs.aurora-assistant;
  types = lib.types;
  assetRoot = if cfg.models.enable then "${cfg.modelDirectory}/current" else cfg.modelDirectory;
  modelSpec = pkgs.writeText "aurora-models.json" (builtins.toJSON {
    inherit (cfg.models) stt realtimeStt wakeWord wakeSource silero tts revisions;
    voice = cfg.voice;
    llm = cfg.ollama.model;
    kev = if cfg.kev.enable then cfg.kev.model else null;
    reviewer = if cfg.safety.enable then cfg.safety.model else null;
    ollamaUrl = "http://127.0.0.1:11434";
  });
  modelCheck = lib.escapeShellArgs [ "${cfg.package}/bin/aurora-models"
    "--config" modelSpec "--root" cfg.modelDirectory "--check" ];
  packages = self.packages.${pkgs.stdenv.hostPlatform.system};
  runtimeConfig = pkgs.writeText "aurora-assistant.json" (builtins.toJSON {
    webSearch = { inherit (cfg.webSearch) enable url maxResults language; };
    apps = cfg.applications;
    dbus_actions = cfg.dbusActions;
    settings = { enable = true; sessionPrefixes = cfg.settings.sessionPrefixes;
      systemPrefixes = cfg.settings.systemPrefixes; maxRounds = cfg.settings.maxRounds; };
    kev = { inherit (cfg.kev) enable model maxRounds announceEscalation escalationMessage; };
    safety = { enable = cfg.safety.enable; model = cfg.safety.model; };
    commands = {
      wpctl = "${pkgs.wireplumber}/bin/wpctl";
      playerctl = "${pkgs.playerctl}/bin/playerctl";
      gtk-launch = "${pkgs.gtk3}/bin/gtk-launch";
      plasma-colors = "${pkgs.kdePackages.plasma-workspace}/bin/plasma-apply-colorscheme";
      plasma-theme = "${pkgs.kdePackages.plasma-workspace}/bin/plasma-apply-lookandfeel";
      kreadconfig = "${pkgs.kdePackages.kconfig}/bin/kreadconfig6";
    };
    llm = { url = "http://127.0.0.1:11434/v1"; model = cfg.ollama.model; };
    tts = { url = "http://127.0.0.1:${toString cfg.ttsPort}/v1";
      model = cfg.models.tts; voice = cfg.voice; wordSync = cfg.wordSync; };
    stt = {
      model = cfg.sttModel;
      realtime_model = cfg.realtimeSttModel;
      wake_model = cfg.wakeModel;
      embedding_model = "${assetRoot}/embedding_model.onnx";
      melspectrogram_model = "${assetRoot}/melspectrogram.onnx";
      silero_model = "${assetRoot}/silero_vad.onnx";
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
    user = lib.mkOption { type = types.str; description = "Existing desktop account that runs the assistant services and owns model files. This module does not create the account or configure login."; example = "alice"; };
    package = lib.mkOption {
      description = "Python runtime package that provides the controller, model provisioner, TTS server, approval CLI, and desktop D-Bus adapter."; type = types.package; default = packages.assistant; defaultText = lib.literalExpression "self.packages.<system>.assistant"; };
    overlayPackage = lib.mkOption {
      description = "Qt 6 Wayland overlay package. Replacements must implement the pinned VoiceOverlay1 D-Bus interface."; type = types.package; default = packages.default; defaultText = lib.literalExpression "self.packages.<system>.default"; };
    modelDirectory = lib.mkOption { type = types.str; default = "/var/lib/aurora-models";
      description = "Absolute writable directory for model generations. Named provisioning uses its current symlink. Keep managed assets outside home because provisioning uses ProtectHome."; };
    models = {
      enable = lib.mkOption { type = types.bool; default = true;
        description = "Provision named models in a separate online setup service."; };
      stt = lib.mkOption {
        description = "Final speech model: a faster-whisper short name or a public Hugging Face CTranslate2 repository ID. Download failures stop provisioning."; type = types.str; default = "base.en"; };
      realtimeStt = lib.mkOption {
        description = "Provisional speech model used while speaking. A small model reduces update latency; final recognition uses models.stt."; type = types.str; default = "tiny.en"; };
      wakeWord = lib.mkOption {
        description = "Built-in openWakeWord model name, or a label for wakeSource. A text label does not train a new spoken phrase."; type = types.str; default = "hey_jarvis"; example = "hey_mycroft"; };
      wakeSource = lib.mkOption {
        description = "Optional public Hugging Face source for a trained custom wake-word ONNX model. Null selects the built-in model named by wakeWord."; default = null; type = types.nullOr (types.submodule {
        options = {
          repo = lib.mkOption {
            description = "Public Hugging Face repository ID containing the trained wake-word model."; type = types.str; };
          revision = lib.mkOption {
            description = "Exact Hugging Face commit for the custom wake model. Pin a commit for reproducible downloads."; type = types.str; };
          file = lib.mkOption {
            description = "Repository-relative path to the compatible trained ONNX wake model."; type = types.str; };
        };
      }); };
      silero = lib.mkOption {
        description = "Voice activity model identifier. Currently only silero-vad is supported; its file comes from the locked Python package."; type = types.str; default = "silero-vad"; };
      tts = lib.mkOption {
        description = "Supertonic model name: supertonic, supertonic-2, or supertonic-3. Models are downloaded at provisioning, never during synthesis."; type = types.str; default = "supertonic-3"; };
      revisions = lib.mkOption { type = types.attrsOf types.str; default = {};
        description = "Optional Hugging Face revisions keyed by stt, realtimeStt, or tts."; };
    };
    webSearch = {
      enable = lib.mkOption {
        type = types.bool; default = false;
        description = "Allow public web searches through a local SearXNG API. Queries leave the machine for external search engines; model inference stays local. Results are summarized in a tool-free context.";
      };
      manageService = lib.mkOption {
        type = types.bool; default = true;
        description = "When web search is enabled, configure a loopback-only SearXNG service with JSON output and disabled HTTP access logging. Disable to use an existing local API.";
      };
      port = lib.mkOption {
        type = types.port; default = 8888;
        description = "Loopback port used by the managed SearXNG API. Must be free on the host.";
      };
      url = lib.mkOption {
        type = types.str; default = "http://127.0.0.1:${toString cfg.webSearch.port}";
        defaultText = lib.literalExpression ''"http://127.0.0.1:<webSearch.port>"'';
        example = "http://127.0.0.1:8080";
        description = "Base URL of the local SearXNG API, without /search. Only HTTP literal loopback addresses are accepted at runtime. A custom URL requires manageService=false.";
      };
      maxResults = lib.mkOption {
        type = types.ints.between 1 8; default = 5;
        description = "Maximum usable search snippets sent to the local summarizer. Full result pages are not downloaded.";
      };
      language = lib.mkOption {
        type = types.str; default = "en";
        description = "Language sent to SearXNG for web searches. Independent of speech recognition language.";
      };
      engines = lib.mkOption {
        type = types.listOf types.str; default = [ "duckduckgo" ];
        example = [ "duckduckgo" "brave" ];
        description = "SearXNG engine names retained in the managed service. These providers receive queries and see the host's outbound IP. Provider availability and rate limits vary.";
      };
    };
    kev.enable = lib.mkOption {
      type = types.bool; default = true;
      description = "Try Kev first for common requests. Uncertain, invalid, or timed-out routes go to ollama.model before any action runs.";
    };
    kev.maxRounds = lib.mkOption {
      type = types.ints.between 1 4; default = 2;
      description = "Maximum Kev planning rounds before escalation. Two allows a common desktop lookup followed by an action. These rounds count toward settings.maxRounds.";
    };
    kev.announceEscalation = lib.mkOption {
      type = types.bool; default = true;
      description = "Speak a short notice once when Kev escalates. Planning runs concurrently; notices are skipped if the result is ready within 350 milliseconds. TTS failure does not fail the request.";
    };
    kev.escalationMessage = lib.mkOption {
      type = types.strMatching ".{1,160}"; default = "Checking that in more detail.";
      example = "This needs a closer look. One moment.";
      description = "Short local TTS message for escalation. It must not claim that an action has completed. Notices are limited to eight seconds and finish before execution or the final reply.";
    };
    kev.model = lib.mkOption {
      type = types.str; default = cfg.ollama.model;
      defaultText = lib.literalExpression "config.programs.aurora-assistant.ollama.model";
      example = "qwen3:0.6b";
      description = "Local Ollama model for fast routing and common typed arguments. Set a smaller model for lower inference cost; actual latency depends on hardware and model loading. Provisioning pulls it by name.";
    };
    safety.enable = lib.mkOption { type = types.bool; default = true;
      description = "Review mutations with a separate local model context. Unknown mutations still require human approval."; };
    safety.model = lib.mkOption {
      description = "Local Ollama model used in a separate tool-free review context. Defaults to the planner model. Review does not replace deterministic approval rules."; type = types.str; default = cfg.ollama.model; };
    settings.sessionPrefixes = lib.mkOption {
      description = "Allowed session-bus service namespaces for generic discovery and calls. Each entry matches its exact name and dot-separated descendants; empty entries match nothing. Defaults cover KDE, MPRIS, the overlay, and the Aurora desktop adapter. Sensitive services remain excluded."; type = types.listOf types.str; default = [ "org.kde." "org.mpris." "org.example.VoiceOverlay" "org.aurora.Desktop" ]; };
    settings.systemPrefixes = lib.mkOption {
      description = "Allowed system-bus service namespaces, matched at dot boundaries; empty entries match nothing. Normal D-Bus and Polkit rules apply. Generic changes always require local approval."; type = types.listOf types.str; default = [ "org.freedesktop.UPower" ]; };
    settings.maxRounds = lib.mkOption {
      description = "Maximum discovery/planning rounds per request. Each round allows at most four actions. No mutations run when discovery exhausts this limit."; type = types.ints.between 1 8; default = 5; };
    wakeModel = lib.mkOption { type = types.str; default = "${assetRoot}/wake.onnx";
      description = "Absolute path to the trained openWakeWord ONNX wake-phrase model."; };
    sttModel = lib.mkOption { type = types.str; default = "${assetRoot}/whisper";
      description = "Absolute path to the final CTranslate2 speech recognition model."; };
    realtimeSttModel = lib.mkOption { type = types.str; default = "${assetRoot}/whisper-realtime";
      description = "Absolute path to the provisional CTranslate2 speech recognition model."; };
    wakeTimeout = lib.mkOption {
      description = "Seconds allowed to start speaking after wake-word activation."; type = types.numbers.between 1 60; default = 8; };
    maxUtteranceSeconds = lib.mkOption {
      description = "Maximum seconds for a voice turn including final transcription. A timeout discards the request and reloads recognition."; type = types.numbers.between 5 300; default = 45; };
    dbusActions = lib.mkOption {
      default = {};
      description = "Optional fixed D-Bus shortcuts. No entries are required for generic live discovery or built-in desktop controls. These calls require local approval.";
      type = types.attrsOf (types.submodule {
        options = {
          description = lib.mkOption {
            description = "Human-readable meaning of this optional fixed D-Bus shortcut, shown to the planner."; type = types.str; };
          bus = lib.mkOption {
            description = "Bus on which the fixed shortcut is executed. The desktop user must already have access."; type = types.enum [ "session" "system" ]; default = "session"; };
          destination = lib.mkOption {
            description = "Well-known D-Bus service name for this optional shortcut."; type = types.str; };
          path = lib.mkOption {
            description = "D-Bus object path exported by the destination service."; type = types.str; };
          interface = lib.mkOption {
            description = "D-Bus interface containing the selected method."; type = types.str; };
          member = lib.mkOption {
            description = "D-Bus method name to invoke. This is not a shell command."; type = types.str; };
          signature = lib.mkOption {
            description = "Concatenated D-Bus input argument signature. Use an empty string for a method without arguments."; type = types.str; default = ""; };
          arguments = lib.mkOption {
            description = "Fixed method arguments in signature order. The planner cannot change these shortcut arguments."; type = types.listOf types.anything; default = []; };
          expectedReply = lib.mkOption {
            description = "Expected D-Bus return body, or null to accept any successful method return. A return alone does not prove every side effect."; type = types.nullOr (types.listOf types.anything); default = null; };
          successMessage = lib.mkOption {
            description = "Response returned after the shortcut completes and its optional expected reply matches."; type = types.str; default = "D-Bus action completed."; };
        };
      });
    };
    applications = lib.mkOption { type = types.attrsOf types.str;
      default = {};
      description = "Optional spoken aliases for installed desktop IDs. Normal application discovery needs no aliases; visible XDG desktop entries are listed automatically over D-Bus.";
      example = { files = "org.kde.dolphin.desktop"; }; };
    silenceSeconds = lib.mkOption {
      description = "Seconds of silence that finalize recognition after speech. Increase this value to allow longer pauses."; type = types.numbers.between 0.2 5; default = 0.7; };
    wakeThreshold = lib.mkOption {
      description = "Wake detector threshold from 0.01 to one; zero is rejected because it activates on zero-confidence scores. Higher values reduce sensitivity; the useful threshold depends on the microphone and trained model."; type = types.numbers.between 0.01 1; default = 0.5; };
    language = lib.mkOption {
      description = "Whisper language code for recognition. TTS currently uses English; changing this does not change synthesis language."; type = types.str; default = "en"; };
    inputDevice = lib.mkOption {
      description = "SoundDevice input index or device-name substring. Null uses the default input. Select a microphone rather than a monitor source."; type = types.nullOr (types.either types.int types.str); default = null; };
    voice = lib.mkOption {
      description = "Supertonic voice style, F1 through F5 or M1 through M5. Provisioning checks that the style exists in the selected model."; type = types.enum [ "M1" "M2" "M3" "M4" "M5" "F1" "F2" "F3" "F4" "F5" ]; default = "F1"; };
    wordSync = lib.mkOption {
      type = types.bool; default = true;
      description = "Align reply words locally against generated audio and reveal text using the playback device clock. Reuses realtimeSttModel in the TTS service, adding memory and preparation latency. Alignment failures use chunk captions, not fabricated word timestamps.";
    };
    ttsPort = lib.mkOption {
      description = "Loopback TCP port for the local OpenAI-compatible speech endpoint. Must be free on the host."; type = types.port; default = 7788; };
    ollama.enable = lib.mkOption { type = types.bool; default = true;
      description = "Manage the system Ollama service in local-only mode."; };
    ollama.model = lib.mkOption {
      description = "Local Ollama planner model tag. Provisioning pulls this model when missing. Cloud models are rejected; changing size does not grant more permissions."; type = types.str; default = "qwen3:4b"; example = "qwen3:8b"; };
  };
  config = lib.mkIf cfg.enable {
    assertions = [{ assertion = lib.hasPrefix "/" cfg.modelDirectory;
      message = "programs.aurora-assistant.modelDirectory must be absolute."; }
      { assertion = !(cfg.webSearch.enable && cfg.webSearch.manageService) ||
          cfg.webSearch.url == "http://127.0.0.1:${toString cfg.webSearch.port}";
        message = "A custom Aurora search URL requires webSearch.manageService=false."; }
      { assertion = !(cfg.webSearch.enable && cfg.webSearch.manageService) || cfg.webSearch.engines != [];
        message = "Aurora managed search requires at least one search engine."; }
    ];
    environment.systemPackages = [ cfg.package cfg.overlayPackage ];
    environment.etc."aurora-assistant/models.json".source = modelSpec;
    systemd.tmpfiles.rules = lib.mkIf cfg.models.enable [
      "d ${lib.escapeShellArg cfg.modelDirectory} 0750 ${cfg.user} - -"
    ];
    systemd.services.aurora-models = lib.mkIf cfg.models.enable {
      description = "Provision named local Aurora models";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ] ++ lib.optional cfg.ollama.enable "ollama.service";
      requires = lib.optional cfg.ollama.enable "ollama.service";
      restartTriggers = [ modelSpec ];
      environment = { HF_HUB_OFFLINE = "0"; HF_HUB_DISABLE_TELEMETRY = "1";
        XDG_CACHE_HOME = "/var/cache/aurora-models"; };
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        User = cfg.user;
        StateDirectory = "aurora-models";
        CacheDirectory = "aurora-models";
        UMask = "0022";
        ProtectSystem = "strict";
        ProtectHome = true;
        NoNewPrivileges = true;
        ReadWritePaths = [ cfg.modelDirectory ];
        TimeoutStartSec = "1h";
        ExecStart = lib.escapeShellArgs [ "${cfg.package}/bin/aurora-models"
          "--config" modelSpec "--root" cfg.modelDirectory ];
      };
    };
    services.searx = lib.mkIf (cfg.webSearch.enable && cfg.webSearch.manageService) {
      enable = true;
      package = pkgs.searxng;
      configureUwsgi = true;
      configureNginx = false;
      openFirewall = false;
      environmentFile = "/var/lib/aurora-search/environment";
      uwsgiConfig = {
        http = "127.0.0.1:${toString cfg.webSearch.port}";
        disable-logging = true;
      };
      settings = {
        use_default_settings.engines.keep_only = cfg.webSearch.engines;
        general.debug = false;
        server = {
          bind_address = "127.0.0.1";
          port = cfg.webSearch.port;
          secret_key = "$SEARX_SECRET_KEY";
          limiter = false;
          public_instance = false;
        };
        search.formats = [ "html" "json" ];
      };
    };
    systemd.services.aurora-search-secret = lib.mkIf (cfg.webSearch.enable && cfg.webSearch.manageService) {
      description = "Generate a local SearXNG signing key outside the Nix store";
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        StateDirectory = "aurora-search";
        StateDirectoryMode = "0700";
        UMask = "0077";
      };
      script = ''
        if [ ! -s /var/lib/aurora-search/environment ]; then
          ${pkgs.openssl}/bin/openssl rand -hex 32 > /var/lib/aurora-search/key.tmp
          ${pkgs.gnused}/bin/sed 's/^/SEARX_SECRET_KEY=/' /var/lib/aurora-search/key.tmp > /var/lib/aurora-search/environment.tmp
          mv /var/lib/aurora-search/environment.tmp /var/lib/aurora-search/environment
          rm /var/lib/aurora-search/key.tmp
        fi
      '';
    };
    systemd.services.searx-init = lib.mkIf (cfg.webSearch.enable && cfg.webSearch.manageService) {
      requires = [ "aurora-search-secret.service" ];
      after = [ "aurora-search-secret.service" ];
    };
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
      serviceConfig.ExecStartPre = lib.optional cfg.models.enable modelCheck;
      environment = offline;
      serviceConfig.ExecStart = lib.escapeShellArgs ([ "${cfg.package}/bin/aurora-tts"
        "--model-dir" "${assetRoot}/supertonic" "--model" cfg.models.tts "--port" (toString cfg.ttsPort) ] ++ lib.optionals cfg.wordSync [ "--alignment-model" cfg.realtimeSttModel ]);
    };
    systemd.user.services.aurora-desktop = lib.recursiveUpdate common {
      description = "Aurora desktop D-Bus adapter";
      serviceConfig = {
        Type = "dbus";
        BusName = "org.aurora.Desktop";
        ExecStart = "${cfg.package}/bin/aurora-desktop --config ${runtimeConfig}";
      };
    };
    systemd.user.services.aurora-controller = lib.recursiveUpdate common {
      description = "Aurora microphone and action controller";
      serviceConfig.ExecStartPre = lib.optional cfg.models.enable modelCheck;
      serviceConfig.RuntimeDirectory = "aurora-assistant";
      serviceConfig.RuntimeDirectoryMode = "0700";
      wants = [ "aurora-voice-overlay.service" "aurora-tts.service" "aurora-desktop.service" ];
      after = [ "aurora-voice-overlay.service" "aurora-tts.service" "aurora-desktop.service" ];
      environment = offline;
      serviceConfig.ExecStart = "${cfg.package}/bin/aurora-assistant --config ${runtimeConfig}";
    };
  };
}
