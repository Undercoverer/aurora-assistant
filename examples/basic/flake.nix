{
  description = "Existing NixOS workstation with Aurora";
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    aurora.url = "github:Undercoverer/aurora-assistant";
  };
  outputs = { nixpkgs, aurora, ... }: {
    nixosConfigurations.workstation = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        # Copy your working host configuration here; keep its hardware and boot settings.
        ./configuration.nix
        aurora.nixosModules.default
        ./assistant.nix
      ];
    };
  };
}
