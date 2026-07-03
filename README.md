# Context-Aware Dev Automator

> Geliştirme ortamını kaydeden, yapay zeka ile özetleyen ve tek komutla geri yükleyen MCP aracı.

VS Code, Cursor ve Claude Desktop ile çalışır. Yerel, bulut yok, veri dışarı çıkmaz.

---

## Neden var?

Gün içinde 3-4 proje arasında geçiş yapıyorsun. Her seferinde:
- Hangi dosyalar açıktı?
- Hangi branch'teydim?
- En son ne yapıyordum?

Context-automator bunu çözüyor — ve Claude AI, dönüşünde seni özetli bir brifingyle karşılıyor.

---

## Mimari

```
┌─────────────────────────────────────────────────────┐
│              Claude Desktop / VS Code               │
│                  (MCP Host)                         │
└──────────────────────┬──────────────────────────────┘
                       │ stdio
┌──────────────────────▼──────────────────────────────┐
│              mcp_server.py (MCP Server)             │
│                                                     │
│  TOOLS              │  RESOURCES                    │
│  ─────────────────  │  ─────────────────────────── │
│  save_context       │  context://current-project-  │
│  switch_context     │    spec (README + dizin)      │
│  list_contexts      │  context://current-git-status │
│  preview_context    │  context://session-history/  │
│  delete_context     │    {proje} (AI özet)          │
│  resolve_git_state  │                               │
└──────┬──────────────┴──────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────┐
│                  Capture Layer                      │
│  git_state.py          session_logger.py            │
│  (branch/dirty/stash)  (git diff → Claude API)      │
│  vscode_family.py                                   │
│  (state.vscdb + history.entries fallback)           │
└──────┬──────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────┐
│                  Restore Layer                      │
│  ide_launcher.py          file_restorer.py          │
│  (VS Code / Cursor açar)  (dosyaları satır:sütun'a) │
└──────┬──────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────┐
│             SQLite (data/contexts.db)               │
│  contexts tablosu    context_events audit log       │
│  session_summary ◄── Faz 7 AI özeti burada yatıyor │
└─────────────────────────────────────────────────────┘
```

---

## Kurulum

```powershell
cd C:\Users\bdogan\Desktop\context_automatorClaude
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### ANTHROPIC_API_KEY (Faz 7 için)

AI seans özeti üretmek için:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
# Kalıcı yapmak için: Windows Ortam Değişkenleri > Sistem Değişkenleri
```

Yoksa araç yine çalışır — sadece AI özet üretilmez.

### Claude Desktop entegrasyonu

`%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "context-automator": {
      "command": "C:\\Users\\bdogan\\Desktop\\context_automatorClaude\\.venv\\Scripts\\python.exe",
      "args": ["-m", "context_automator.mcp_server"],
      "env": {
        "PYTHONPATH": "C:\\Users\\bdogan\\Desktop\\context_automatorClaude\\src",
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

---

## Kullanım

### CLI

```powershell
# Şu anki projeyi kaydet (+ AI otomatik özetler)
context-automator save whatsapp-bot --ide vscode

# Kayıtlı projeleri listele
context-automator list

# Geçiş öncesi ne olacağını gör
context-automator preview whatsapp-bot

# Projeye geç — VS Code açılır, Claude geçmiş özeti gösterir
context-automator switch whatsapp-bot

# Sil
context-automator delete whatsapp-bot
```

### Claude Desktop'tan doğal dil

```
"whatsapp-bot projesini kaydet"
→ save_context çağrılır, AI git diff'i özetler

"context-automator'a geç"  
→ switch_context çağrılır, Claude seni karşılar:
  "Hoş geldin! Son seansta JWT bug düzeltildi, 2 test yazıldı.
   Branch temiz. Devam edelim mi?"

"bu projedeki değişiklikleri stash'e al"
→ resolve_git_state(action='stash') çağrılır
```

### MCP Resources (Faz 5)

Claude Desktop bu kaynakları otomatik okuyabilir:

| Resource URI | İçerik |
|---|---|
| `context://current-project-spec` | Aktif projenin README + dizin yapısı |
| `context://current-git-status` | Anlık git diff + log |
| `context://session-history/{isim}` | Geçmiş seans özeti |

---

## Özellikler

| Özellik | Durum | Not |
|---|---|---|
| Workspace snapshot (git, dosyalar) | ✅ | |
| VS Code / Cursor desteği | ✅ | Her ikisi de |
| MCP Tools (5 araç) | ✅ | |
| MCP Resources (dinamik bağlam) | ✅ | Faz 5 |
| Agentic Git (stash/commit/discard) | ✅ | Faz 6 |
| AI Session Summary | ✅ | Faz 7 — API key gerekli |
| Hoş geldin brifingleri | ✅ | Faz 7 |
| Bulut sync | ❌ | Bilinçli — yerel kalır |
| Terminal geçmişi | ❌ | V2 backlog |

---

## Teknoloji

| Bileşen | Seçim | Neden |
|---|---|---|
| Dil | Python 3.10+ | |
| MCP | `mcp` SDK (stdio) | Standart protokol |
| AI | Claude API (Haiku) | Hızlı, ucuz, Türkçe |
| DB | SQLite | Yerel, kurulum gerektirmez |
| IDE otomasyon | subprocess + CLI | Güvenilir, cross-IDE |

---

## Testler

```powershell
pytest tests/  # 10 test: URI normalizer, memento walker, git parser
```

---

## Lisans

MIT
