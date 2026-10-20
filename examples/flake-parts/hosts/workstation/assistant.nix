{ ... }: {
  programs.aurora-assistant = {
    enable = true;
    user = "alice"; # Existing Plasma account.
    wakeWord.name = "alexa"; # A trained phrase, not arbitrary text.
    recognition.silenceSeconds = 0.7;
    speech.voice = "F1";
    # Kev, Qwen, Supertonic and their local services use the defaults.
  };
}
