#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ "$(uname -sm)" != "Linux x86_64" ]]; then
    printf '%s\n' 'This AppImage recipe requires Linux x86_64.' >&2
    exit 1
fi

work="$PWD/build/appimage"
mkdir -p "$work" dist
stage="$(mktemp -d "$work/stage.XXXXXXXX")"
trap 'rm -rf -- "$stage"' EXIT
export TMPDIR="$stage"

fetch() {
    local url=$1 digest=$2 target=$3
    if [[ -f "$target" ]] && printf '%s  %s\n' "$digest" "$target" | sha256sum --check --status; then
        return
    fi
    curl -fsSL --connect-timeout 15 --max-time 120 --retry 3 "$url" -o "$stage/download"
    printf '%s  %s\n' "$digest" "$stage/download" | sha256sum --check
    mv -- "$stage/download" "$target"
}

tool="$work/appimagetool"
runtime="$work/runtime-x86_64"
fetch https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage \
    ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0 "$tool"
fetch https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64 \
    2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d "$runtime"
chmod +x "$tool"

KODIKDOWN_BUILD_NAME=kodikdown KODIKDOWN_ONEDIR=1 \
    pyinstaller packaging/kodikdown.spec --noconfirm \
    --workpath "$work/pyinstaller" --distpath "$work/dist"

app_dir="$stage/KodikDown.AppDir"
mkdir -p "$app_dir/usr/bin"
cp -a "$work/dist/kodikdown/." "$app_dir/usr/bin/"
install -m755 packaging/appimage/AppRun "$app_dir/AppRun"
install -m644 packaging/appimage/kodikdown.{desktop,png} "$app_dir/"
install -Dm644 LICENSE "$app_dir/usr/share/licenses/kodikdown/LICENSE"
ln -s kodikdown.png "$app_dir/.DirIcon"

ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$tool" --no-appstream --comp zstd \
    --runtime-file "$runtime" "$app_dir" "$stage/kodikdown-linux-x86_64.AppImage"
mv -- "$stage/kodikdown-linux-x86_64.AppImage" dist/
