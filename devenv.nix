{
  inputs,
  pkgs,
  lib,
  ...
}:
let
  # Upstream's lock supplies Glaze 8, but this compositor requires Glaze 7.
  glaze = (pkgs.glaze.override { enableSSL = false; }).overrideAttrs {
    version = "7.2.0";
    src = pkgs.fetchFromGitHub {
      owner = "stephenberry";
      repo = "glaze";
      tag = "v7.2.0";
      hash = "sha256-f3NVRi3SXKo42hn0WCw7JsOK3EkdOVJIcuzhPorKjFY=";
    };
    cmakeFlags = [
      "-Dglaze_ENABLE_SSL=OFF"
      "-Dglaze_DISABLE_SIMD_WHEN_SUPPORTED=ON"
    ];
  };
  hyprland = inputs.hyprland.packages.${pkgs.stdenv.hostPlatform.system}.hyprland.override {
    glaze-hyprland = glaze;
  };
in
{
  stdenv = hyprland.stdenv;

  packages = [
    hyprland
    hyprland.dev
    pkgs.cmake
    pkgs.ninja
    pkgs.gnumake
    pkgs.pkg-config
    pkgs.git
    pkgs.python3
    pkgs.binutils
    pkgs.foot
    pkgs.grim
    pkgs.wtype
    pkgs.lua5_5
    pkgs.libGL
  ]
  ++ hyprland.buildInputs;

  # ctypes loads xkbcommon by soname rather than through a linked executable.
  env.LD_LIBRARY_PATH = lib.makeLibraryPath [ pkgs.libxkbcommon ];
}
