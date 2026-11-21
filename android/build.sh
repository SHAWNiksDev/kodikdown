#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Respect the developer's environment; local tooling is an optional fallback.
if [[ -z "${JAVA_HOME:-}" && -d "$DIR/.tooling/jdk-21" ]]; then
    export JAVA_HOME="$DIR/.tooling/jdk-21"
fi
if [[ -z "${ANDROID_HOME:-}" && -z "${ANDROID_SDK_ROOT:-}" && -d "$DIR/.tooling/sdk" ]]; then
    export ANDROID_HOME="$DIR/.tooling/sdk"
fi
if [[ -n "${JAVA_HOME:-}" ]]; then
    export PATH="$JAVA_HOME/bin:$PATH"
fi

variant="debug"
if [[ "${1:-}" == "--release" ]]; then
    variant="release"
    shift
fi
if [[ "$variant" == "release" ]]; then
    repo="$DIR/.."
    brand_dir=src/kodikdown/gui/brands
    source_trees() {
        git -C "$repo" rev-parse HEAD:android "HEAD:$brand_dir" | paste -sd ' ' -
    }
    expected_trees="$(source_trees)"
    check_release_source() {
        local current changes
        current="$(source_trees)"
        changes="$(git -C "$repo" status --porcelain --untracked-files=all -- android "$brand_dir")"
        if [[ "$current" != "$expected_trees" || -n "$changes" ]]; then
            printf '%s\n' 'Build the signed APK from clean, unchanged Android and brand source trees.' >&2
            exit 1
        fi
    }
    check_release_source
    "$DIR/gradlew" -p "$DIR" testReleaseUnitTest lintRelease assembleRelease "$@" \
        "-PkodikdownSourceTrees=$expected_trees"
    check_release_source
else
    "$DIR/gradlew" -p "$DIR" testDebugUnitTest lintDebug assembleDebug "$@"
fi
mkdir -p "$DIR/../packaging"
output="$DIR/../packaging/kodikdown-android.apk"
if [[ "$variant" == "debug" ]]; then output="$DIR/../packaging/kodikdown-android-debug.apk"; fi
cp "$DIR/app/build/outputs/apk/$variant/app-$variant.apk" "$output"
printf 'APK: %s\n' "$output"
