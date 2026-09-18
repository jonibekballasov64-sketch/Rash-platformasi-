"""Bot konfiguratsiyasi. Barcha maxfiy/muhit qiymatlari .env fayldan (yoki Railway
muhit o'zgaruvchilaridan) o'qiladi.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    allowed_group_id: int
    admin_ids: str = ""  # "123,456" ko'rinishida, keyin listga aylantiriladi

    database_url: str

    # Esse'ni to'g'ridan-to'g'ri OpenAI orqali tekshirish uchun
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # O'quvchi test ishlaydigan Web App'ning ochiq (https) manzili, masalan
    # https://milliy-sertifikat-bot.up.railway.app
    webapp_base_url: str = ""

    @property
    def admin_id_list(self) -> list[int]:
        return [int(x) for x in self.admin_ids.split(",") if x.strip()]


settings = Settings()  # type: ignore[call-arg]
