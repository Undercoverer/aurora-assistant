{ inputs, ... }: {
  flake.nixosConfigurations.workstation = inputs.nixpkgs.lib.nixosSystem {
    system = "x86_64-linux";
    modules = [
      inputs.aurora.nixosModules.default
      # Supply your existing working host configuration at this location.
      ../hosts/workstation/configuration.nix
      ../hosts/workstation/assistant.nix
    ];
  };
}
