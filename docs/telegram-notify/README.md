# Etornie → Telegram Bildirim Botu

Etornie reposundaki **push, commit, PR açma/kapama/merge** olaylarını eş zamanlı olarak
Telegram'a bildirir. Ekstra sunucu/hosting **gerekmez** — her şey GitHub Actions ile
GitHub'ın kendi içinde çalışır.

## Mimari

```
Etornie repo  ──(push / pull_request)──►  GitHub Actions
                                              │
                                              ▼
                                   Telegram Bot API (sendMessage)
                                              │
                                              ▼
                                     @EtornieDevBot → senin chat'in
```

## Kurulum (5 adım)

### 1. Workflow dosyası
Workflow dosyası bu reponun [.github/workflows/telegram-notify.yml](../../.github/workflows/telegram-notify.yml)
yolunda hazır duruyor. Başka bir repoya taşımak istersen onu hedef reponun
`.github/workflows/` klasörüne kopyalayıp commit'le.

> Not: Workflow, kurulu olduğu reponun olaylarını dinler. Bu yüzden dosya her zaman
> `.github/workflows/` altında olmalı.

### 2. chat_id'yi bul
Bildirimlerin nereye gideceğini Telegram'a söylemen lazım:

- Bota özelden bir mesaj yaz, **ya da** botu bir gruba/kanala ekle ve oraya mesaj at.
- Sonra (repo kökünden):
  ```bash
  export TELEGRAM_TOKEN="..."   # @EtornieDevBot token'ı
  bash docs/telegram-notify/get-chat-id.sh
  ```
- Çıktıdaki `"chat":{"id": ...}` değerini al. Grup/kanal id'leri `-100...` ile başlar.

### 3. GitHub Secrets ekle
Etornie reposunda: **Settings → Secrets and variables → Actions → New repository secret**

| Secret adı          | Değer                                                  |
|---------------------|--------------------------------------------------------|
| `TELEGRAM_TOKEN`    | `8851765824:AAH_zvNU5z2Jp0nPFw6BODMCPnMZKPJEuRU`       |
| `TELEGRAM_CHAT_ID`  | 2. adımda bulduğun id (örn. `-1001234567890`)          |

> Token'ı koda gömme; secret olarak tut. (Sen restore ediyorsun, biliyorum 🙂 ama
> workflow zaten secret'tan okuyor.)

### 4. Test et
Etornie reposuna küçük bir commit at ve push'la. Birkaç saniye içinde Telegram'a
bildirim düşmeli. Düşmezse Etornie reposunda **Actions** sekmesinden çalışan job'ın
log'una bak.

## Hangi olaylar bildiriliyor?

| Olay                       | Tetikleyici              | İçerik                                            |
|----------------------------|--------------------------|--------------------------------------------------|
| Push (commit'ler)          | `push` (tüm branch'ler)  | Kim attı, branch, her commit (sha + mesaj + yazar), karşılaştırma linki |
| PR açıldı / yeniden açıldı  | `pull_request` opened    | Kişi, başlık, kaynak→hedef branch, +/− satır, link |
| PR merge edildi            | `pull_request` closed+merged | Kim merge etti + tüm PR detayları           |
| PR kapatıldı (merge yok)   | `pull_request` closed    | Kapatma bildirimi                                |

## Özelleştirme

- **Sadece belirli branch'ler:** `telegram-notify.yml` içindeki `push: branches:` kısmını düzenle.
- **Mesaj formatı:** `script:` bloğundaki `text = ...` satırlarını değiştir. `parse_mode: HTML`.
- **Daha fazla olay (issue, release, yorum):** `on:` kısmına event ekle, script'te bir `if` bloğu ekle.

## Sınırlamalar (GitHub Actions yöntemi)

- Fork'lardan açılan PR'lar secret'lara erişemez (güvenlik); o yüzden onlar bildirilmez.
  (Bunu da istiyorsan webhook sunucusu yöntemine geçmek gerekir.)
- Çok nadir durumlarda Actions kuyruğu birkaç saniye gecikme yaratabilir.
