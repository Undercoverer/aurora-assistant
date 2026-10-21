self: { config, lib, pkgs, ... }:
let
  cfg = config.programs.aurora-assistant;
  types = lib.types;
  assetRoot = if cfg.models.enable then "${cfg.models.directory}/current" else cfg.models.directory;
  managedKev = cfg.kev.enable && cfg.kev.manageService;
  managedPlanner = cfg.planner.manageService;
  modelAlias = name: let parts = lib.splitString ":" name; in
    if builtins.length parts == 2 then "${builtins.head parts}:${lib.toUpper (lib.last parts)}" else name;
  kevAlias = if managedKev then modelAlias cfg.kev.model else cfg.kev.model;
  plannerAlias = if managedPlanner then modelAlias cfg.planner.model else cfg.planner.model;
  managedModels = lib.optional managedKev kevAlias ++ lib.optional managedPlanner plannerAlias;
  routerUrl = "http://127.0.0.1:${toString cfg.inference.port}";
  routerPreset = pkgs.writeText "aurora-llama-models.ini" ("version = 1\n" + lib.generators.toINI {} (
    { "*" = { parallel = 1; sleep-idle-seconds = -1; }; }
    // lib.optionalAttrs managedKev {
      "${kevAlias}" = { model = cfg.kev.modelFile; ctx-size = cfg.kev.contextSize;
        cache-ram = cfg.kev.cacheRamMiB;
        # Kev reads all option outputs from one logical batch. Context alone
        # does not lift the server's separate question/options batch limit.
        batch-size = cfg.kev.contextSize;
        n-gpu-layers = cfg.kev.gpuLayers; load-on-startup = true; };
    }
    // lib.optionalAttrs managedPlanner {
      "${plannerAlias}" = { model = cfg.planner.modelFile; ctx-size = cfg.planner.contextSize;
        n-gpu-layers = cfg.planner.gpuLayers; load-on-startup = true;
        jinja = true; chat-template-kwargs = ''{"enable_thinking":false}''; };
    }
  ));
  modelSpec = pkgs.writeText "aurora-models.json" (builtins.toJSON ({
    inherit (cfg.models) silero revisions;
    stt = cfg.recognition.model;
    realtimeStt = cfg.recognition.realtimeModel;
    wakeWord = cfg.wakeWord.name;
    wakeSource = cfg.wakeWord.source;
    tts = cfg.speech.model;
    voice = cfg.speech.voice;
    plannerModel = if cfg.planner.manageService then cfg.planner.model else null;
    kevDecisionModel = if cfg.kev.enable && cfg.kev.manageService then cfg.kev.model else null;
  } // lib.optionalAttrs cfg.retrieval.enable {
    retrieval = { repo = cfg.retrieval.model;
      inherit (cfg.retrieval) revision onnxFile tokenizerFile pooling maxTokens threads; };
  }));
  modelCheck = lib.escapeShellArgs [ "${cfg.package}/bin/aurora-models"
    "--config" modelSpec "--root" cfg.models.directory "--check" ];
  packages = self.packages.${pkgs.stdenv.hostPlatform.system};
  runtimeConfig = pkgs.writeText "aurora-assistant.json" (builtins.toJSON {
    inference = { url = routerUrl; models = managedModels; startupTimeoutSeconds = cfg.inference.startupTimeoutSeconds; };
    webSearch = { inherit (cfg.webSearch) enable url maxResults language; };
    execution = { backend = cfg.execution.backend; confirmationPolicy = cfg.execution.confirmationPolicy;
      executable = if cfg.execution.backend == "mcp" then "${cfg.execution.package}/bin/aurora-mcdbus" else null; };
    retrieval = {
      inherit (cfg.retrieval) enable model pooling maxTokens maxDocuments threads queryPrefix timeoutSeconds;
      directory = cfg.retrieval.modelDirectory;
    };
    apps = cfg.applications;
    dbus_actions = cfg.dbusActions;
    settings = { enable = true; inherit (cfg.settings) discoveryMode discoveryScope scanMaxObjects scanTimeoutSeconds; sessionPrefixes = cfg.settings.sessionPrefixes;
      systemPrefixes = cfg.settings.systemPrefixes; maxRounds = cfg.settings.maxRounds; };
    kev = { inherit (cfg.kev) enable url threshold timeoutSeconds maxRounds announceEscalation escalationMessage contextSize; model = kevAlias; };
    safety = { inherit (cfg.safety) enable backend; model = if managedPlanner && cfg.safety.model == cfg.planner.model then plannerAlias else cfg.safety.model; };
    diagnostics = { inherit (cfg.diagnostics) logContent; };
    catalog = { inherit (cfg.catalog) enrich persist idleSeconds intervalSeconds timeoutSeconds; };
    presentation = { inherit (cfg.overlay) resultSeconds errorSeconds;
      agentTimeoutSeconds = cfg.conversation.timeoutSeconds; };
    conversation = { inherit (cfg.conversation) followUpSeconds maxFollowUps; };
    commands = {
      wpctl = "${pkgs.wireplumber}/bin/wpctl";
      playerctl = "${pkgs.playerctl}/bin/playerctl";
      gtk-launch = "${pkgs.gtk3}/bin/gtk-launch";
      plasma-colors = "${pkgs.kdePackages.plasma-workspace}/bin/plasma-apply-colorscheme";
      plasma-theme = "${pkgs.kdePackages.plasma-workspace}/bin/plasma-apply-lookandfeel";
      kreadconfig = "${pkgs.kdePackages.kconfig}/bin/kreadconfig6";
    };
    llm = { inherit (cfg.planner) url; model = plannerAlias; };
    tts = { url = "http://127.0.0.1:${toString cfg.speech.port}/v1";
      model = cfg.speech.model; voice = cfg.speech.voice; wordSync = cfg.speech.wordSync; };
    stt = {
      model = cfg.recognition.modelDirectory;
      realtime_model = cfg.recognition.realtimeModelDirectory;
      wake_model = cfg.wakeWord.modelFile;
      embedding_model = "${assetRoot}/embedding_model.onnx";
      melspectrogram_model = "${assetRoot}/melspectrogram.onnx";
      silero_model = "${assetRoot}/silero_vad.onnx";
      silence_seconds = cfg.recognition.silenceSeconds;
      wake_threshold = cfg.wakeWord.threshold;
      wake_timeout = cfg.wakeWord.timeoutSeconds;
      max_utterance_seconds = cfg.recognition.maxUtteranceSeconds;
      device = "cpu";
      compute_type = "int8";
      language = cfg.recognition.language;
      input_device = cfg.recognition.inputDevice;
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
      StandardOutput = "journal";
      StandardError = "journal";
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
  imports = [
    ./option-renames.nix
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "kev" "port" ] [ "programs" "aurora-assistant" "inference" "port" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "kev" "package" ] [ "programs" "aurora-assistant" "inference" "package" ])
    (lib.mkRemovedOptionModule [ "programs" "aurora-assistant" "ollama" "enable" ]
      "Aurora now manages llama.cpp. Remove ollama.enable; use planner.manageService for an external local chat server.")
    (lib.mkRemovedOptionModule [ "programs" "aurora-assistant" "ollama" "model" ]
      "Use planner.model with a GGUF name, for example hf.co/Qwen/Qwen3-4B-GGUF:Q4_K_M. Ollama tags cannot be used as GGUF names.")
  ];
  options.programs.aurora-assistant = {
    enable = lib.mkEnableOption "local Aurora voice assistant for Plasma Wayland";
    wakeWord.name = lib.mkOption {
        description = "Built-in openWakeWord model name, or a label for wakeWord.source. A text label does not train a new spoken phrase."; type = types.str; default = "hey_jarvis"; example = "hey_mycroft"; };
    wakeWord.source = lib.mkOption {
        description = "Optional public Hugging Face source for a trained custom wake-word ONNX model. Null selects the built-in model named by wakeWord.name."; default = null; type = types.nullOr (types.submodule {
        options = {
          repo = lib.mkOption {
            description = "Public Hugging Face repository ID containing the trained wake-word model."; type = types.str; };
          revision = lib.mkOption {
            description = "Exact Hugging Face commit for the custom wake model. Pin a commit for reproducible downloads."; type = types.str; };
          file = lib.mkOption {
            description = "Repository-relative path to the compatible trained ONNX wake model."; type = types.str; };
        };
      }); };
    wakeWord.modelFile = lib.mkOption { type = types.str; default = "${assetRoot}/wake.onnx";
      description = "Absolute path to the trained openWakeWord ONNX wake-phrase model."; };
    wakeWord.threshold = lib.mkOption {
      description = "Wake detector threshold from 0.01 to one; zero is rejected because it activates on zero-confidence scores. Higher values reduce sensitivity; the useful threshold depends on the microphone and trained model."; type = types.numbers.between 0.01 1; default = 0.5; };
    wakeWord.timeoutSeconds = lib.mkOption {
      description = "Seconds allowed to start speaking after wake-word activation."; type = types.numbers.between 1 60; default = 8; };
    recognition.model = lib.mkOption {
        description = "Final speech model: a faster-whisper short name or a public Hugging Face CTranslate2 repository ID. Download failures stop provisioning."; type = types.str; default = "base.en"; };
    recognition.realtimeModel = lib.mkOption {
        description = "Provisional speech model used while speaking. A small model reduces update latency; final recognition uses recognition.model."; type = types.str; default = "tiny.en"; };
    recognition.modelDirectory = lib.mkOption { type = types.str; default = "${assetRoot}/whisper";
      description = "Absolute path to the final CTranslate2 speech recognition model."; };
    recognition.realtimeModelDirectory = lib.mkOption { type = types.str; default = "${assetRoot}/whisper-realtime";
      description = "Absolute path to the provisional CTranslate2 speech recognition model."; };
    recognition.silenceSeconds = lib.mkOption {
      description = "Seconds of silence that finalize recognition after speech. Increase this value to allow longer pauses."; type = types.numbers.between 0.2 5; default = 0.7; };
    recognition.maxUtteranceSeconds = lib.mkOption {
      description = "Maximum seconds for a voice turn including final transcription. A timeout discards the request and reloads recognition."; type = types.numbers.between 5 300; default = 45; };
    recognition.inputDevice = lib.mkOption {
      description = "SoundDevice input index or device-name substring. Null uses the default input. Select a microphone rather than a monitor source."; type = types.nullOr (types.either types.int types.str); default = null; };
    recognition.language = lib.mkOption {
      description = "Whisper language code for recognition. TTS currently uses English; changing this does not change synthesis language."; type = types.str; default = "en"; };
    speech.model = lib.mkOption {
        description = "Supertonic model name: supertonic, supertonic-2, or supertonic-3. Models are downloaded at provisioning, never during synthesis."; type = types.str; default = "supertonic-3"; };
    speech.voice = lib.mkOption {
      description = "Supertonic voice style, F1 through F5 or M1 through M5. Provisioning checks that the style exists in the selected model."; type = types.enum [ "M1" "M2" "M3" "M4" "M5" "F1" "F2" "F3" "F4" "F5" ]; default = "F1"; };
    speech.wordSync = lib.mkOption {
      type = types.bool; default = true;
      description = "Align reply words locally against generated audio and reveal text using the playback device clock. Reuses recognition.realtimeModelDirectory in the TTS service, adding memory and preparation latency. Alignment failures use chunk captions, not fabricated word timestamps.";
    };
    speech.port = lib.mkOption {
      description = "Loopback TCP port for the local OpenAI-compatible speech endpoint. Must be free on the host."; type = types.port; default = 7788; };
    overlay.resultSeconds = lib.mkOption { type = types.numbers.between 2 60; default = 6;
      description = "Keep the completed result visible this long after speech ends."; };
    overlay.errorSeconds = lib.mkOption { type = types.numbers.between 3 120; default = 10;
      description = "Keep error messages visible this long before returning to idle."; };
    conversation.timeoutSeconds = lib.mkOption { type = types.numbers.between 10 300; default = 60;
      description = "Maximum planning, discovery, review and approval time per request. Timeouts show an error instead of waiting indefinitely."; };

    overlay.package = lib.mkOption {
      description = "Qt 6 Wayland overlay package. Replacements must implement the pinned VoiceOverlay1 D-Bus interface."; type = types.package; default = packages.default; defaultText = lib.literalExpression "self.packages.<system>.default"; };
    inference.package = lib.mkOption {
      type = types.package; default = packages.llama-server;
      defaultText = lib.literalExpression "self.packages.<system>.llama-server";
      description = "Shared llama.cpp package for Kev and the planner. Uses nixpkgs at version 0.7.0 or newer, otherwise a pinned compatibility build. A GPU-enabled package can be supplied here.";
    };
    user = lib.mkOption { type = types.str; description = "Existing desktop account that runs the assistant services and owns model files. This module does not create the account or configure login."; example = "alice"; };
    package = lib.mkOption {
      description = "Python runtime package that provides the controller, model provisioner, TTS server, approval CLI, and desktop D-Bus adapter."; type = types.package; default = packages.assistant; defaultText = lib.literalExpression "self.packages.<system>.assistant"; };

    models = {
      directory = lib.mkOption { type = types.str; default = "/var/lib/aurora-models";
      description = "Absolute writable directory for model generations. Named provisioning uses its current symlink. Keep managed assets outside home because provisioning uses ProtectHome."; };
      enable = lib.mkOption { type = types.bool; default = true;
        description = "Provision named models in a separate online setup service."; };

      silero = lib.mkOption {
        description = "Voice activity model identifier. Currently only silero-vad is supported; its file comes from the locked Python package."; type = types.str; default = "silero-vad"; };

      revisions = lib.mkOption { type = types.attrsOf types.str; default = {};
        description = "Optional Hugging Face revisions keyed by stt, realtimeStt, tts, kev, or planner."; };
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
      description = "Try Kev first for common requests. Uncertain, invalid, or timed-out routes go to planner.model before any action runs.";
    };
    kev.maxRounds = lib.mkOption {
      type = types.ints.between 1 4; default = 2;
      description = "Maximum Kev decision rounds, including selection from observed D-Bus capabilities. Finite arguments can use further Kev decisions; free-form arguments escalate to the planner. These rounds count toward settings.maxRounds.";
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
      type = types.str; default = "hf.co/ggml-org/Kev-4B-GGUF:Q4_K_M";
      description = "Actual Kev decision-model GGUF, provisioned by name and served through llama.cpp /v1/systemone. This is not an Ollama chat router.";
    };
    kev.manageService = lib.mkOption { type = types.bool; default = true;
      description = "Include Kev in the managed llama.cpp router and provision its GGUF."; };
    kev.url = lib.mkOption { type = types.str; default = routerUrl;
      description = "Local literal-loopback System One server URL. Defaults to the shared router. Set manageService=false to use an existing compatible server."; };
    kev.modelFile = lib.mkOption { type = types.str; default = "${assetRoot}/kev.gguf";
      description = "Local Kev GGUF path. Normal operation never downloads model files."; };
    kev.gpuLayers = lib.mkOption { type = types.ints.unsigned; default = 0;
      description = "Layers offloaded by llama.cpp. Zero selects CPU; use a GPU-enabled inference.package before increasing this."; };
    kev.contextSize = lib.mkOption { type = types.ints.between 4096 65536; default = 32768;
      description = "Managed Kev context capacity in tokens, including capability state and decision questions. Longer accepted contexts do not guarantee equivalent accuracy; upstream Kev-4B validation reports 8192 tokens. Also used for client request budgeting."; };
    kev.cacheRamMiB = lib.mkOption { type = types.ints.unsigned; default = 512;
      description = "Explicit llama.cpp decision-model prompt-cache budget in MiB. Zero disables it. Stable capability prefixes enable reuse; changed D-Bus descriptions invalidate their prefix naturally. Cache savings require target-host measurement."; };
    kev.timeoutSeconds = lib.mkOption { type = types.numbers.between 1 60; default = 10;
      description = "Deadline for each Kev decision; routing timeout escalates and review timeout requires approval."; };
    kev.threshold = lib.mkOption { type = types.numbers.between 0.5 1; default = 0.95;
      description = "Minimum selected-option probability for automatic routing or low-risk review. Generic D-Bus mutations still require approval."; };
    catalog = {
      enrich = lib.mkOption { type = types.bool; default = false;
        description = "Use the local planner while idle to write unverified explanations of observed D-Bus members. No commands execute during enrichment. Wake/speech activity cancels the client request; server cancellation latency depends on the backend."; };
      persist = lib.mkOption { type = types.bool; default = true;
        description = "Cache up to 512 model explanations for seven days under the desktop user's XDG cache directory. Only explanations and signature fingerprints persist; live executable capabilities must be rediscovered. Cached text can contain service or application names."; };
      idleSeconds = lib.mkOption { type = types.ints.between 15 3600; default = 60;
        description = "Minimum quiet period before background catalog enrichment starts. No enrichment runs during an active turn or clarification wait."; };
      intervalSeconds = lib.mkOption { type = types.ints.between 30 86400; default = 240;
        description = "Minimum pause between background explanation attempts. Each attempt describes only one observed member; failures are not retried for an hour."; };
      timeoutSeconds = lib.mkOption { type = types.ints.between 1 60; default = 15;
        description = "Deadline for a background explanation request. Failure never prevents ordinary voice requests."; };
    };
    diagnostics.logContent = lib.mkOption { type = types.bool; default = false;
      description = "Include transcripts, replies, model output and exception messages in the local journal. Off by default; timing and error events are always logged. Never records audio."; };

    conversation.followUpSeconds = lib.mkOption { type = types.numbers.between 0 60; default = 12;
      description = "Listen without another wake word after a clarification question for this many seconds. Zero disables follow-up listening."; };
    conversation.maxFollowUps = lib.mkOption { type = types.ints.between 0 4; default = 2;
      description = "Maximum consecutive clarification replies retained in memory for one conversation."; };
    safety.backend = lib.mkOption { type = types.enum [ "kev" "planner" ]; default = if cfg.kev.enable then "kev" else "planner";
      description = "Use Kev's noul decision for review, or the planner model in a separate tool-free chat context. Neither bypasses deterministic approval requirements."; };
    safety.enable = lib.mkOption { type = types.bool; default = true;
      description = "Review plans outside the validated routine capability policy with a separate local model context. Policy is independent of request wording. Generic D-Bus mutations still require human approval; routine policy cannot override an adapter approval requirement."; };
    safety.model = lib.mkOption {
      description = "Model alias used in a separate tool-free review context. With the managed single-model server this must match planner.model. Review does not replace deterministic approval rules."; type = types.str; default = cfg.planner.model; };
    retrieval = {
      enable = lib.mkEnableOption "experimental offline embedding recall for planner evidence (Kev routing is unchanged)";
      model = lib.mkOption { type = types.nullOr types.str; default = null;
        description = "Explicit Hugging Face repository containing the ONNX encoder and tokenizer. Required when recall is enabled."; };
      revision = lib.mkOption { type = types.str; default = "main";
        description = "Provisioning revision, resolved to a commit once and recorded in the model manifest."; };
      onnxFile = lib.mkOption { type = types.str; default = "onnx/model_quantized.onnx";
        description = "Relative self-contained ONNX encoder file in the named repository. External weight files are not supported."; };
      tokenizerFile = lib.mkOption { type = types.str; default = "tokenizer.json";
        description = "Relative tokenizers JSON file in the named repository."; };
      modelDirectory = lib.mkOption { type = types.str; default = "${assetRoot}/retrieval";
        description = "Absolute directory containing model.onnx and tokenizer.json. Runtime never downloads assets."; };
      pooling = lib.mkOption { type = types.enum [ "mean" "cls" ]; default = "mean";
        description = "Pooling required by the chosen embedding model; verify against its model card."; };
      queryPrefix = lib.mkOption { type = types.str; default = "";
        description = "Query prefix required by the chosen embedding model, if any."; };
      maxTokens = lib.mkOption { type = types.ints.between 16 512; default = 256;
        description = "Maximum tokens per document or query."; };
      maxDocuments = lib.mkOption { type = types.ints.between 1 256; default = 64;
        description = "Maximum observed documents embedded, ordered by lexical relevance."; };
      threads = lib.mkOption { type = types.ints.between 1 4; default = 1;
        description = "CPU threads for the optional local encoder."; };
      timeoutSeconds = lib.mkOption { type = types.numbers.between 1 30; default = 5;
        description = "Recall request deadline; expiry terminates the worker and uses lexical evidence until controller restart."; };
    };
    execution.backend = lib.mkOption {
      type = types.enum [ "direct" "mcp" ]; default = "mcp";
      description = "MCP transports all controller desktop actions, adapter queries and generic discovery. Destructive operations require exact human consent; ordinary operations use bounded policy grants. Direct is an explicit legacy rollback option. Overlay IPC keeps its pinned contract.";
    };
    execution.confirmationPolicy = lib.mkOption {
      type = types.enum [ "destructive" "always" ]; default = "destructive";
      description = "Destructive policy runs understood requested ordinary operations under standing consent, asks before destructive operations, and refuses unknown effects. Always retains blanket approval. Spoken approval is available during voice operation; exact plans remain available through aurora-control pending.";
    };
    execution.package = lib.mkOption {
      type = types.package; default = packages.mcdbus;
      description = "Installed strict MCP D-Bus server. No runtime package downloads.";
    };
    settings.discoveryScope = lib.mkOption {
      type = types.enum [ "all" "restricted" ]; default = "all";
      description = "MCP discovery scope. All exposes running well-known services on both buses subject to desktop permissions; restricted applies namespace prefixes. Discovery does not grant execution permission.";
    };
    settings.sessionPrefixes = lib.mkOption {
      description = "Allowed session-bus service namespaces for generic discovery and calls. Each entry matches its exact name and dot-separated descendants; empty entries match nothing. Defaults cover KDE, MPRIS, the overlay, and the Aurora desktop adapter. Sensitive services remain excluded."; type = types.listOf types.str; default = [ "org.kde." "org.mpris." "org.example.VoiceOverlay" "org.aurora.Desktop" ]; };
    settings.systemPrefixes = lib.mkOption {
      description = "Allowed system-bus service namespaces, matched at dot boundaries; empty entries match nothing. Normal D-Bus and Polkit rules apply. Generic changes always require local approval."; type = types.listOf types.str; default = [ "org.freedesktop.UPower" ]; };
    settings.discoveryMode = lib.mkOption {
      type = types.enum [ "realtime" "startup" "periodic" ]; default = "realtime";
      description = "Realtime lists running services per request and inspects relevant objects on demand. No startup crawl or cross-request service catalog is used. Startup and periodic retain legacy scan modes. Execution rechecks live ownership and types.";
    };
    settings.scanMaxObjects = lib.mkOption { type = types.ints.between 1 128; default = 24;
      description = "Maximum objects attempted in each legacy startup/periodic scan. Realtime inspection is bounded by maxRounds and four actions per round."; };
    settings.scanTimeoutSeconds = lib.mkOption { type = types.numbers.between 1 30; default = 6;
      description = "Deadline for each realtime service listing, or each legacy native scan. Individual MCP calls and the complete request also have deadlines."; };
    settings.maxRounds = lib.mkOption {
      description = "Maximum discovery/planning rounds per request. Each round allows at most four actions. No mutations run when discovery exhausts this limit."; type = types.ints.between 1 8; default = 5; };

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

    inference.port = lib.mkOption { type = types.port; default = 8008;
      description = "Loopback port shared by Kev and planner APIs on the managed llama.cpp router."; };
    inference.startupTimeoutSeconds = lib.mkOption { type = types.ints.between 30 600; default = 180;
      description = "Startup deadline while the shared router loads all managed models and TTS becomes ready. Does not extend per-turn deadlines."; };
    planner = {
      model = lib.mkOption { type = types.str; default = "hf.co/Qwen/Qwen3-4B-GGUF:Q4_K_M";
        description = "Planner GGUF name in hf.co/owner/repository:QUANT format. Provisioning resolves one exact GGUF and fails on missing or ambiguous matches. Also used as the local API model alias."; };
      manageService = lib.mkOption { type = types.bool; default = true;
        description = "Include the planner in the managed llama.cpp router and provision its GGUF. Disable to use an existing loopback OpenAI-compatible chat server."; };
      url = lib.mkOption { type = types.str; default = "${routerUrl}/v1";
        defaultText = lib.literalExpression ''"http://127.0.0.1:<inference.port>/v1"'';
        description = "Loopback OpenAI-compatible chat API URL including /v1. A custom URL requires manageService=false."; };
      modelFile = lib.mkOption { type = types.str; default = "${assetRoot}/planner.gguf";
        defaultText = lib.literalExpression ''"<assetRoot>/planner.gguf"'';
        description = "Local planner GGUF path. Managed named provisioning writes planner.gguf. For manually installed files, disable models.enable."; };
      contextSize = lib.mkOption { type = types.ints.between 4096 131072; default = 32768;
        description = "Planner context capacity in tokens, including action schemas, observations and response. Larger values require more memory. The selected model must support this capacity."; };
      gpuLayers = lib.mkOption { type = types.ints.unsigned; default = 0;
        description = "Planner layers to offload. Zero selects CPU. Supply a GPU-enabled inference.package before increasing this."; };
    };
  };
  config = lib.mkIf cfg.enable {
    assertions = [
      { assertion = !cfg.retrieval.enable || (cfg.retrieval.model != null && cfg.retrieval.model != "");
        message = "Aurora retrieval requires an explicit model repository."; }
      { assertion = !managedPlanner || cfg.planner.url == "${routerUrl}/v1";
        message = "A custom planner URL requires planner.manageService=false."; }
      { assertion = !managedKev || cfg.kev.url == routerUrl;
        message = "A custom Kev URL requires kev.manageService=false."; }
      { assertion = managedModels == [] || (cfg.inference.port != cfg.speech.port
          && (!(cfg.webSearch.enable && cfg.webSearch.manageService) || cfg.inference.port != cfg.webSearch.port));
        message = "The inference router must use a different port from TTS and managed search."; }
      { assertion = !(managedKev && managedPlanner) || kevAlias != plannerAlias;
        message = "Kev and the planner need distinct model names in the router preset."; }
      { assertion = lib.all (value: !(lib.hasInfix "\n" value || lib.hasInfix "\r" value || lib.hasInfix "#" value || lib.hasInfix ";" value))
          (managedModels ++ lib.optional managedKev cfg.kev.modelFile ++ lib.optional managedPlanner cfg.planner.modelFile)
          && lib.all (value: !(lib.hasInfix "]" value || lib.hasInfix "[" value)) managedModels;
        message = "Managed model names and paths must be single-line INI values without comment characters; names cannot contain brackets."; }
      { assertion = !(managedPlanner && cfg.safety.enable && cfg.safety.backend == "planner") || cfg.safety.model == cfg.planner.model;
        message = "safety.model must match planner.model when using the managed planner for review."; }
      { assertion = cfg.safety.backend != "kev" || cfg.kev.enable;
        message = "Aurora safety.backend=kev requires kev.enable=true."; }
      { assertion = lib.hasPrefix "/" cfg.models.directory;
      message = "programs.aurora-assistant.modelDirectory must be absolute."; }
      { assertion = !(cfg.webSearch.enable && cfg.webSearch.manageService) ||
          cfg.webSearch.url == "http://127.0.0.1:${toString cfg.webSearch.port}";
        message = "A custom Aurora search URL requires webSearch.manageService=false."; }
      { assertion = !(cfg.webSearch.enable && cfg.webSearch.manageService) || cfg.webSearch.engines != [];
        message = "Aurora managed search requires at least one search engine."; }
    ];
    environment.systemPackages = [ cfg.package cfg.overlay.package ];
    environment.etc."aurora-assistant/models.json".source = modelSpec;
    systemd.tmpfiles.rules = lib.mkIf cfg.models.enable [
      "d ${lib.escapeShellArg cfg.models.directory} 0750 ${cfg.user} - -"
    ];
    systemd.services.aurora-models = lib.mkIf cfg.models.enable {
      description = "Provision named local Aurora models";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];
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
        ReadWritePaths = [ cfg.models.directory ];
        TimeoutStartSec = "1h";
        ExecStart = lib.escapeShellArgs [ "${cfg.package}/bin/aurora-models"
          "--config" modelSpec "--root" cfg.models.directory ];
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
        ExecStart = "${cfg.overlay.package}/bin/aurora-voice-overlay"; };
      environment.QT_QPA_PLATFORM = "wayland";
    };
    systemd.user.services.aurora-tts = lib.recursiveUpdate common {
      description = "Local Supertonic speech API";
      serviceConfig.ExecStartPre = lib.optional cfg.models.enable modelCheck;
      environment = offline;
      serviceConfig.ExecStart = lib.escapeShellArgs ([ "${cfg.package}/bin/aurora-tts"
        "--model-dir" "${assetRoot}/supertonic" "--model" cfg.speech.model "--port" (toString cfg.speech.port) ] ++ lib.optionals cfg.speech.wordSync [ "--alignment-model" cfg.recognition.realtimeModelDirectory ]);
    };
    systemd.user.services.aurora-inference = lib.mkIf (managedModels != []) (lib.recursiveUpdate common {
      description = "Local Aurora llama.cpp model router";
      environment = offline // { LLAMA_CACHE = "%t/aurora-inference/cache"; };
      serviceConfig.ExecStartPre = lib.optional cfg.models.enable modelCheck;
      serviceConfig.RuntimeDirectory = "aurora-inference";
      serviceConfig.RuntimeDirectoryMode = "0700";
      serviceConfig.KillMode = "control-group";
      serviceConfig.ExecStart = lib.escapeShellArgs [ "${cfg.inference.package}/bin/llama-server"
        "--models-preset" routerPreset "--models-max" (toString (builtins.length managedModels))
        "--host" "127.0.0.1" "--port" (toString cfg.inference.port) ];
    });
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
      wants = [ "aurora-voice-overlay.service" "aurora-tts.service" "aurora-desktop.service" ] ++ lib.optional (managedModels != []) "aurora-inference.service";
      after = [ "aurora-voice-overlay.service" "aurora-tts.service" "aurora-desktop.service" ] ++ lib.optional (managedModels != []) "aurora-inference.service";
      environment = offline;
      serviceConfig.ExecStart = "${cfg.package}/bin/aurora-assistant --config ${runtimeConfig}";
    };
  };
}
