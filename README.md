# 🧠 Context-Automator (MCP Server)

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Protocol](https://img.shields.io/badge/MCP-Protocol-green.svg)](https://modelcontextprotocol.io/)
[![Docker](https://img.shields.io/badge/Docker-Supported-2496ED.svg)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Context-Automator**, modern yazılım geliştirme süreçlerinde geliştiricilerin en büyük sorunlarından biri olan "bağlam değiştirme" (context-switching) maliyetini sıfıra indirmeyi hedefleyen, yapay zeka destekli otonom bir **Model Context Protocol (MCP)** sunucusudur.

Geliştirme ortamınızın tam bir anlık görüntüsünü (snapshot) alır, açık dosyaları ve Git durumunu kaydeder, Claude LLM aracılığıyla projenin o anki durumunu özetler ve dilediğiniz an tek komutla tüm çalışma ortamınızı eksiksiz bir şekilde geri yükler.

---

## 🎯 Projenin Amacı ve Çözdüğü Sorun (Neden Var?)

Gün içinde birden fazla proje arasında geçiş yapmak zorunda olan bir mühendissiniz. Her geçişte şu sorunları yaşarsınız:
- "En son hangi dosyalarda çalışıyordum?"
- "IDE'nin pencere yerleşimi nasıldı?"
- "Hangi branch'te kalmıştım ve son commit'im neydi?"

**Context-Automator**, tüm bu süreçleri otomatikleştirir. Projeden çıkarken ortamı dondurur, geri döndüğünüzde ise hem IDE'nizi (VS Code/Cursor) tam bıraktığınız gibi açar hem de Claude aracılığıyla sizi şu şekilde karşılar:
> *"Hoş geldin! Son seansta veritabanı şemasını güncelleyip 2 yeni API endpoint'i eklemiştin. Çalışma dizinin temiz, testlere devam edebilirsin."*

---

## 🚀 Temel Özellikler (Features)

- 🔄 **Otonom Git Yönetimi (Agentic Git - Faz 6):** Kaydedilmemiş (dirty) değişiklikler tespit edildiğinde, sistem alt süreç kilitlenmelerini tolere ederek otonom kararlar alır (`stash`, `commit_wip`, `discard`).
- 🤖 **Yapay Zeka Destekli Seans Özeti (Faz 7):** `save_context` tetiklendiğinde Git diff ve log verileri toplanarak **Claude 3 Haiku** modeline gönderilir. Ortaya çıkan teknik özet SQLite veritabanında saklanır. *(Kontrol tamamen sizdedir, arka planda izinsiz tarama yapmaz).*
- 🔌 **Agnostik IDE Desteği:** Hem VS Code hem de Cursor ekosistemleriyle tam entegre (Native support) çalışır. Dosyaları satır ve sütun konumlarına kadar hatasız yükler.
- 📦 **Docker & İzolasyon:** Herhangi bir yerel bağımlılığa ihtiyaç duymadan, sistemin tamamen izole bir konteyner içerisinde çalışabilmesini sağlayan Docker desteği.
- 🔒 **Tam Gizlilik:** Tüm meta veriler (SQLite db) makinenizde lokal kalır, bulut senkronizasyonu yoktur. Sadece açık komut verdiğinizde özet için API'ye veri gider.

---

## 🏗️ Sistem Mimarisi

Sistem, MCP standartlarına uygun olarak `stdio` (Standart Giriş/Çıkış) üzerinden Claude Desktop veya uyumlu IDE eklentileri ile haberleşir.

```text
┌─────────────────────────────────────────────────────┐
│              Claude Desktop / VS Code               │
│                  (MCP Host)                         │
└──────────────────────┬──────────────────────────────┘
                       │ stdio transport
┌──────────────────────▼──────────────────────────────┐
│              mcp_server.py (MCP Server)             │
│                                                     │
│  [TOOLS]                            [RESOURCES]     │
│  - save_context             - current-project-spec  │
│  - switch_context           - current-git-status    │
│  - resolve_git_state        - session-history/{ctx} │
└──────┬───────────────┬───────────────┬──────────────┘
       │               │               │
┌──────▼───────┐ ┌─────▼───────┐ ┌─────▼──────────────┐
│   Capture    │ │   Restore   │ │    AI Logger       │
│ Layer (Git,  │ │ Layer (IDE, │ │ Layer (Claude API) │
│ State dump)  │ │ File load)  │ │                    │
└──────┬───────┘ └─────┬───────┘ └─────┬──────────────┘
       └───────────────┼───────────────┘
               ┌───────▼───────┐
               │  SQLite DB    │
               │ (contexts.db) │
               └───────────────┘

```

---

## ⚙️ Kurulum ve Konfigürasyon

Context-Automator'ı iki farklı yöntemle çalıştırabilirsiniz: Yerel ortamda veya Docker konteyneri olarak.

### Seçenek 1: Docker Üzerinden Çalıştırma 
*(Not: Docker sürümü, IDE otomasyonu (VS Code açma) yapmaz; yalnızca MCP sunucusunu arka planda ayağa kaldırır.)*


1. Depoyu klonlayın ve dizine gidin:
```bash
git clone [https://github.com/KULLANICI_ADINIZ/context-automator.git](https://github.com/KULLANICI_ADINIZ/context-automator.git)
cd context-automator

```


2. Docker imajını oluşturun:
```bash
docker build -t context-automator .

```


3. Konteyneri başlatın (API Key'inizi çevresel değişken olarak ekleyerek):
```bash
docker run --rm -e ANTHROPIC_API_KEY="sk-ant-api-key-buraya" context-automator

```

### Docker ile Çalıştırma
Verilerinizin kalıcı olması için yerel dizininizi konteynere bağlayın:

```bash
docker run -d \
  -v ${PWD}/data:/app/data \
  -v ${PWD}/logs:/app/logs \
  -e ANTHROPIC_API_KEY="senin_keyin" \
  context-automator

### Seçenek 2: Yerel (Local) Ortam Kurulumu

Geliştirme yapmak veya doğrudan işletim sistemi üzerinden çalıştırmak isterseniz:

1. Sanal ortamı hazırlayın ve bağımlılıkları yükleyin:
```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1  # Windows
pip install -e ".[dev]"
pip install httpx python-dotenv

```


2. Projenin kök dizininde bir `.env` dosyası oluşturup API anahtarınızı girin:
```env
ANTHROPIC_API_KEY=sk-ant-api-key-buraya

```


> *Not: API anahtarı sağlanmazsa, araç stabil şekilde çalışmaya devam eder; yalnızca yapay zeka tarafından üretilen özetleme adımı sessizce atlanır.*


3. Sunucuyu başlatın:
```bash
python -m context_automator.mcp_server

```



### Claude Desktop Entegrasyonu

Claude uygulamasının bu MCP sunucusunu tanıyabilmesi için konfigürasyon dosyanızı (Windows: `%APPDATA%\Claude\claude_desktop_config.json`) güncelleyin:

```json
{
  "mcpServers": {
    "context-automator": {
      "command": "C:\\Projeye\\Giden\\Tam\\Yol\\.venv\\Scripts\\python.exe",
      "args": ["-m", "context_automator.mcp_server"],
      "env": {
        "PYTHONPATH": "C:\\Projeye\\Giden\\Tam\\Yol\\src"
      }
    }
  }
}

```

---

## 💻 Kullanım (CLI & MCP Tool)

### Komut Satırı (CLI) Aracılığıyla

Sistem aynı zamanda terminalden de kullanılabilen yerleşik komutlara sahiptir:

```bash
# Şu anki çalışma dizinini snapshot olarak kaydet (AI özetini tetikler)
context-automator save whatsapp-bot --ide vscode

# Kayıtlı projeleri ve son güncelleme tarihlerini gör
context-automator list

# Projeye geri dön (VS Code açılır, dosyalar geri yüklenir)
context-automator switch whatsapp-bot

```

### Doğal Dil ile (Claude Desktop Üzerinden)

Claude Desktop'a sadece ne istediğinizi söylemeniz yeterlidir:

* *"Şu an üzerinde çalıştığım projeyi kaydet."*
* *"whatsapp-bot projesine geçiş yap."*
* *"Bu projede uncommitted değişiklikler var, onları stash'e alarak ortamı temizle."*

---

## 🛠️ Sorun Giderme (Troubleshooting)

**S: Git işlemleri (Faz 6) sırasında zaman aşımı (`timeout`) hatası alıyorum.**

> C: Sistemin alt süreç kilitlenmesini engellemek için `DEVNULL` yönlendirmesi (Faz 6) aktif edilmiştir. Ancak yerel ortamınızda global `.gitconfig` dosyanızda imzalama (GPG sign) zorunluluğu varsa komut asılı kalabilir. Geçici olarak kapatmayı deneyin.

**S: AI Seans özeti (Faz 7) üretilmiyor ve hata vermiyor.**

> C: Kod mimarisi "Bring Your Own Key" (Kendi Anahtarını Getir) mantığıyla yazılmıştır. `.env` dosyanızı kontrol edin. Geçerli bir `ANTHROPIC_API_KEY` yoksa sistem hata fırlatmaz, sessizce o adımı atlar (`return None`).

**S: Docker imajı build olurken `failed to connect to docker API` hatası alıyorum.**

> C: Docker arka plan motoru (daemon) çalışmıyor demektir. Docker Desktop uygulamasını açıp yeşil "Engine running" ibaresini görene kadar bekleyin.

---

## 📄 Lisans

Bu proje [MIT Lisansı](https://www.google.com/search?q=LICENSE) altında lisanslanmıştır. Detaylar için `LICENSE` dosyasına bakabilirsiniz.

```

```