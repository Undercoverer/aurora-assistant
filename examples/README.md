# Runnable integration examples

Choose `basic` for a regular flake or `flake-parts` for flake-parts plus import-tree.
Both extend an existing working NixOS Plasma Wayland installation. They do not
invent disk, bootloader, networking, account, or hardware settings.

## Regular flake

Copy `basic/flake.nix` and `basic/assistant.nix` to your NixOS configuration folder.
Keep your existing `configuration.nix` there, including its hardware imports.
If a flake already exists, merge the Aurora input and two Aurora module imports
instead of replacing it. Change `alice` in assistant.nix to your existing user.
The host output in this example is named `workstation`; retain your existing name
if it differs.

## flake-parts and import-tree

Copy `flake-parts/flake.nix`, `flake-parts/parts`, and `flake-parts/hosts` into your
configuration folder. Put your existing host configuration at
`hosts/workstation/configuration.nix`. Preserve the relative paths of its hardware
imports, or adjust them after copying. Change `alice` in
`hosts/workstation/assistant.nix`.

`parts/hosts.nix` is a flake-parts module: it defines `flake.nixosConfigurations`.
`hosts/workstation/assistant.nix` is a NixOS module: it defines `programs`.
Do not recursively import both kinds through the same import-tree. Aurora's
`nixosModules.default` belongs in `nixosSystem.modules`, not the flake-parts imports.
In an existing layout, merge these expressions into the corresponding locations.

## Apply either example

Run from the configuration folder:

```sh
# New files must be tracked if this folder is a Git repository.
git add flake.nix assistant.nix  # regular example; use parts/ and hosts/ for flake-parts
nix flake lock
sudo nixos-rebuild switch --flake .#workstation
journalctl -u aurora-models.service -b
systemctl --user status aurora-assistant.target aurora-desktop.service aurora-controller.service
```

Omit `git add` outside a Git repository. If using a private copy of Aurora, configure
GitHub read access outside the flake or use a working SSH input URL. Do not put
access tokens in Nix files. Initial provisioning needs network access, enough disk,
and sufficient RAM to load the selected models. Later voice processing is local.
See [the first-run guide](../docs/QUICKSTART.md) for functional checks and errors.
The example model split is illustrative; three model roles do not imply that
three sets of weights fit in memory simultaneously or that small models always
produce correct arguments.
