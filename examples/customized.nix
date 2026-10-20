{ ... }: {
  programs.aurora-assistant = {
    enable = true;
    user = "alice";
    wakeWord = {
      name = "alexa";
      threshold = 0.5; # Higher means less sensitive.
      timeoutSeconds = 8; # Time to start speaking after activation.
    };
    recognition = {
      model = "base.en";
      realtimeModel = "tiny.en";
      language = "en";
      inputDevice = null; # Use the default microphone.
      silenceSeconds = 0.7;
      maxUtteranceSeconds = 45;
    };
    speech = {
      model = "supertonic-3";
      voice = "F1";
      wordSync = true;
    };
    overlay = { resultSeconds = 6; errorSeconds = 10; };
    conversation = { timeoutSeconds = 60; followUpSeconds = 12; maxFollowUps = 2; };
    kev = {
      model = "hf.co/ggml-org/Kev-4B-GGUF:Q4_K_M";
      contextSize = 32768;
      cacheRamMiB = 512;
      threshold = 0.95;
    };
    planner.model = "hf.co/Qwen/Qwen3-4B-GGUF:Q4_K_M";
    diagnostics.logContent = false;
    # Online search is optional; ordinary voice operation remains local.
    webSearch.enable = false;
    # No application aliases or fixed D-Bus actions are required.
  };
}
