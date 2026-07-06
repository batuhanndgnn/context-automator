# Hafif ve güvenli bir Python tabanı kullanıyoruz
FROM python:3.11-slim

# Konteyner içindeki çalışma dizinimiz
WORKDIR /app

# Projedeki tüm dosyaları konteynerin içine kopyala
COPY . /app

# Gerekli bağımlılıkları kur — httpx ve python-dotenv artık pyproject.toml'da
# gerçek dependency olarak tanımlı, ayrıca elle kurmaya gerek yok.
RUN pip install --no-cache-dir -e .

# MCP Sunucuları stdio üzerinden haberleştiği için doğrudan scripti çalıştırıyoruz.
# ÖNEMLİ: bu konteyneri elle test ederken `docker run -i ...` kullanın —
# `-i` olmadan stdin bağlanmaz ve sunucu client ile hiç konuşamaz (bkz. README).
ENTRYPOINT ["python", "-m", "context_automator.mcp_server"]