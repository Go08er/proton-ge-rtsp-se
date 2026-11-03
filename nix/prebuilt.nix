{ lib, stdenvNoCC, fetchurl, localArchive ? null }:
let
  release = import ./release.nix;
in stdenvNoCC.mkDerivation {
  pname = "proton-ge-rtsp-slop-edition";
  version = "se3";
  src = if localArchive != null then localArchive else fetchurl {
    inherit (release) url hash;
  };
  sourceRoot = "proton-ge-11-11-rtsp-se3";
  outputs = [ "out" "steamcompattool" ];
  dontConfigure = true;
  dontBuild = true;
  dontFixup = true;
  dontStrip = true;
  dontPatchShebangs = true;
  installPhase = ''
    runHook preInstall
    echo "Use programs.steam.extraCompatPackages, not environment.systemPackages." > "$out"
    mkdir -p "$steamcompattool"
    cp -a ./. "$steamcompattool/"
    runHook postInstall
  '';
  meta = {
    description = "Experimental GE-Proton11-11 RTSP compatibility tool";
    homepage = "https://github.com/Go08er/proton-ge-rtsp-se";
    platforms = [ "x86_64-linux" ];
    # Aggregate: component/file licenses remain authoritative.
    license = with lib.licenses; [ bsd3 lgpl21Plus gpl2Plus gpl3Plus mit zlib ];
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
  };
}
