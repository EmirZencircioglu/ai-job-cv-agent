# Emir İş Asistanı — İş İlanı & CV Uyarlama Agent'ı

CV'ni (`data/cv.pdf`) Gemini ile analiz eden, LinkedIn, Kariyer.net ve Gmail ilan alarmlarından İstanbul staj ilanlarını toplayıp puanlayan, eşik üstü ilanları Telegram'dan butonlu mesajla bildiren ve **"📝 CV'mi Düzenle"** butonuna bastığında ilana özel ATS uyumlu PDF CV + ön yazı hazırlayan 7/24 agent.

---

## 1. Kendi Bilgisayarında Çalıştırma

```powershell
cd "C:\Users\ezenc\OneDrive\Masaüstü\Dosyalar\agents\Linkedin iş ilanı"
.\.venv\Scripts\python -m app.main
```

CV'ni güncellediğinde profil analizini yenilemek için:
```powershell
.\.venv\Scripts\python -m app.cv_parser
```

---

## 2. Telegram Komutları

| Komut | Açıklama |
|---|---|
| `/ara` | Beklemeden hemen yeni ilan taraması başlatır |
| `/durum` | Son tarama zamanı, incelenen/bildirilen ilan istatistikleri |
| `/profil` | CV analizinin özeti (beceriler, güçlü yönler, eksikler) |
| `/esik 70` | Bildirim için minimum uyum skorunu değiştirir (0–100) |
| `/test` | Örnek bir ilan kartı gönderir (CV düzenleme butonunu denemek için) |
| `/yardim` | Komut listesini gösterir |

---

## 3. Gmail İlan Alarmlarını Bağlama (Önerilen Yedek Kaynak)

LinkedIn ve Kariyer.net zaman zaman sunucu IP'lerini hız sınırına (429/403) sokabilir. Gmail üzerinden ilan alarmı kurduğunda agent mailleri okuyarak hiçbir ilanı kaçırmaz:

1. **LinkedIn** ve **Kariyer.net**'te aradığın kriterlerle ("Finans Stajyer", "Veri Analizi Stajyer" vb., İstanbul) **İş İlanı Alarmı (E-posta)** oluştur.
2. Google hesabında **2 Adımlı Doğrulama** açık olsun.
3. https://myaccount.google.com/apppasswords adresine git, uygulama adı olarak `IsAsistani` yaz ve verilen **16 haneli şifreyi** kopyala.
4. `.env` dosyasına ekle:
   ```env
   GMAIL_ADDRESS=seninadresin@gmail.com
   GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
   ```

---

## 4. VPS Üzerinde 7/24 Kurulum (Docker ile)

Ubuntu kurulu küçük bir VPS (Hetzner CX22, Oracle Cloud Free Tier, DigitalOcean vb.) üzerinde:

```bash
# 1) Docker ve Docker Compose kurulumu
curl -fsSL https://get.docker.com | sh

# 2) Proje klasörünü sunucuya kopyaladıktan sonra (scp / git / SFTP ile):
cd "Linkedin iş ilanı"

# 3) Arka planda 7/24 başlat (sunucu yeniden başlasa bile otomatik açılır)
docker compose up -d --build

# Logları canlı izlemek için:
docker compose logs -f
```
> **Not:** Bot aynı anda yalnızca **tek bir yerde** (ya bilgisayarında ya VPS'te) çalışmalıdır; ikisi birden açık olursa Telegram mesajları çakışır.
