# Hafif ve güvenli bir Python tabanı kullanıyoruz
FROM python:3.11-slim

# Konteyner içindeki çalışma dizinimiz
WORKDIR /app

# Projedeki tüm dosyaları konteynerin içine kopyala
COPY . /app

# Gerekli bağımlılıkları kur (httpx ve dotenv dahil)
RUN pip install --no-cache-dir -e .
RUN pip install --no-cache-dir httpx python-dotenv

# MCP Sunucuları stdio üzerinden haberleştiği için doğrudan scripti çalıştırıyoruz
ENTRYPOINT ["python", "-m", "context_automator.mcp_server"]