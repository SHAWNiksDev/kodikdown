#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export JAVA_HOME="$DIR/.tooling/jdk-21"
export ANDROID_HOME="$DIR/.tooling/sdk"
export PATH="$JAVA_HOME/bin:$PATH"

echo "=== Building KodikDown Android APK ==="
echo "JAVA_HOME=$JAVA_HOME"
echo "ANDROID_HOME=$ANDROID_HOME"

cd "$DIR"
./gradlew assembleDebug --stacktrace
echo "=== Build Complete ==="
ls -lh app/build/outputs/apk/debug/
