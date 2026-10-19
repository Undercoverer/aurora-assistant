{
  description = "Aurora with flake-parts and import-tree";
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
    import-tree.url = "github:denful/import-tree";
    aurora.url = "github:Undercoverer/aurora-assistant";
  };
  outputs = inputs: inputs.flake-parts.lib.mkFlake { inherit inputs; } {
    systems = [ "x86_64-linux" ];
    # Only flake-parts modules go in parts. Host modules are outside this tree.
    imports = [ (inputs.import-tree ./parts) ];
  };
}
