#!/bin/bash
# Monta o Will Painel para Mac: app universal (Apple Silicon e Intel), ícone e o .dmg com o atalho para Aplicativos.
# Roda num Mac (GitHub macos-latest). Uso: apps/mac-painel/montar.sh VERSAO PASTA_SAIDA
set -euo pipefail
VERSAO="${1:-1.0.0}"
SAIDA="${2:-dist-mac}"
AQUI="$(cd "$(dirname "$0")" && pwd)"
RAIZ="$(cd "$AQUI/../.." && pwd)"
TRAB="$(mktemp -d)"
APP="$TRAB/Will Painel.app"

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$SAIDA"

# Binário universal: compila para cada arquitetura e junta.
for arq in arm64 x86_64; do
  swiftc -O -target "$arq-apple-macos11.0" -framework Cocoa -framework WebKit \
    "$AQUI/main.swift" -o "$TRAB/WillPainel-$arq"
done
lipo -create "$TRAB/WillPainel-arm64" "$TRAB/WillPainel-x86_64" -output "$APP/Contents/MacOS/WillPainel"

sed "s/__VERSAO__/$VERSAO/g" "$AQUI/Info.plist" > "$APP/Contents/Info.plist"
plutil -lint "$APP/Contents/Info.plist"

# Ícone a partir do ícone do painel (o mesmo do celular).
ICONES="$TRAB/WillPainel.iconset"
mkdir -p "$ICONES"
ORIGEM="$RAIZ/backend/painel_web/icones/icone-512.png"
for t in 16 32 128 256 512; do
  sips -z "$t" "$t" "$ORIGEM" --out "$ICONES/icon_${t}x${t}.png" > /dev/null
  d=$((t * 2))
  sips -z "$d" "$d" "$ORIGEM" --out "$ICONES/icon_${t}x${t}@2x.png" > /dev/null
done
iconutil -c icns "$ICONES" -o "$APP/Contents/Resources/WillPainel.icns"

# Assinatura local (ad hoc): sem ela o Mac com chip Apple nem abre o app. Não substitui a assinatura da Apple.
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

# .dmg: o app e um atalho para a pasta Aplicativos (arrastar para instalar).
PACOTE="$TRAB/pacote"
mkdir -p "$PACOTE"
cp -R "$APP" "$PACOTE/"
ln -s /Applications "$PACOTE/Aplicativos"
hdiutil create -volname "Will Painel" -srcfolder "$PACOTE" -ov -format UDZO "$SAIDA/WillPainel-$VERSAO.dmg"
cp -R "$APP" "$SAIDA/"
echo "Pronto: $SAIDA/WillPainel-$VERSAO.dmg"
