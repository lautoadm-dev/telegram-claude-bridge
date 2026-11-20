import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
STATE_FILE = BASE_DIR / "state.json"
INBOX_DIR = BASE_DIR / "inbox"
INBOX_FILES_DIR = INBOX_DIR / "files"
PENDING_MD = INBOX_DIR / "PENDING.md"
MESSAGES_JSONL = INBOX_DIR / "messages.jsonl"


def load_env() -> dict[str, str]:
    env = {}
    if ENV_FILE.exists():
        for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def get_config() -> tuple[str, str, str]:
    env = load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_BOT_TOKEN", "")
    allowed_username = (
        os.environ.get("ALLOWED_USERNAME") or env.get("ALLOWED_USERNAME", "Sonecaroxxx")
    ).lstrip("@")
    chat_id = os.environ.get("CHAT_ID") or env.get("CHAT_ID", "")
    if not chat_id:
        state = load_state()
        chat_id = str(state.get("chat_id", ""))
    return token, allowed_username, chat_id


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"last_update_id": 0, "chat_id": None, "next_task_id": 1, "tasks": []}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def render_pending_md(state: dict) -> None:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    pending = [t for t in state.get("tasks", []) if t.get("status") != "done"]
    done = [t for t in state.get("tasks", []) if t.get("status") == "done"][-10:]

    lines = [
        "# 📥 Pedidos do Telegram (Bridge → Claude)",
        "",
        f"_Última atualização: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
        "",
        "## ⏳ Pendentes",
        "",
    ]

    if not pending:
        lines.append("_Nenhum pedido pendente no momento._")
        lines.append("")
    else:
        for task in pending:
            lines.append(f"### Pedido #{task['id']} ({task['created_at']})")
            lines.append(f"- **Status:** `{task.get('status', 'pending')}`")
            lines.append(f"- **De:** @{task.get('username', 'Sonecaroxxx')}")
            lines.append(f"- **Mensagem:** {task.get('text', '')}")
            if task.get("files"):
                lines.append("- **Anexos recebidos:**")
                for fpath in task["files"]:
                    lines.append(f"  - `{fpath}`")
            lines.append("")

    if done:
        lines.append("## ✅ Concluídos (últimos 10)")
        lines.append("")
        for task in reversed(done):
            lines.append(
                f"- **#{task['id']}** ({task.get('completed_at', '')}): {task.get('text', '')[:120]}"
            )
        lines.append("")

    PENDING_MD.write_text("\n".join(lines), encoding="utf-8")


def api_request(token: str, method: str, data: dict | None = None, timeout: int = 35) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    if data is not None:
        encoded = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(url, data=encoded, method="POST")
    else:
        req = urllib.request.Request(url, method="GET")

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_message(token: str, chat_id: str, text: str) -> dict:
    chunks = [text[i : i + 4000] for i in range(0, len(text), 4000)] or [""]
    last_resp = {}
    for chunk in chunks:
        last_resp = api_request(
            token,
            "sendMessage",
            {"chat_id": str(chat_id), "text": chunk},
        )
    return last_resp


def send_document(token: str, chat_id: str, file_path: Path, caption: str = "") -> dict:
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    boundary = f"----AntigravityBoundary{uuid.uuid4().hex}"
    mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    file_bytes = file_path.read_bytes()

    body = bytearray()

    def add_field(name: str, value: str) -> None:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(f"{value}\r\n".encode("utf-8"))

    add_field("chat_id", str(chat_id))
    if caption:
        add_field("caption", caption[:1024])

    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        f'Content-Disposition: form-data; name="document"; filename="{file_path.name}"\r\n'.encode(
            "utf-8"
        )
    )
    body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
    body.extend(file_bytes)
    body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download_telegram_file(token: str, file_id: str, suggested_name: str) -> Path:
    INBOX_FILES_DIR.mkdir(parents=True, exist_ok=True)
    info = api_request(token, "getFile", {"file_id": file_id})
    remote_path = info["result"]["file_path"]
    ext = Path(remote_path).suffix
    safe_name = suggested_name if suggested_name else f"{file_id}{ext}"
    if not Path(safe_name).suffix and ext:
        safe_name += ext
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = INBOX_FILES_DIR / f"{timestamp}_{safe_name}"
    file_url = f"https://api.telegram.org/file/bot{token}/{remote_path}"
    urllib.request.urlretrieve(file_url, dest)
    return dest
