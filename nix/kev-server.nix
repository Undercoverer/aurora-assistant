{ lib, stdenv, fetchurl, cmake, ninja, pkg-config, openssl }:
stdenv.mkDerivation {
  pname = "aurora-kev-server";
  version = "0.6.0";
  src = fetchurl {
    name = "llama.cpp-0.6.0.tar.gz";
    url = "https://codeload.github.com/ggml-org/llama.cpp/tar.gz/refs/tags/v0.6.0";
    hash = "sha256-CbNtuiNfysGA7/8YUU2nA45l2OW55K76WSOEaKv97BI=";
  };
  nativeBuildInputs = [ cmake ninja pkg-config ];
  buildInputs = [ openssl ];
  cmakeFlags = [
    "-DGGML_NATIVE=OFF"
    "-DGGML_CPU_ALL_VARIANTS=ON"
    "-DGGML_BACKEND_DL=ON"
    "-DLLAMA_BUILD_EXAMPLES=OFF"
    "-DLLAMA_BUILD_TESTS=OFF"
    "-DLLAMA_BUILD_SERVER=ON"
    "-DLLAMA_BUILD_UI=OFF"
    "-DLLAMA_USE_PREBUILT_UI=OFF"
    "-DLLAMA_OPENSSL=ON"
  ];
  meta = {
    description = "Pinned local System One decision server for Kev, without web UI downloads";
    homepage = "https://github.com/ggml-org/llama.cpp";
    license = lib.licenses.mit;
    platforms = [ "x86_64-linux" ];
    mainProgram = "llama-server";
  };
}
