{
  description = "Themeable Wayland/KWin voice assistant overlay";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
    };
  };

  outputs = { self, nixpkgs, pyproject-nix, uv2nix, pyproject-build-systems }:
    let
      systems = [ "x86_64-linux" ];
      eachSystem = f: nixpkgs.lib.genAttrs systems (
        system: f system (import nixpkgs { inherit system; })
      );
    workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };
      pythonSet = pkgs: (pkgs.callPackage pyproject-nix.build.packages {
        python = pkgs.python311;
      }).overrideScope (pkgs.lib.composeManyExtensions [
        pyproject-build-systems.overlays.wheel
        (workspace.mkPyprojectOverlay { sourcePreference = "wheel"; })
        (final: prev: {
          aurora-assistant = prev.aurora-assistant.overrideAttrs (old: {
            nativeBuildInputs = (old.nativeBuildInputs or []) ++ final.resolveBuildSystem { hatchling = []; };
          });
          halo = prev.halo.overrideAttrs (old: {
            nativeBuildInputs = (old.nativeBuildInputs or []) ++ final.resolveBuildSystem { setuptools = []; };
          });
          torchaudio = prev.torchaudio.overrideAttrs (old: {
            buildInputs = (old.buildInputs or []) ++ [ final.torch pkgs.sox ];
            preFixup = (old.preFixup or "") + ''
              addAutoPatchelfSearchPath "${final.torch}/${final.python.sitePackages}/torch/lib"
              # Aurora uses SoundDevice/SoundFile, not torio's optional FFmpeg I/O.
              # Remove all bundled version-specific plugins instead of leaving
              # unresolved FFmpeg 4/5/6 dependencies or ignoring patch failures.
              rm -f "$out/${final.python.sitePackages}/torio/lib/"*ffmpeg*.so
            '';
          });
          sounddevice = prev.sounddevice.overrideAttrs (old: {
            buildInputs = (old.buildInputs or []) ++ [ pkgs.portaudio ];
            postInstall = (old.postInstall or "") + ''
              substituteInPlace "$out/${final.python.sitePackages}/sounddevice.py" \
                --replace-fail '_libname = _find_library(_libname)' \
                '_libname = "${pkgs.lib.getLib pkgs.portaudio}/lib/libportaudio.so.2"'
            '';
          });
          pyaudio = prev.pyaudio.overrideAttrs (old: {
            buildInputs = (old.buildInputs or []) ++ [ pkgs.portaudio ];
            nativeBuildInputs = (old.nativeBuildInputs or []) ++ [ pkgs.pkg-config ] ++ final.resolveBuildSystem { setuptools = []; wheel = []; };
          });
        })
      ]);
    in {
      nixosModules.default = import ./nix/module.nix self;
      packages = eachSystem (system: pkgs: let
        env = (pythonSet pkgs).mkVirtualEnv "aurora-python" { aurora-assistant = [ "voice" ]; };
        optionEval = nixpkgs.lib.nixosSystem {
          inherit system;
          modules = [ self.nixosModules.default ];
        };
        optionDocs = pkgs.nixosOptionsDoc {
          options = { programs.aurora-assistant = optionEval.options.programs.aurora-assistant; };
          warningsAreErrors = true;
          transformOptions = opt: opt // {
            declarations = [ "https://github.com/Undercoverer/aurora-assistant/blob/main/nix/module.nix" ];
          };
        };
      in {
        kev-server = self.packages.${system}.llama-server;
        llama-server = if pkgs.lib.versionAtLeast pkgs.llama-cpp.version "0.7.0"
          then pkgs.llama-cpp
          else pkgs.callPackage ./nix/kev-server.nix {};
        docs = pkgs.runCommand "aurora-documentation" {} ''
          mkdir -p $out/share/doc/aurora
          cp -r ${./docs} $out/share/doc/aurora/docs
          cp -r ${./examples} $out/share/doc/aurora/examples
          cp ${optionDocs.optionsCommonMark} $out/share/doc/aurora/OPTIONS.md
          cp ${optionDocs.optionsJSON}/share/doc/nixos/options.json $out/share/doc/aurora/options.json
        '';
        assistant = pkgs.symlinkJoin {
          name = "aurora-assistant";
          paths = [ env ];
          nativeBuildInputs = [ pkgs.makeWrapper ];
          postBuild = ''
            for executable in aurora-assistant aurora-tts aurora-models aurora-control aurora-desktop aurora-report; do
              wrapProgram "$out/bin/$executable" \
                --prefix LD_LIBRARY_PATH : "${pkgs.lib.makeLibraryPath [ pkgs.portaudio pkgs.libsndfile pkgs.stdenv.cc.cc.lib ]}" \
                --prefix PATH : "${pkgs.lib.makeBinPath [ pkgs.systemd pkgs.wl-clipboard ]}" \
                --set AURORA_REVISION "${self.rev or self.dirtyRev or "unversioned"}" \
                --set HF_HUB_OFFLINE 1 --set HF_HUB_DISABLE_TELEMETRY 1 --set TORIO_USE_FFMPEG 0
            done
          '';
          meta.mainProgram = "aurora-assistant";
        };
        default = pkgs.stdenv.mkDerivation {
          pname = "aurora-voice-overlay";
          version = "2.3.0";
          src = ./.;

          nativeBuildInputs = with pkgs; [
            cmake
            ninja
            pkg-config
            qt6.wrapQtAppsHook
            qt6.qtshadertools
          ];

          buildInputs = with pkgs; [
            qt6.qtbase
            qt6.qtdeclarative
            qt6.qtwayland
            kdePackages.layer-shell-qt
            libglvnd
            libGL
          ];

          # The app has an embedded-QML/shader verification mode that does not
          # require a Wayland session or D-Bus. Fail the build if they are absent.
          doCheck = true;
          checkPhase = ''
            runHook preCheck
            ./aurora-voice-overlay --check-resources
            runHook postCheck
          '';

          meta = with pkgs.lib; {
            description = "Configurable animated voice-assistant overlay for KDE Plasma Wayland";
            platforms = platforms.linux;
            mainProgram = "aurora-voice-overlay";
          };
        };
      });

      checks = eachSystem (system: pkgs: {
        configuration = import ./tests/nixos-options.nix { inherit self nixpkgs pkgs system; };
        documentation = self.packages.${system}.docs;
        audioImports = pkgs.runCommand "aurora-audio-imports" {
          nativeBuildInputs = [ self.packages.${system}.assistant ];
          LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [ pkgs.portaudio pkgs.libsndfile pkgs.stdenv.cc.cc.lib ];
          TORIO_USE_FFMPEG = "0";
          HF_HUB_OFFLINE = "1";
        } ''
          env -i HOME="$TMPDIR" PATH=/no-external-tools ${self.packages.${system}.assistant}/bin/aurora-assistant --check-audio
          python -c 'import torch, torchaudio, sounddevice, soundfile; assert torch.version.cuda is None; print(torch.__version__, torchaudio.__version__)'
          touch $out
        '';

        backend = pkgs.runCommand "aurora-backend-tests" {
          nativeBuildInputs = [ (pkgs.python311.withPackages (p: [ p.httpx p.dbus-next p.numpy p.soundfile p.fastapi ])) pkgs.dbus ];
        } ''
          export PYTHONPATH=${./backend}
          export AURORA_TEST_CONFIG=${./config/assistant.example.json}
          dbus-run-session -- python -m unittest discover -s ${./tests} -v
          touch $out
        '';
      });

      apps = eachSystem (system: pkgs: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/aurora-voice-overlay";
        };
      });

      devShells = eachSystem (system: pkgs: {
        default = pkgs.mkShell {
          inputsFrom = [ self.packages.${system}.default ];
          packages = with pkgs; [ python311 uv portaudio libsndfile wireplumber playerctl gtk3 ];
          LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [ pkgs.portaudio pkgs.libsndfile pkgs.stdenv.cc.cc.lib ];
        };
      });
    };
}
