"""Bota Start'a basan kullanıcının chat ID'sini bulup .env dosyasına yazar.

Kullanım:
    python -m app.setup_telegram
"""
from __future__ import annotations

import re

import httpx

from app.config import ROOT, env


def main() -> None:
    token = env("TELEGRAM_BOT_TOKEN")
    base = f"https://api.telegram.org/bot{token}"

    me = httpx.get(f"{base}/getMe", timeout=15).json()
    if not me.get("ok"):
        print("❌ Token geçersiz görünüyor. .env içindeki TELEGRAM_BOT_TOKEN değerini kontrol et.")
        return
    print(f"🤖 Bot: {me['result']['first_name']} (@{me['result']['username']})")

    updates = httpx.get(f"{base}/getUpdates", timeout=15).json()["result"]
    chats = {
        u["message"]["chat"]["id"]: u["message"]["chat"].get("first_name", "")
        for u in updates
        if "message" in u
    }
    if not chats:
        print("❌ Mesaj bulunamadı. Telegram'da botu açıp START'a bas (veya 'merhaba' yaz), sonra tekrar çalıştır.")
        return

    chat_id, name = list(chats.items())[-1]
    env_file = ROOT / ".env"
    text = env_file.read_text(encoding="utf-8")
    if re.search(r"^TELEGRAM_CHAT_ID=.*$", text, flags=re.M):
        text = re.sub(r"^TELEGRAM_CHAT_ID=.*$", f"TELEGRAM_CHAT_ID={chat_id}", text, flags=re.M)
    else:
        text += f"\nTELEGRAM_CHAT_ID={chat_id}\n"
    env_file.write_text(text, encoding="utf-8")
    print(f"✅ Chat ID bulundu ({name}) ve .env dosyasına yazıldı.")


if __name__ == "__main__":
    main()
