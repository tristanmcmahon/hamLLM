{ pkgs ? import <nixpkgs> { } }:

pkgs.python3Packages.buildPythonApplication {
  pname = "hamllm";
  version = "0.1.0";
  pyproject = true;
  src = ./.;

  build-system = with pkgs.python3Packages; [
    setuptools
    wheel
  ];

  pythonImportsCheck = [ "hamllm" ];
}
