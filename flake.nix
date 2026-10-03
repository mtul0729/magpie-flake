{
  description = "magpie – standalone Nix package (from source)";

  nixConfig = {
    extra-substituters = [ "https://mtul.cachix.org" ];
    extra-trusted-public-keys = [
      "mtul.cachix.org-1:WEuapLtfyNPLkcCbwQh3jLxVwEwQNcDXhru9lbuhDlo="
    ];
  };

  inputs = {
    # Follow your own nixpkgs (add
    # `magpie-flake.inputs.nixpkgs.follows = "nixpkgs";` to your config) so
    # gtk4 and webkitgtk come from the nixpkgs you already have cached —
    # otherwise you pull a second, unrelated nixpkgs for those two.
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { self, nixpkgs }:
    let
      # magpie's desktop window is Wails v3 + cgo on Linux: GTK/WebKitGTK only.
      forAllSystems = nixpkgs.lib.genAttrs [
        "x86_64-linux"
        "aarch64-linux"
      ];
    in
    {
      overlays.default = final: prev: {
        magpie = final.callPackage ./package.nix { };
      };

      packages = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          magpie = pkgs.callPackage ./package.nix { };
        in
        {
          inherit magpie;
          default = magpie;
        }
      );
    };
}
