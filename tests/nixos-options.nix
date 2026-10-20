{ self, nixpkgs, pkgs, system }:
let
  evaluate = settings: (nixpkgs.lib.nixosSystem {
    inherit system;
    modules = [ self.nixosModules.default {
      programs.aurora-assistant = { enable = true; user = "alice"; } // settings;
      users.users.alice.isNormalUser = true;
      system.stateVersion = "26.05";
    } ];
  }).config;
  legacy = evaluate {
    models = { wakeWord = "alexa"; stt = "small.en"; realtimeStt = "base.en";
      tts = "supertonic-2"; wakeSource = null; };
    wakeModel = "/var/lib/test/wake.onnx";
    wakeThreshold = 0.6; wakeTimeout = 9;
    sttModel = "/var/lib/test/final"; realtimeSttModel = "/var/lib/test/live";
    silenceSeconds = 1.2; maxUtteranceSeconds = 50;
    inputDevice = "Test microphone"; language = "en";
    voice = "M2"; wordSync = false; ttsPort = 7789;
    presentation = { resultSeconds = 8; errorSeconds = 20; agentTimeoutSeconds = 90; };
    modelDirectory = "/var/lib/test";
    overlayPackage = pkgs.hello; inferencePackage = pkgs.hello;
  };
  grouped = evaluate {
    wakeWord = { name = "alexa"; source = null; modelFile = "/var/lib/test/wake.onnx";
      threshold = 0.6; timeoutSeconds = 9; };
    recognition = { model = "small.en"; realtimeModel = "base.en";
      modelDirectory = "/var/lib/test/final"; realtimeModelDirectory = "/var/lib/test/live";
      silenceSeconds = 1.2; maxUtteranceSeconds = 50;
      inputDevice = "Test microphone"; language = "en"; };
    speech = { model = "supertonic-2"; voice = "M2"; wordSync = false; port = 7789; };
    overlay = { resultSeconds = 8; errorSeconds = 20; package = pkgs.hello; };
    conversation.timeoutSeconds = 90;
    models.directory = "/var/lib/test";
    inference.package = pkgs.hello;
  };
  # Equal store paths here require equal generated runtime configuration/presets.
  services = [ "aurora-controller" "aurora-tts" "aurora-desktop"
    "aurora-voice-overlay" "aurora-inference" ];
  sameServices = builtins.all (name:
    legacy.systemd.user.services.${name}.serviceConfig.ExecStart ==
    grouped.systemd.user.services.${name}.serviceConfig.ExecStart) services;
  defaults = evaluate {};
  basic = evaluate ((import ../examples/basic/assistant.nix {}).programs.aurora-assistant);
  customized = evaluate ((import ../examples/customized.nix {}).programs.aurora-assistant);
in
assert sameServices;
assert legacy.environment.etc."aurora-assistant/models.json".source.outPath ==
  grouped.environment.etc."aurora-assistant/models.json".source.outPath;
assert defaults.programs.aurora-assistant.wakeWord.name == "hey_jarvis";
assert basic.programs.aurora-assistant.wakeWord.name == "alexa";
assert customized.programs.aurora-assistant.speech.voice == "F1";
assert builtins.isString customized.systemd.user.services.aurora-controller.serviceConfig.ExecStart;
pkgs.runCommand "aurora-nixos-options" {} ''touch $out''
