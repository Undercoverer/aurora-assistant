{ ... }: {
  programs.aurora-assistant = {
    enable = true;
    user = "alice"; # Change to an existing Plasma desktop account.
    models = {
      stt = "base.en";
      realtimeStt = "tiny.en";
      wakeWord = "hey_jarvis"; # Spoken phrase comes from the trained model.
      tts = "supertonic-3";
    };
    # All names are provisioned automatically. Invalid names fail setup.
    kev.model = "qwen3:0.6b";
    ollama.model = "qwen3:4b";
    safety.model = "qwen3:4b";
    silenceSeconds = 0.7;
    voice = "F1";
    # No applications or dbusActions entries are needed.
  };
}
