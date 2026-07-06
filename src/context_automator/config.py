"""Merkezi konfigürasyon -- pydantic-settings ile tip-güvenli ayar yönetimi.

ÖNCEDEN: ayarlar (ANTHROPIC_API_KEY, IDE CLI override'ları, log seviyesi)
proje genelinde farklı dosyalarda (session_logger.py, ide_paths.py, util.py)
birbirinden bağımsız `os.environ.get(...)` çağrılarıyla okunuyordu. Bunun
somut sakıncaları vardı:
  - Hangi env var'ların desteklendiğini görmek için tüm kod tabanını
    grep'lemek gerekiyordu.
  - Bir env var adı yanlış yazılırsa (typo) sessizce None dönüyordu,
    hiçbir uyarı/hata yoktu.
  - Tip dönüşümü (ör. path, bool) her çağıran yerde elle yapılıyordu.

ARTIK: tüm ayarlar burada, tek yerde, tip bilgisiyle tanımlı. `.env`
dosyasından ve gerçek ortam değişkenlerinden otomatik okunur (ortam
değişkeni her zaman .env'deki değeri ezer).

NOT: Bu bir "production/dev/test ortamı" değiştirme mekanizması DEĞİL --
proje tek-kullanıcılı, tek-makineli bir kişisel araç, öyle bir karmaşıklığa
ihtiyacı yok. Bu sadece "dağınık os.environ çağrılarını tek yere topla"
iyileştirmesi.
"""
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env dosyasında bilinmeyen key'ler olursa patlamasın
    )

    # --- AI özet fallback'i (BYOK) için --------------------------------
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")

    # --- IDE CLI override'ları (ide_paths.py'nin PATH/bilinen-yol
    #     aramasından önce kontrol ettiği manuel yollar) -----------------
    cursor_cli_override: Optional[str] = Field(
        default=None, alias="CONTEXT_AUTOMATOR_CURSOR_CLI"
    )
    vscode_cli_override: Optional[str] = Field(
        default=None, alias="CONTEXT_AUTOMATOR_VSCODE_CLI"
    )

    # --- DB yolu override --------------------------------------------
    # Boş bırakılırsa db/schema.py'deki default_db_path() eski (proje kökü
    # + data/contexts.db) davranışına düşer -- bu, mevcut kurulumları bozmaz.
    db_path_override: Optional[Path] = Field(
        default=None, alias="CONTEXT_AUTOMATOR_DB_PATH"
    )

    # --- Log seviyesi ---------------------------------------------------
    log_level: str = Field(default="DEBUG", alias="CONTEXT_AUTOMATOR_LOG_LEVEL")

    def cli_override_for(self, ide_type: str) -> Optional[str]:
        """ide_paths.py'nin kullanacağı, ide_type'a göre override döndüren
        yardımcı -- iki ayrı alanı elle if/else ile sormak yerine."""
        return {
            "cursor": self.cursor_cli_override,
            "vscode": self.vscode_cli_override,
        }.get(ide_type)


# Modül import edildiğinde bir kez oluşturulur, tüm proje bunu paylaşır.
settings = Settings()
