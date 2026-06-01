#!/usr/bin/env bash
# Telegram chat_id'yi bulmak için.
#
# Kullanım:
#   1) Botu (@EtornieDevBot) bildirim göndermesini istediğin yere ekle:
#        - Özelden almak istiyorsan: bota Telegram'dan "/start" veya herhangi bir mesaj yaz.
#        - Gruba: botu gruba ekle, gruba herhangi bir mesaj yaz.
#        - Kanala: botu kanala admin yap, kanala bir gönderi at.
#   2) Bot token'ını ortam değişkeni olarak ver ve scripti çalıştır:
#        export TELEGRAM_TOKEN="..."
#        bash docs/telegram-notify/get-chat-id.sh
#   3) Çıktıda "chat":{"id": ...} değerini al. Grup/kanal id'leri -100... ile başlar.

TOKEN="${TELEGRAM_TOKEN:-}"

if [ -z "$TOKEN" ]; then
  echo "Hata: TELEGRAM_TOKEN ortam değişkeni tanımlı değil." >&2
  echo "Önce:  export TELEGRAM_TOKEN=\"<bot-token>\"" >&2
  exit 1
fi

echo "getUpdates çağrılıyor..."
curl -s "https://api.telegram.org/bot${TOKEN}/getUpdates" \
  | python3 -m json.tool 2>/dev/null \
  || curl -s "https://api.telegram.org/bot${TOKEN}/getUpdates"

echo ""
echo "Yukarıdaki çıktıda  \"chat\":{\"id\": <BURASI> ...}  değeri senin TELEGRAM_CHAT_ID'in."
