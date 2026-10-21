{ lib, python3Packages, fetchPypi }:
# nixpkgs provides the inference-free MCP runtime and D-Bus bindings. mcdbus
# The separate server uses nixpkgs default Python; Aurora stays on Python 3.11.
# mcdbus itself is absent from the pinned nixpkgs revision, so pin its small wheel.
python3Packages.buildPythonApplication {
  pname = "aurora-mcdbus";
  version = "2026.3.6.3";
  format = "wheel";
  src = fetchPypi {
    pname = "mcdbus";
    version = "2026.3.6.3";
    format = "wheel";
    python = "py3";
    dist = "py3";
    hash = "sha256-yreslrSxv6wltEHefv5DpMOzk5ccn+ZQU5mWJOU5XZM=";
  };
  dependencies = with python3Packages; [ fastmcp dbus-fast ];
  postInstall = ''
    cp ${../mcp/aurora_mcdbus.py} "$out/${python3Packages.python.sitePackages}/mcdbus/aurora.py"
    substituteInPlace "$out/bin/mcdbus" --replace-fail 'mcdbus.server' 'mcdbus.aurora'
    mv "$out/bin/mcdbus" "$out/bin/aurora-mcdbus"
  '';
  doInstallCheck = true;
  installCheckPhase = ''
    runHook preInstallCheck
    AURORA_MCP_EXECUTABLE="$out/bin/aurora-mcdbus" python ${../tests/mcp/test_stdio.py}
    runHook postInstallCheck
  '';
  pythonImportsCheck = [ "mcdbus.aurora" ];
  meta = {
    description = "Experimental owner-bound, introspection-typed MCP D-Bus server for Aurora";
    mainProgram = "aurora-mcdbus";
    platforms = lib.platforms.linux;
  };
}
