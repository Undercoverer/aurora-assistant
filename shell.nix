{ pkgs ? import <nixpkgs> {} }:
let
  qtEnv = pkgs.qt6.env "voice-overlay-qt" (with pkgs.qt6; [
    qtbase
    qtdeclarative
    qtwayland
    qtshadertools
  ]);
in pkgs.mkShell {
  packages = with pkgs; [
    cmake ninja pkg-config gcc
    qtEnv kdePackages.layer-shell-qt
    libGL libglvnd glib python3
  ];
  shellHook = ''
    export QT_QPA_PLATFORM=wayland
    export CMAKE_GENERATOR=Ninja
  '';
}
