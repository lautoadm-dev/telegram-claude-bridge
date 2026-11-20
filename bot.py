import json
import sys
import time
import urllib.error
from datetime import datetime

from telegram_api import (
    INBOX_DIR,
    MESSAGES_JSONL,
    api_request,
    download_telegram_file,
    get_config,
    load_state,
    render_pending_md,
    save_state,
    send_message,
)


def extract_attachments(token: str, msg: dict) -> list[str]:
    saved_paths: list[str] = []

    if "document" in msg:
        doc = msg["document"]
        path = download_telegram_file(token, doc["file_id"], doc.get("file_name", "document"))
        saved_paths.append(str(path))

    if "photo" in msg and msg["photo"]:
        largest = msg["photo"][-1]
        path = download_telegram_file(token, largest["file_id"], "photo.jpg")
        saved_paths.append(str(path))

    if "voice" in msg:
        voice = msg["voice"]
        path = download_telegram_file(token, voice["file_id"], "voice.ogg")
        saved_paths.append(str(path))

    if "audio" in msg:
        audio = msg["audio"]
        path = download_telegram_file(token, audio["file_id"], audio.get("file_name", "audio.mp3"))
        saved_paths.append(str(path))

    return saved_paths


def main() -> None:
    token, allowed_username, configured_chat_id = get_config()
    if not token or token == "SEU_TOKEN_AQUI":
        print("ERRO: Configure TELEGRAM_BOT_TOKEN no arquivo .env antes de iniciar o bot.")
        sys.exit(1)

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    render_pending_md(state)

    print(f"🤖 Bot iniciado! Aguardando mensagens de @{allowed_username}...")
    print(f"📥 Pedidos serão gravados em: {INBOX_DIR / 'PENDING.md'}")

    while True:
        try:
            offset = state.get("last_update_id", 0) + 1
            resp = api_request(
                token,
                "getUpdates",
                {"offset": offset, "timeout": 25},
                timeout=35,
            )
            if not resp.get("ok"):
                time.sleep(3)
                continue

            for update in resp.get("result", []):
                state["last_update_id"] = update["update_id"]
                msg = update.get("message")
                if not msg:
                    save_state(state)
                    continue

                chat_id = str(msg["chat"]["id"])
                sender = msg.get("from", {})
                username = sender.get("username", "")

                allowed_by_user = (
                    allowed_username and username.lower() == allowed_username.lower()
                )
                allowed_by_chat = configured_chat_id and chat_id == str(configured_chat_id)
                if not (allowed_by_user or allowed_by_chat):
                    print(f"⚠️ Mensagem ignorada de @{username or 'desconhecido'} (chat {chat_id})")
                    save_state(state)
                    continue

                if state.get("chat_id") != chat_id:
                    state["chat_id"] = chat_id

                text = (msg.get("text") or msg.get("caption") or "").strip()

                if text == "/start":
                    save_state(state)
                    send_message(
                        token,
                        chat_id,
                        "✅ Bot conectado à ponte do Claude!\n\n"
                        "Envie qualquer texto ou anexo por aqui. "
                        "Tudo será registrado na fila do Claude e ele enviará atualizações e arquivos prontos diretamente neste chat.",
                    )
                    continue

                if text == "/status":
                    pending_count = sum(
                        1 for t in state.get("tasks", []) if t.get("status") != "done"
                    )
                    send_message(
                        token,
                        chat_id,
                        f"📊 Status da ponte:\n• Pedidos pendentes: {pending_count}\n• Chat ID registrado: {chat_id}",
                    )
                    save_state(state)
                    continue

                attachments = extract_attachments(token, msg)
                if not text and not attachments:
                    save_state(state)
                    continue

                task_id = state.get("next_task_id", 1)
                state["next_task_id"] = task_id + 1

                task = {
                    "id": task_id,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "username": username or allowed_username,
                    "chat_id": chat_id,
                    "text": text or "(Anexo sem texto)",
                    "files": attachments,
                    "status": "pending",
                }
                state.setdefault("tasks", []).append(task)
                save_state(state)
                render_pending_md(state)

                with MESSAGES_JSONL.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(task, ensure_ascii=False) + "\n")

                print(f"📩 Pedido #{task_id} recebido de @{task['username']}: {task['text'][:80]}")
                send_message(
                    token,
                    chat_id,
                    f"📥 Pedido #{task_id} recebido e colocado na fila do Claude!\n"
                    f"Assim que houver atualizações ou arquivos prontos, eu te aviso aqui.",
                )

        except urllib.error.URLError as e:
            print(f"⚠️ Erro de rede: {e}. Tentando novamente em 5s...")
            time.sleep(5)
        except KeyboardInterrupt:
            print("\n🛑 Bot encerrado.")
            break
        except Exception as e:
            print(f"⚠️ Erro inesperado: {e}")
            time.sleep(3)


if __name__ == "__main__":
    main()
