#  Context-Automator (MCP Server)

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Protocol](https://img.shields.io/badge/MCP-Protocol-green.svg)](https://modelcontextprotocol.io/)
[![Docker](https://img.shields.io/badge/Docker-Supported-2496ED.svg)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Context-Automator**, modern yazılım geliştirme süreçlerinde geliştiricilerin en büyük sorunlarından biri olan "bağlam değiştirme" (context-switching) maliyetini sıfıra indirmeyi hedefleyen, yapay zeka destekli otonom bir **Model Context Protocol (MCP)** sunucusudur.

Geliştirme ortamınızın tam bir anlık görüntüsünü (snapshot) alır, açık dosyaları ve Git durumunu kaydeder, Claude LLM aracılığıyla projenin o anki durumunu özetler ve dilediğiniz an tek komutla tüm çalışma ortamınızı eksiksiz bir şekilde geri yükler.



---



##  Projenin Amacı ve Çözdüğü Sorun (Neden Var?)

Gün içinde birden fazla proje arasında geçiş yapmak zorunda olan bir mühendissiniz. Her geçişte şu sorunları yaşarsınız:
- "En son hangi dosyalarda çalışıyordum?"
- "IDE'nin pencere yerleşimi nasıldı?"
- "Hangi branch'te kalmıştım ve son commit'im neydi?"

**Context-Automator**, tüm bu süreçleri otomatikleştirir. Projeden çıkarken ortamı dondurur, geri döndüğünüzde ise hem IDE'nizi (VS Code/Cursor) tam bıraktığınız gibi açar hem de Claude aracılığıyla sizi şu şekilde karşılar:
> *"Hoş geldin! Son seansta veritabanı şemasını güncelleyip 2 yeni API endpoint'i eklemiştin. Çalışma dizinin temiz, testlere devam edebilirsin."*


---


##  Temel Özellikler (Features)

-  **Otonom Git Yönetimi (Agentic Git - Faz 6):** Kaydedilmemiş (dirty) değişiklikler tespit edildiğinde, sistem alt süreç kilitlenmelerini tolere ederek otonom kararlar alır (`stash`, `commit_wip`, `discard`).
-  **Yapay Zeka Destekli Seans Özeti (Faz 7 + Faz 8):** `save_context` tetiklendiğinde Git diff ve log verileri toplanır ve özetlenir. İki yol var:
  - **MCP Sampling (öncelikli, Faz 8):** Sunucu kendi API key'ini kullanmaz — "bana bir mesaj üret" isteğini MCP session üzerinden client'a (Claude Desktop) yollar. Maliyet ve model seçimi tamamen client tarafındaki ayarlarda kalır.
  - **BYOK fallback (Faz 7):** Client sampling desteklemiyorsa (veya CLI'den, MCP session olmadan çalıştırılıyorsa) ve `ANTHROPIC_API_KEY` tanımlıysa doğrudan Anthropic API'ye gidilir.
  - *(Kontrol tamamen sizde — arka planda izinsiz tarama yapılmaz, her iki yol da yalnızca `save_context` çağrıldığında tetiklenir.)*
-  **Agnostik IDE Desteği:** Hem VS Code hem de Cursor ekosistemleriyle tam entegre (Native support) çalışır. Dosyaları satır ve sütun konumlarına kadar hatasız yükler.
-  **Docker & İzolasyon (kısmi):** MCP sunucusunun kendisi (tools/resources, git durumu okuma) bağımsız bir Linux konteynerinde çalışabilir. **Önemli sınırlama:** proje Windows'a özel APPDATA/LOCALAPPDATA yollarına ve `.cmd` çalıştırılabilirlerine dayandığı için IDE otomasyonu (VS Code/Cursor açma, workspaceStorage okuma) konteyner içinde çalışmaz -- bu, ayrı bir Windows-native süreç gerektirir. Docker'ı sadece git-durumu/resource kısmını izole çalıştırmak için düşünün, tam özellik seti için değil.
-  **Tam Gizlilik:** Tüm meta veriler (SQLite db) makinenizde lokal kalır, bulut senkronizasyonu yoktur. Sadece açık komut verdiğinizde özet için dışarı veri gider (sampling ile bile bu, sizin MCP client'ınızın kendi çıkış kanalıdır).


---


##  Sistem Mimarisi


Sistem, MCP standartlarına uygun olarak `stdio` (Standart Giriş/Çıkış) üzerinden Claude Desktop veya uyumlu IDE eklentileri ile haberleşir.

```text
┌─────────────────────────────────────────────────────┐
│              Claude Desktop / VS Code               │
│                  (MCP Host)                         │
└──────────────────────┬──────────────────────────────┘
                       │ stdio transport (+ sampling: server→client)
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
│ Layer (Git,  │ │ Layer (IDE, │ │ Layer (Sampling →  │
│ State dump)  │ │ File load)  │ │  BYOK fallback)     │
└──────┬───────┘ └─────┬───────┘ └─────┬──────────────┘
       └───────────────┼───────────────┘
               ┌───────▼───────┐
               │  SQLite DB    │
               │ (contexts.db) │
               └───────────────┘
```


---


##  Kurulum ve Konfigürasyon

Context-Automator'ı iki farklı yöntemle çalıştırabilirsiniz: Yerel ortamda veya Docker konteyneri olarak.

### Seçenek 1: Yerel (Local) Ortam Kurulumu

Geliştirme yapmak veya doğrudan işletim sistemi üzerinden çalıştırmak isterseniz:

1. Depoyu klonlayın:
```bash
git clone https://github.com/batuhanndgnn/context-automator.git
cd context-automator
```

2. Sanal ortamı hazırlayın ve bağımlılıkları yükleyin:
```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1  # Windows
pip install -e ".[dev]"
```
> `httpx` ve `python-dotenv` artık `pyproject.toml`'da tanımlı — ayrıca elle kurmanıza gerek yok.

3. Projenin kök dizininde bir `.env` dosyası oluşturup API anahtarınızı girin (opsiyonel — bkz. "AI Seans Özeti Nasıl Çalışır?"):
```env
ANTHROPIC_API_KEY=sk-ant-api-key-buraya
```
> *Not: API anahtarı sağlanmazsa ve MCP client sampling desteklemiyorsa, araç stabil şekilde çalışmaya devam eder; yalnızca yapay zeka tarafından üretilen özetleme adımı sessizce atlanır.*

4. Sunucuyu başlatın:
```bash
python -m context_automator.mcp_server

```


### Seçenek 2: Docker Üzerinden Çalıştırma


*(Not: Docker sürümü, IDE otomasyonu (VS Code açma) yapmaz; yalnızca MCP sunucusunu ayağa kaldırır. `stdio` transport kullanıldığı için konteyneri mutlaka `-i` ile interaktif başlatmanız gerekir — aksi halde stdin bağlanmaz ve sunucu client ile hiç konuşamaz.)*

1. Docker imajını oluşturun:
```bash
docker build -t context-automator .
```

2. Konteyneri başlatın — **`-i` flag'i zorunlu**:
```bash
docker run --rm -i -e ANTHROPIC_API_KEY="sk-ant-api-key-buraya" context-automator
```

3. Verilerinizin kalıcı olması için yerel dizininizi de bağlayın:
```bash
docker run --rm -i \
  -v ${PWD}/data:/app/data \
  -v ${PWD}/logs:/app/logs \
  -e ANTHROPIC_API_KEY="senin_keyin" \
  context-automator

```

> Claude Desktop `stdio` transport için konteyneri kendi başlatıp stdin/stdout'unu kendisi yönetir (aşağıdaki `claude_desktop_config.json` örneğine bakın); `-i` yalnızca konteyneri elle, terminalden test ederken gereklidir.


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


**Docker Üzerinden Kullanım İçin Konfigürasyon:**
Eğer yerel kurulum yerine Docker imajını Claude Desktop'a bağlamak isterseniz, `claude_desktop_config.json` dosyanızı şu şekilde güncellemelisiniz:

```json
{
  "mcpServers": {
    "context-automator": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "ANTHROPIC_API_KEY=senin_gercek_api_keyin",
        "context-automator"
      ]
    }
  }
}


```

---


##  AI Seans Özeti Nasıl Çalışır? (Sampling vs. BYOK)

`save_context` her çalıştığında bir AI özeti üretmeye çalışır. Bunu iki farklı yoldan yapabilir:

1. **MCP Sampling (varsayılan, tercih edilen yol):** Sunucu `ANTHROPIC_API_KEY` gerektirmez. Bunun yerine MCP session üzerinden client'a (Claude Desktop) "şu prompt için bana bir mesaj üret" isteği gönderir (`session.create_message(...)`). Hangi modelin kullanılacağına ve maliyetin nereden düşeceğine client karar verir — sunucu tarafında hiçbir API key tutulmaz. Client sampling'i desteklemiyorsa bu adım sessizce atlanır ve BYOK'a düşülür.
2. **BYOK (Bring Your Own Key) fallback:** Sampling mevcut değilse (client desteklemiyorsa, ya da CLI'den — MCP session'ı olmadan — çalıştırılıyorsa) ve `.env`'de `ANTHROPIC_API_KEY` tanımlıysa, sunucu doğrudan `https://api.anthropic.com/v1/messages` adresine istek atar. Bu durumda maliyet ve model seçimi sunucu tarafındadır.

Her iki yol da başarısız olursa (ne sampling ne API key varsa) `save_context` yine de normal çalışır; sadece `session_summary` alanı boş kalır.

**CLI'den (`context-automator save ...`) çalıştırdığınızda** MCP session olmadığı için yalnızca BYOK yolu kullanılabilir — sampling sadece MCP host (Claude Desktop vb.) üzerinden çağrıldığında devrededir.


---


##  Kullanım (CLI & MCP Tool)


### Komut Satırı (CLI) Aracılığıyla

Sistem aynı zamanda terminalden de kullanılabilen yerleşik komutlara sahiptir:

```bash
# Şu anki çalışma dizinini snapshot olarak kaydet (AI özetini tetikler — BYOK yoluyla)
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


##  Sorun Giderme (Troubleshooting)


**S: Git işlemleri (Faz 6) sırasında zaman aşımı (`timeout`) hatası alıyorum.**

> C: Sistemin alt süreç kilitlenmesini engellemek için `DEVNULL` yönlendirmesi (Faz 6) aktif edilmiştir. Ancak yerel ortamınızda global `.gitconfig` dosyanızda imzalama (GPG sign) zorunluluğu varsa komut asılı kalabilir. Geçici olarak kapatmayı deneyin.


**S: AI Seans özeti (Faz 7/8) üretilmiyor ve hata vermiyor.**

> C: Kod mimarisi önce Sampling'i, o başarısız olursa "Bring Your Own Key" (Kendi Anahtarını Getir) yolunu dener. MCP client'ınız sampling desteklemiyorsa ve `.env` dosyanızda geçerli bir `ANTHROPIC_API_KEY` yoksa sistem hata fırlatmaz, sessizce o adımı atlar.


**S: Docker imajı build olurken `failed to connect to docker API` hatası alıyorum.**

> C: Docker arka plan motoru (daemon) çalışmıyor demektir. Docker Desktop uygulamasını açıp yeşil "Engine running" ibaresini görene kadar bekleyin.


**S: Docker konteynerini elle çalıştırdığımda hiçbir şey olmuyor / hemen çıkıyor.**

> C: `-i` flag'ini unutmuşsunuzdur. `stdio` transport stdin bekler; `-i` olmadan konteyner stdin'e bağlanamaz. `docker run --rm -i -e ANTHROPIC_API_KEY="..." context-automator` kullanın.


---

##  Testler


Proje pytest ile test ediliyor. Çalıştırmak için:

```bash
pip install -e ".[dev]"
pytest tests/ -v
```


Kapsam raporu için:
```bash
pytest tests/ --cov=context_automator --cov-report=term-missing
```


Her push/PR'da `.github/workflows/tests.yml` üzerinden otomatik olarak da çalışır.

---

##  Lisans

Bu proje MIT Lisansı altında lisanslanmıştır. Detaylar için `LICENSE` dosyasına bakabilirsiniz.
