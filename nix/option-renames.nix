{ lib, ... }: {
  # Keep existing deployments working while documenting the new option paths.
  imports = [
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "models" "wakeWord" ]
      [ "programs" "aurora-assistant" "wakeWord" "name" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "models" "wakeSource" ]
      [ "programs" "aurora-assistant" "wakeWord" "source" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "wakeModel" ]
      [ "programs" "aurora-assistant" "wakeWord" "modelFile" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "wakeThreshold" ]
      [ "programs" "aurora-assistant" "wakeWord" "threshold" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "wakeTimeout" ]
      [ "programs" "aurora-assistant" "wakeWord" "timeoutSeconds" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "models" "stt" ]
      [ "programs" "aurora-assistant" "recognition" "model" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "models" "realtimeStt" ]
      [ "programs" "aurora-assistant" "recognition" "realtimeModel" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "sttModel" ]
      [ "programs" "aurora-assistant" "recognition" "modelDirectory" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "realtimeSttModel" ]
      [ "programs" "aurora-assistant" "recognition" "realtimeModelDirectory" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "silenceSeconds" ]
      [ "programs" "aurora-assistant" "recognition" "silenceSeconds" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "maxUtteranceSeconds" ]
      [ "programs" "aurora-assistant" "recognition" "maxUtteranceSeconds" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "inputDevice" ]
      [ "programs" "aurora-assistant" "recognition" "inputDevice" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "language" ]
      [ "programs" "aurora-assistant" "recognition" "language" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "models" "tts" ]
      [ "programs" "aurora-assistant" "speech" "model" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "voice" ]
      [ "programs" "aurora-assistant" "speech" "voice" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "wordSync" ]
      [ "programs" "aurora-assistant" "speech" "wordSync" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "ttsPort" ]
      [ "programs" "aurora-assistant" "speech" "port" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "presentation" "resultSeconds" ]
      [ "programs" "aurora-assistant" "overlay" "resultSeconds" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "presentation" "errorSeconds" ]
      [ "programs" "aurora-assistant" "overlay" "errorSeconds" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "presentation" "agentTimeoutSeconds" ]
      [ "programs" "aurora-assistant" "conversation" "timeoutSeconds" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "modelDirectory" ]
      [ "programs" "aurora-assistant" "models" "directory" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "overlayPackage" ]
      [ "programs" "aurora-assistant" "overlay" "package" ])
    (lib.mkRenamedOptionModule [ "programs" "aurora-assistant" "inferencePackage" ]
      [ "programs" "aurora-assistant" "inference" "package" ])
  ];
}
