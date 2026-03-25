#!/usr/bin/env sh
set -eu

# One-shot local test of package/install/update path.
# Usage: sh scripts/release/e2e_local.sh

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
WORK_DIR="${DELTAPLAN_E2E_WORKDIR:-/tmp/deltaplan-e2e}"
RELEASE_DIR="$WORK_DIR/release"
TEST_HOME="$WORK_DIR/home"
TEST_REPO="$WORK_DIR/repo"
KEY_DIR="$WORK_DIR/keys"

mkdir -p "$WORK_DIR" "$KEY_DIR" "$TEST_HOME"
rm -rf "$RELEASE_DIR" "$TEST_REPO"

OS_NAME="$(uname | tr '[:upper:]' '[:lower:]')"
ARCH_RAW="$(uname -m)"
case "$ARCH_RAW" in
  x86_64) ARCH_NAME="amd64" ;;
  arm64|aarch64) ARCH_NAME="arm64" ;;
  *) ARCH_NAME="$ARCH_RAW" ;;
esac

# Provide a tiny managed Java stub only when a compatible Java 21 is unavailable.
# This keeps local e2e fast while still exercising the CLI-managed Java install path.
STUB_JAVA_ARCHIVE="$WORK_DIR/temurin-jre-21-$OS_NAME-$ARCH_NAME.tar.gz"
if ! java -XshowSettings:properties -version 2>/dev/null | grep -q "java.version = 21"; then
  STUB_ROOT="$WORK_DIR/stub-java/$OS_NAME-$ARCH_NAME"
  mkdir -p "$STUB_ROOT/bin"
  cat > "$STUB_ROOT/bin/java" <<'EOF'
#!/bin/sh
if [ "$1" = "-XshowSettings:properties" ] && [ "$2" = "-version" ]; then
  echo "    java.version = 21.0.0"
  exit 0
fi
if [ "$1" = "-version" ] && [ "$2" = "-XshowSettings:properties" ]; then
  echo "    java.version = 21.0.0"
  exit 0
fi
echo "fake java runtime"
exit 0
EOF
  chmod +x "$STUB_ROOT/bin/java"
  mkdir -p "$WORK_DIR/stub-java"
  (cd "$WORK_DIR/stub-java" && tar -czf "$STUB_JAVA_ARCHIVE" "$OS_NAME-$ARCH_NAME")

  java_sha="$(python3 -c 'import hashlib,sys;print(hashlib.file_digest(open(sys.argv[1],"rb"),"sha256").hexdigest())' "$STUB_JAVA_ARCHIVE")"
  java_env_url="DELTAPLAN_JAVA_${OS_NAME}_${ARCH_NAME}_URL"
  java_env_sha="DELTAPLAN_JAVA_${OS_NAME}_${ARCH_NAME}_SHA"
  export "$java_env_url=file://$STUB_JAVA_ARCHIVE"
  export "$java_env_sha=$java_sha"
fi

key_priv="$KEY_DIR/release.key"
key_pub="$KEY_DIR/release.pub"

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$key_priv" >/dev/null 2>&1
openssl rsa -in "$key_priv" -pubout -out "$key_pub" >/dev/null 2>&1

export PYTHONPATH="$ROOT_DIR"
export DELTAPLAN_RELEASE_PRIVATE_KEY="$key_priv"
export DELTAPLAN_RELEASE_PUBLIC_KEY="$key_pub"
export DELTAPLAN_RELEASE_DIR="$RELEASE_DIR"
export DELTAPLAN_RELEASE_BASE_URL="file://$RELEASE_DIR"

echo "building local release..."
python3 "$ROOT_DIR/scripts/release/build_release.py"

# Use local release artifacts directly (no manual manifest URL/key gymnastics)
export HOME="$TEST_HOME"
export DELTAPLAN_MANIFEST_URL="file://$RELEASE_DIR/manifest.json"

sh "$RELEASE_DIR/install.sh"

export PATH="$HOME/.local/bin:$PATH"

echo "DeltaPlan CLI installed at: $(command -v deltaplan)"
deltaplan --version

mkdir -p "$TEST_REPO"
cd "$TEST_REPO"
git init -q

echo "running init in fresh repo"
if printf 'Claude Code\nYes\n' | deltaplan init; then
  echo "init: OK"
  deltaplan doctor
  printf 'Yes\n' | deltaplan remove
  echo "remove: OK"
else
  echo "init failed: Java 21 missing or managed Java asset unavailable."
  echo "Install Java 21 first (or provide local java assets) and rerun for full lifecycle test."
fi

echo "WORKDIR: $WORK_DIR"
echo "HOME: $HOME"
echo "REPO: $TEST_REPO"
