#!/usr/bin/env sh
set -eu

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "missing required command: $1" >&2; exit 1; }
}

download_file() {
  src="$1"
  dst="$2"
  case "$src" in
    file://*)
      src_file="${src#file://}"
      cp "$src_file" "$dst"
      ;;
    *)
      curl -fsSL "$src" -o "$dst"
      ;;
  esac
}

need_cmd curl
need_cmd tar
need_cmd openssl
need_cmd python3

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OS="$(uname | tr '[:upper:]' '[:lower:]')"
ARCH_RAW="$(uname -m)"
case "$ARCH_RAW" in
  x86_64) ARCH="amd64" ;;
  arm64|aarch64) ARCH="arm64" ;;
  *) ARCH="$ARCH_RAW" ;;
esac

if [ -n "${DELTAPLAN_MANIFEST_URL:-}" ]; then
  MANIFEST_URL="$DELTAPLAN_MANIFEST_URL"
elif [ -f "$SCRIPT_DIR/manifest.json" ]; then
  MANIFEST_URL="file://$SCRIPT_DIR/manifest.json"
else
  MANIFEST_URL="https://github.com/<org>/<repo>/releases/latest/download/manifest.json"
fi

SIG_URL="$(printf '%s' "$MANIFEST_URL" | sed 's/manifest.json$/manifest.sig/')"

tmpdir="$(mktemp -d)"
cleanup() { rm -rf "$tmpdir"; }
trap cleanup EXIT

download_file "$MANIFEST_URL" "$tmpdir/manifest.json"
download_file "$SIG_URL" "$tmpdir/manifest.sig"

if [ -f "$SCRIPT_DIR/release_public_key.pem" ]; then
  cp "$SCRIPT_DIR/release_public_key.pem" "$tmpdir/release_public_key.pem"
elif [ -f "$HOME/.deltaplan/release_public_key.pem" ]; then
  cp "$HOME/.deltaplan/release_public_key.pem" "$tmpdir/release_public_key.pem"
else
cat > "$tmpdir/release_public_key.pem" <<'PEM'
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA7YqRUAGV5hKWKzoZCOCX
7rqVYiejKiy7ZLXO1rPo8I0JJfRUUDMZ5UneMVsMtzp8lK3QSpScvkBJPxpRUnDM
pLE8cZpgkyVe6pzZ5mVcFderCalyIx6nZ8EO8C5Y/d7JwA1Ej7vWp/RELZmqPOaq
J4W23IC84IJN9qagILMPSLZWxQidxi34S3gj/rys+5VYl1Tt5xL7M52NyFys70Wm
I4YRgvzbtiZSqNoExKj2RFtClPpyrIGJN5brxHmG4g5Tj9dfXgauTF0ReXx7qOwL
xl8g+3vAjt6hsLx8h27dFxdak6fE3JObp2zx3nd4xeBDESlaQiGAZe15W10t0pHS
TwIDAQAB
-----END PUBLIC KEY-----
PEM
fi

if ! openssl dgst -sha256 -verify "$tmpdir/release_public_key.pem" -signature "$tmpdir/manifest.sig" "$tmpdir/manifest.json" >/dev/null; then
  echo "manifest signature verification failed" >&2
  exit 1
fi

ASSET_INFO="$(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print(next((f"{i.get("name")}|{i.get("url")}|{i.get("sha256")}" for i in m.get("assets",[]) if i.get("kind")=="cli" and i.get("os")==sys.argv[2] and i.get("arch")==sys.argv[3]), ""))' "$tmpdir/manifest.json" "$OS" "$ARCH")"
ASSET_NAME="$(printf '%s' "$ASSET_INFO" | cut -d '|' -f 1)"
ASSET_URL="$(printf '%s' "$ASSET_INFO" | cut -d '|' -f 2)"
ASSET_SHA="$(printf '%s' "$ASSET_INFO" | cut -d '|' -f 3)"

if [ -z "$ASSET_NAME" ] || [ -z "$ASSET_URL" ]; then
  echo "no matching cli asset for ${OS}/${ARCH}" >&2
  exit 1
fi

download_file "$ASSET_URL" "$tmpdir/$ASSET_NAME"

ACTUAL_SHA="$(python3 -c 'import hashlib,sys; print(hashlib.file_digest(open(sys.argv[1],"rb"),"sha256").hexdigest())' "$tmpdir/$ASSET_NAME")"
if [ "$ACTUAL_SHA" != "$ASSET_SHA" ]; then
  echo "cli sha256 mismatch" >&2
  exit 1
fi

VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$tmpdir/manifest.json")"
INSTALL_ROOT="$HOME/.deltaplan/cli/$VERSION"
mkdir -p "$HOME/.deltaplan/cli"
rm -rf "$INSTALL_ROOT"
mkdir -p "$INSTALL_ROOT"

tar -xzf "$tmpdir/$ASSET_NAME" -C "$INSTALL_ROOT"
mkdir -p "$HOME/.deltaplan"
cp "$tmpdir/release_public_key.pem" "$HOME/.deltaplan/release_public_key.pem"
ln -sfn "$INSTALL_ROOT" "$HOME/.deltaplan/cli/current"

if [ -w /usr/local/bin ]; then
  LAUNCHER_PATH="/usr/local/bin/deltaplan"
else
  mkdir -p "$HOME/.local/bin"
  LAUNCHER_PATH="$HOME/.local/bin/deltaplan"
  echo "Launcher installed at $LAUNCHER_PATH (not on PATH unless configured)"
fi

cat > "$LAUNCHER_PATH" <<EOF
#!/usr/bin/env sh
"$HOME/.deltaplan/cli/current/launcher.py" "\$@"
EOF
chmod +x "$LAUNCHER_PATH"

echo "DeltaPlan CLI installed. Try: $LAUNCHER_PATH --help"
