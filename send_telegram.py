import argparse
import sys
from datetime import datetime
from pathlib import Path

from telegram_api import (
    PENDING_MD,
    get_config,
    load_state,
    render_pending_md,
    save_state,
    send_document,
    send_message,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CLI da ponte Telegram <-> Claude (ler pedidos, enviar atualizações e anexos)."
    )
    parser.add_argument("--read", action="store_true", help="Mostra os pedidos pendentes do Telegram.")
    parser.add_argument("--text", type=str, help="Envia uma mensagem de texto/atualização no Telegram.")
    parser.add_argument("--file", type=str, help="Caminho de um arquivo para anexar no Telegram.")
    parser.add_argument("--caption", type=str, default="", help="Legenda opcional para o anexo.")
    parser.add_argument("--done", type=int, help="Marca o Pedido #ID como concluído.")
    parser.add_argument("--working", type=int, help="Marca o Pedido #ID como em andamento.")

    args = parser.parse_args()

    if args.read:
        state = load_state()
        render_pending_md(state)
        print(PENDING_MD.read_text(encoding="utf-8"))
        return

    token, _, chat_id = get_config()
    if not token or token == "SEU_TOKEN_AQUI":
        print("ERRO: TELEGRAM_BOT_TOKEN não configurado no .env.", file=sys.stderr)
        sys.exit(1)

    state = load_state()
    if not chat_id:
        print(
            "ERRO: CHAT_ID ainda não registrado. Envie /start para o bot no Telegram primeiro.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.working is not None:
        for task in state.get("tasks", []):
            if task["id"] == args.working:
                task["status"] = "in_progress"
                save_state(state)
                render_pending_md(state)
                print(f"Pedido #{args.working} marcado como em andamento.")
                break

    if args.done is not None:
        for task in state.get("tasks", []):
            if task["id"] == args.done:
                task["status"] = "done"
                task["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                save_state(state)
                render_pending_md(state)
                print(f"Pedido #{args.done} marcado como concluído.")
                break

    if args.text:
        send_message(token, chat_id, args.text)
        print("Mensagem enviada ao Telegram com sucesso.")

    if args.file:
        fpath = Path(args.file)
        if not fpath.exists():
            print(f"ERRO: Arquivo não encontrado: {fpath}", file=sys.stderr)
            sys.exit(1)
        send_document(token, chat_id, fpath, caption=args.caption)
        print(f"Anexo enviado ao Telegram com sucesso: {fpath.name}")


if __name__ == "__main__":
    main()
