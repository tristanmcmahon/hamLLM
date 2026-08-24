{ pkgs ? import <nixpkgs> {} }:

pkgs.buildEnv {
  name = "hamllm-env";
  paths = [ pkgs.python310 pkgs.python310Packages.pytest ];
}
