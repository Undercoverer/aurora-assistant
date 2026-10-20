{ lib, python311Packages, fetchPypi }:
# nixpkgs provides the inference-free MCP runtime and D-Bus bindings. mcdbus
# itself is absent from the pinned nixpkgs revision, so pin its small wheel.
python311Packages.buildPythonApplication {
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
  dependencies = with python311Packages; [ fastmcp dbus-fast ];
  postInstall = ''
    cp ${../mcp/aurora_mcdbus.py} "$out/${python311Packages.python.sitePackages}/mcdbus/aurora.py"
    substituteInPlace "$out/bin/mcdbus" --replace-fail 'mcdbus.server' 'mcdbus.aurora'
    mv "$out/bin/mcdbus" "$out/bin/aurora-mcdbus"
  '';
  pythonImportsCheck = [ "mcdbus.aurora" ];
  meta = {
    description = "Experimental owner-bound, introspection-typed MCP D-Bus server for Aurora";
    mainProgram = "aurora-mcdbus";
    platforms = lib.platforms.linux;
  };
}
