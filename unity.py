#!/usr/bin/env python3
# ============================================================
#  Unity Code v2.2 — консольный AI-ассистент
#  Один файл. Без внешних зависимостей (stdlib).
#  Python 3.10+
# ============================================================

from __future__ import annotations

import base64
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator


# ============================================================
#  КОНСТАНТЫ
# ============================================================
APP_NAME = "Unity Code"
VERSION = "2.2.0"

CONFIG_DIR = Path.home() / ".unity_code"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "history.json"
PLUGIN_DIR = Path(__file__).resolve().parent / "plugins"

MAX_HISTORY = 40
MAX_FILE_PREVIEW = 200

ALLOWED_SET_KEYS = {
    "provider", "api_key", "api_base", "model",
    "temperature", "max_tokens", "stream", "system_prompt",
    "ollama_hint_shown",
}


# ============================================================
#  ХРАНИЛИЩЕ БЛОКОВ КОДА
# ============================================================
CODE_SNIPPETS: list[dict[str, Any]] = []
SNIPPETS_DIR = CONFIG_DIR / "code_snippets"
SNIPPETS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
#  ЦВЕТА
# ============================================================
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"


def _supports_color() -> bool:
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)
            return True
        except Exception:
            return False
    return sys.stdout.isatty()


USE_COLOR = _supports_color()


def c(text: str, color: str) -> str:
    if not USE_COLOR:
        return text
    return f"{color}{text}{C.RESET}"


def clear_screen() -> None:
    if os.name == "nt":
        os.system("cls")
    else:
        os.system("clear")


# ============================================================
#  АНИМАЦИЯ ЗАГРУЗКИ "UNITY"
# ============================================================
BIG_LETTERS = {
    "U": [
        " ██╗   ██╗ ",
        " ██║   ██║ ",
        " ██║   ██║ ",
        " ██║   ██║ ",
        " ╚██████╔╝ ",
        "  ╚═════╝  ",
    ],
    "N": [
        " ███╗   ██╗ ",
        " ████╗  ██║ ",
        " ██╔██╗ ██║ ",
        " ██║╚██╗██║ ",
        " ██║ ╚████║ ",
        " ╚═╝  ╚═══╝ ",
    ],
    "I": [
        " ██╗ ",
        " ██║ ",
        " ██║ ",
        " ██║ ",
        " ██║ ",
        " ╚═╝ ",
    ],
    "T": [
        " ████████╗ ",
        " ╚══██╔══╝ ",
        "    ██║    ",
        "    ██║    ",
        "    ██║    ",
        "    ╚═╝    ",
    ],
    "Y": [
        " ██╗   ██╗ ",
        " ╚██╗ ██╔╝ ",
        "  ╚████╔╝  ",
        "   ╚██╔╝   ",
        "    ██║    ",
        "    ╚═╝    ",
    ],
}


def _render_word(letters_shown: list[str]) -> list[str]:
    if not letters_shown:
        return [""] * 6
    lines = [""] * 6
    for ch in letters_shown:
        art = BIG_LETTERS.get(ch)
        if not art:
            continue
        for i in range(6):
            lines[i] += art[i] + "  "
    return lines


def animate_boot() -> None:
    if not USE_COLOR:
        print(f"\n  {APP_NAME} v{VERSION}\n")
        return

    word = "UNITY"
    letters_shown: list[str] = []
    interval = 0.30

    for ch in word:
        letters_shown.append(ch)
        lines = _render_word(letters_shown)

        clear_screen()
        print()
        for line in lines:
            print(c(line, C.GREEN + C.BOLD))
        print()
        print(c(f"           {APP_NAME} v{VERSION}", C.MAGENTA + C.BOLD))
        time.sleep(interval)

    clear_screen()
    print()
    for line in _render_word(list(word)):
        print(c(line, C.GREEN + C.BOLD))
    print()
    print(c(f"           {APP_NAME} v{VERSION}", C.MAGENTA + C.BOLD))
    print()
    print(c("  Загрузка...", C.DIM))
    time.sleep(0.5)
    clear_screen()


# ============================================================
#  КОНФИГ
# ============================================================
DEFAULT_CONFIG: dict[str, Any] = {
    "provider": "openai",
    "api_key": "",
    "api_base": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    "temperature": 0.7,
    "max_tokens": 2048,
    "stream": True,
    "system_prompt": (
        "Ты — Unity Code, консольный ассистент для программирования. "
        "Отвечай кратко и по делу. Код оформляй в ``` с указанием языка."
    ),
    "ollama_hint_shown": False,
}


def load_config() -> dict[str, Any]:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            for k, v in DEFAULT_CONFIG.items():
                data.setdefault(k, v)
            return data
        except Exception as e:
            print(c(f"Ошибка config.json: {e}", C.RED))
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict[str, Any]) -> None:
    try:
        CONFIG_FILE.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(c(f"Не сохранить config.json: {e}", C.RED))


# ============================================================
#  ИСТОРИЯ
# ============================================================
def load_history() -> list[dict[str, Any]]:
    if HISTORY_FILE.exists():
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data[-MAX_HISTORY:]
        except Exception:
            pass
    return []


def save_history(history: list[dict[str, Any]]) -> None:
    try:
        HISTORY_FILE.write_text(
            json.dumps(history[-MAX_HISTORY:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


# ============================================================
#  ПОДСВЕТКА КОДА
# ============================================================
KEYWORDS = {
    "python": [
        "def", "class", "return", "if", "else", "elif", "for", "while",
        "import", "from", "as", "try", "except", "finally", "with", "lambda",
        "yield", "async", "await", "True", "False", "None", "and", "or", "not",
        "in", "is", "pass", "break", "continue", "raise", "global", "nonlocal",
    ],
    "javascript": [
        "function", "const", "let", "var", "return", "if", "else", "for",
        "while", "class", "new", "this", "try", "catch", "finally", "throw",
        "async", "await", "true", "false", "null", "undefined",
    ],
    "cpp": [
        "int", "char", "bool", "void", "return", "if", "else", "for", "while",
        "class", "struct", "public", "private", "protected", "new", "delete",
        "try", "catch", "throw", "namespace", "using", "const", "static",
        "true", "false", "nullptr",
    ],
}


def _highlight_line(line: str, lang: str) -> str:
    if not USE_COLOR:
        return line
    result = line
    result = re.sub(r'(".*?"|\'.*?\')', lambda m: c(m.group(0), C.YELLOW), result)
    result = re.sub(r"(#.*$|//.*$)", lambda m: c(m.group(0), C.GRAY), result)
    for kw in KEYWORDS.get(lang.lower(), []):
        result = re.sub(rf"\b{re.escape(kw)}\b",
                        lambda m: c(m.group(0), C.MAGENTA), result)
    return result


# ============================================================
#  HTTP + LLM
# ============================================================
def _post_json(url: str, headers: dict, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Сеть: {e.reason}") from e


def _post_stream(url: str, headers: dict, payload: dict) -> Iterator[dict]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if line.startswith("data: "):
                    line = line[6:]
                if line == "[DONE]":
                    break
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Сеть: {e.reason}") from e


def openai_stream(cfg: dict, messages: list[dict]) -> Iterator[str]:
    url = cfg["api_base"].rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {cfg['api_key']}"}
    payload = {
        "model": cfg["model"], "messages": messages,
        "temperature": cfg["temperature"], "max_tokens": cfg["max_tokens"],
        "stream": True,
    }
    for obj in _post_stream(url, headers, payload):
        try:
            chunk = obj["choices"][0].get("delta", {}).get("content")
            if chunk:
                yield chunk
        except (KeyError, IndexError):
            continue


def openai_blocking(cfg: dict, messages: list[dict]) -> str:
    url = cfg["api_base"].rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {cfg['api_key']}"}
    payload = {
        "model": cfg["model"], "messages": messages,
        "temperature": cfg["temperature"], "max_tokens": cfg["max_tokens"],
    }
    resp = _post_json(url, headers, payload)
    return resp["choices"][0]["message"]["content"]


def anthropic_stream(cfg: dict, messages: list[dict]) -> Iterator[str]:
    url = cfg["api_base"].rstrip("/") + "/messages"
    headers = {"Content-Type": "application/json",
               "x-api-key": cfg["api_key"],
               "anthropic-version": "2023-06-01"}
    system = cfg["system_prompt"]
    user_msgs = [m for m in messages if m["role"] != "system"]
    payload = {
        "model": cfg["model"], "system": system, "messages": user_msgs,
        "max_tokens": cfg["max_tokens"], "temperature": cfg["temperature"],
        "stream": True,
    }
    for obj in _post_stream(url, headers, payload):
        if obj.get("type") == "content_block_delta":
            text = obj.get("delta", {}).get("text")
            if text:
                yield text


def anthropic_blocking(cfg: dict, messages: list[dict]) -> str:
    url = cfg["api_base"].rstrip("/") + "/messages"
    headers = {"Content-Type": "application/json",
               "x-api-key": cfg["api_key"],
               "anthropic-version": "2023-06-01"}
    system = cfg["system_prompt"]
    user_msgs = [m for m in messages if m["role"] != "system"]
    payload = {
        "model": cfg["model"], "system": system, "messages": user_msgs,
        "max_tokens": cfg["max_tokens"], "temperature": cfg["temperature"],
    }
    resp = _post_json(url, headers, payload)
    return resp["content"][0]["text"]


def chat_stream(cfg: dict, messages: list[dict]) -> Iterator[str]:
    p = cfg["provider"].lower()
    if p in ("openai", "custom", "ollama"):
        yield from openai_stream(cfg, messages)
    elif p == "anthropic":
        yield from anthropic_stream(cfg, messages)
    else:
        raise RuntimeError(f"Неизвестный провайдер: {p}")


def chat_blocking(cfg: dict, messages: list[dict]) -> str:
    p = cfg["provider"].lower()
    if p in ("openai", "custom", "ollama"):
        return openai_blocking(cfg, messages)
    if p == "anthropic":
        return anthropic_blocking(cfg, messages)
    raise RuntimeError(f"Неизвестный провайдер: {p}")


# ============================================================
#  ФАЙЛЫ
# ============================================================
def read_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return f"Файл не найден: {path}"
    if not p.is_file():
        return f"Это не файл: {path}"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        if len(lines) > MAX_FILE_PREVIEW:
            head = "\n".join(lines[:MAX_FILE_PREVIEW])
            return f"{head}\n... [{len(lines)} строк всего]"
        return text
    except Exception as e:
        return f"Ошибка: {e}"


def write_file(path: str, content: str) -> str:
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Записано {len(content)} символов в {path}"
    except Exception as e:
        return f"Ошибка записи: {e}"


def list_dir(path: str = ".") -> str:
    try:
        items = sorted(os.listdir(path))
        return "\n".join(items) if items else "(пусто)"
    except Exception as e:
        return f"Ошибка: {e}"


# ============================================================
#  GIT
# ============================================================
def _git(args: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git"] + args, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out.strip()
    except FileNotFoundError:
        return -1, "git не установлен"
    except subprocess.TimeoutExpired:
        return -1, "таймаут"
    except Exception as e:
        return -1, f"Ошибка: {e}"


def git_status() -> str:
    code, out = _git(["status", "--short"])
    return out or "(нет изменений)" if code == 0 else out


def git_diff(staged: bool = False) -> str:
    args = ["diff", "--cached"] if staged else ["diff"]
    code, out = _git(args)
    return out or "(нет изменений)" if code == 0 else out


def git_log(n: int = 10) -> str:
    code, out = _git(["log", f"-{n}", "--oneline"])
    return out if code == 0 else out


def git_branch() -> str:
    code, out = _git(["branch", "--show-current"])
    return out if code == 0 else out


# ============================================================
#  TAB-АВТОДОПОЛНЕНИЕ
# ============================================================
try:
    import readline
    HAS_READLINE = True
except ImportError:
    try:
        import pyreadline3 as readline  # type: ignore
        HAS_READLINE = True
    except ImportError:
        HAS_READLINE = False


def _complete_path(text: str, state: int) -> str | None:
    if not HAS_READLINE:
        return None
    try:
        line = readline.get_line_buffer()
    except Exception:
        return None
    if not any(line.startswith(p) for p in ("/file ", "/write ", "/ls ", "/run ")):
        return None
    matches = []
    try:
        for name in os.listdir("."):
            if name.startswith(text):
                p = Path(name)
                matches.append(name + ("/" if p.is_dir() else ""))
    except Exception:
        pass
    return matches[state] if state < len(matches) else None


def setup_autocomplete() -> None:
    if not HAS_READLINE:
        return
    try:
        readline.set_completer(_complete_path)
        readline.parse_and_bind("tab: complete")
    except Exception:
        pass


# ============================================================
#  MULTIMODAL
# ============================================================
def build_vision_message(text: str, image_path: str) -> dict:
    p = Path(image_path)
    if not p.exists():
        raise FileNotFoundError(f"Нет файла: {image_path}")
    ext = p.suffix.lower()
    mime = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp",
    }.get(ext, "image/png")
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {"type": "image_url",
             "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ],
    }


# ============================================================
#  АГЕНТ
# ============================================================
AGENT_SYSTEM = """Ты — агент Unity Code. Предложи план для задачи пользователя.

Верни ТОЛЬКО валидный JSON без markdown-обёртки:
{
  "plan": "краткое описание",
  "steps": [
    {"action": "read_file", "path": "..."},
    {"action": "write_file", "path": "...", "content": "..."},
    {"action": "run_command", "command": "..."},
    {"action": "finish"}
  ]
}

Только JSON, ничего кроме.
"""


def parse_plan(text: str) -> dict | None:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def propose_plan(cfg: dict, task: str) -> dict | None:
    messages = [
        {"role": "system", "content": AGENT_SYSTEM},
        {"role": "user", "content": task},
    ]
    try:
        raw = chat_blocking(cfg, messages)
        return parse_plan(raw)
    except Exception as e:
        print(c(f"Ошибка агента: {e}", C.RED))
        return None


def show_plan(plan: dict) -> None:
    print(c("\n=== ПЛАН ===", C.CYAN + C.BOLD))
    print(c(plan.get("plan", "(без описания)"), C.WHITE))
    for i, step in enumerate(plan.get("steps", []), 1):
        action = step.get("action", "?")
        detail = step.get("path") or step.get("command") or "(нет деталей)"
        print(f"  {i}. {c(action, C.YELLOW)}: {detail}")
    print()


# ============================================================
#  ПЛАГИНЫ
# ============================================================
class PluginAPI:
    def __init__(self):
        self.commands: dict[str, dict] = {}

    def register_command(self, name: str, handler, help_text: str = "") -> None:
        self.commands[name] = {"handler": handler, "help": help_text}


def load_plugins() -> PluginAPI:
    api = PluginAPI()
    if not PLUGIN_DIR.exists():
        return api
    for py in sorted(PLUGIN_DIR.glob("*.py")):
        if py.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(py.stem, py)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "register"):
                mod.register(api)
        except Exception as e:
            print(c(f"Ошибка плагина {py.name}: {e}", C.RED))
    return api


# ============================================================
#  ПОДСКАЗКА ПРО OLLAMA
# ============================================================
def show_ollama_hint() -> None:
    print()
    print(c("=" * 60, C.CYAN))
    print(c("  НЕТ API-КЛЮЧА? РАБОТАЙ БЕСПЛАТНО ЧЕРЕЗ OLLAMA", C.CYAN + C.BOLD))
    print(c("=" * 60, C.CYAN))
    print()
    print(c("Ollama — это локальный сервер с открытыми моделями.", C.WHITE))
    print(c("Работает без интернета, без ключей, без оплаты.", C.WHITE))
    print()
    print(c("Шаг 1. Скачай и установи Ollama:", C.YELLOW + C.BOLD))
    print(c("   https://ollama.com/download", C.BLUE))
    print(c("   Или через winget:", C.DIM))
    print(c("   winget install --id Ollama.Ollama -e", C.GREEN))
    print()
    print(c("Шаг 2. Скачай модель (в новом cmd):", C.YELLOW + C.BOLD))
    print(c("   ollama pull qwen2.5-coder:1.5b", C.GREEN))
    print(c("   (для слабого ПК: qwen2.5-coder:0.5b)", C.DIM))
    print()
    print(c("Шаг 3. Переключи Unity Code на Ollama:", C.YELLOW + C.BOLD))
    print(c("   /provider ollama", C.GREEN))
    print(c("   /model qwen2.5-coder:1.5b", C.GREEN))
    print()
    print(c("Шаг 4. Проверь:", C.YELLOW + C.BOLD))
    print(c("   Привет", C.GREEN))
    print()
    print(c("Если Ollama уже установлена — просто введи:", C.DIM))
    print(c("   /provider ollama", C.GREEN))
    print()
    print(c("Показать эту подсказку снова: /ollama", C.DIM))
    print(c("=" * 60, C.CYAN))
    print()


# ============================================================
#  ХЕЛП И УТИЛИТЫ
# ============================================================
def print_help(plugin_commands: dict) -> None:
    print(c("\nДоступные команды:", C.CYAN))
    base = [
        ("/help", "справка"),
        ("/exit, /quit", "выход"),
        ("/clear", "очистить историю"),
        ("/config", "показать настройки"),
        ("/reload", "перечитать config.json"),
        ("/set key value", "изменить настройку"),
        ("/model NAME", "сменить модель"),
        ("/provider NAME", "openai | anthropic | ollama | custom"),
        ("/ollama", "подсказка по бесплатной работе через Ollama"),
        ("/copy N", "скопировать блок кода #N в буфер обмена"),
        ("/code", "список блоков кода за сессию"),
        ("/file PATH", "показать файл"),
        ("/write PATH", "записать последний ответ в файл"),
        ("/run CMD", "выполнить команду shell"),
        ("/ls [PATH]", "список файлов"),
        ("/history", "история"),
        ("/img PATH [текст]", "отправить изображение (multimodal)"),
        ("/git status|diff|log|branch", "git-команды"),
        ("/agent TASK", "режим агента: план + подтверждения"),
        ("/plugins", "список плагинов"),
    ]
    for name, desc in base:
        print(f"  {c(name, C.YELLOW)} — {desc}")
    for name, meta in plugin_commands.items():
        print(f"  {c(name, C.MAGENTA)} — {meta.get('help', '')} (плагин)")
    print()


def print_config(cfg: dict) -> None:
    print(c("\nНастройки:", C.CYAN))
    for k, v in cfg.items():
        if k == "api_key" and v:
            v = v[:4] + "..." + v[-4:] if len(v) > 8 else "***"
        if k == "system_prompt" and len(str(v)) > 60:
            v = str(v)[:60] + "..."
        print(f"  {c(k, C.YELLOW)}: {v}")
    print()


def ask_yes_no(prompt: str) -> bool:
    try:
        ans = input(c(f"{prompt} [y/N]: ", C.YELLOW)).strip().lower()
        return ans in ("y", "yes", "д", "да")
    except (EOFError, KeyboardInterrupt):
        return False


def run_shell(cmd: str, confirm: bool = True) -> tuple[int, str]:
    if confirm and not ask_yes_no(f"Выполнить: {cmd}?"):
        return -1, "Отменено пользователем"
    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60,
        )
        return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return -1, "Таймаут 60 сек"
    except Exception as e:
        return -1, f"Ошибка: {e}"


# ============================================================
#  БУФЕР ОБМЕНА + СОХРАНЕНИЕ БЛОКОВ
# ============================================================
def _copy_to_clipboard(text: str) -> bool:
    """Копирует текст в буфер обмена. Возвращает True при успехе."""
    try:
        if os.name == "nt":
            proc = subprocess.Popen("clip", stdin=subprocess.PIPE, shell=True)
            proc.communicate(text.encode("utf-16le"))
            return True
        if sys.platform == "darwin":
            proc = subprocess.Popen("pbcopy", stdin=subprocess.PIPE)
            proc.communicate(text.encode("utf-8"))
            return True
        for cmd in (["xclip", "-selection", "clipboard"],
                    ["xsel", "--clipboard", "--input"]):
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                proc.communicate(text.encode("utf-8"))
                return True
            except FileNotFoundError:
                continue
    except Exception:
        pass
    return False


def _save_snippet(n: int, lang: str, code: str) -> Path | None:
    """Сохраняет блок кода в файл."""
    try:
        ext = {
            "python": ".py", "py": ".py",
            "javascript": ".js", "js": ".js",
            "typescript": ".ts", "ts": ".ts",
            "cpp": ".cpp", "c": ".c", "csharp": ".cs", "cs": ".cs",
            "java": ".java", "rust": ".rs", "go": ".go",
            "bash": ".sh", "sh": ".sh", "shell": ".sh",
            "html": ".html", "css": ".css", "json": ".json",
            "yaml": ".yml", "yml": ".yml", "sql": ".sql",
            "php": ".php", "ruby": ".rb", "rb": ".rb",
        }.get(lang.lower(), ".txt")
        filename = f"snippet_{n:03d}{ext}"
        path = SNIPPETS_DIR / filename
        path.write_text(code, encoding="utf-8")
        return path
    except Exception:
        return None


# ============================================================
#  СТРИМИНГ С ПОДСВЕТКОЙ И НУМЕРАЦИЕЙ БЛОКОВ
# ============================================================
def stream_answer(cfg: dict, messages: list[dict]) -> str:
    buf: list[str] = []
    in_code = False
    code_lang = ""
    line_buffer = ""
    code_lines: list[str] = []
    code_counter = len(CODE_SNIPPETS)

    def flush_line() -> None:
        nonlocal line_buffer
        if not line_buffer:
            return
        if in_code:
            print(_highlight_line(line_buffer, code_lang))
            code_lines.append(line_buffer)
        else:
            print(line_buffer)
        line_buffer = ""

    for chunk in chat_stream(cfg, messages):
        buf.append(chunk)
        for ch in chunk:
            if ch == "\n":
                flush_line()
            else:
                line_buffer += ch

            if not in_code and line_buffer.endswith("```"):
                in_code = True
                code_lang = ""
                code_lines = []
                code_counter += 1
                line_buffer = line_buffer[:-3]
                flush_line()
                print()
                print(c(f"┌─ Код #{code_counter} ", C.CYAN + C.BOLD))

            elif in_code and line_buffer.startswith("```") and len(line_buffer) > 3:
                in_code = False
                line_buffer = ""
                code_text = "\n".join(code_lines)
                path = _save_snippet(code_counter, code_lang or "txt", code_text)
                CODE_SNIPPETS.append({
                    "n": code_counter,
                    "lang": code_lang or "txt",
                    "code": code_text,
                    "path": str(path) if path else "",
                })
                print(c(f"└─ конец кода #{code_counter}", C.CYAN))
                if path:
                    print(c(f"   сохранено: {path}", C.DIM))
                print(c(f"   → скопировать: /copy {code_counter}", C.YELLOW))
                print()

        if in_code and not code_lang:
            if line_buffer and len(line_buffer) < 20 and line_buffer.strip():
                if not line_buffer.startswith("```"):
                    code_lang = line_buffer.strip()
                    line_buffer = ""
                    print(c(f"│ язык: {code_lang}", C.DIM))

    flush_line()
    print()
    return "".join(buf)


def send_message(cfg: dict, history: list[dict], user_msg: Any) -> str | None:
    history.append({"role": "user", "content": user_msg})
    system = [m for m in history if m["role"] == "system"][:1]
    rest = [m for m in history if m["role"] != "system"][-MAX_HISTORY:]
    history[:] = system + rest
    try:
        answer = stream_answer(cfg, history)
        history.append({"role": "assistant", "content": answer})
        save_history(history)
        return answer
    except KeyboardInterrupt:
        print(c("\nПрервано.", C.YELLOW))
        history.pop()
        return None
    except Exception as e:
        print(c(f"\nОшибка: {e}", C.RED))
        history.pop()
        return None


# ============================================================
#  АГЕНТ — ВЫПОЛНЕНИЕ
# ============================================================
def run_agent(cfg: dict, task: str) -> None:
    plan = propose_plan(cfg, task)
    if not plan:
        print(c("Не удалось получить план.", C.RED))
        return
    show_plan(plan)
    if not ask_yes_no("Выполнять план пошагово?"):
        return
    for i, step in enumerate(plan.get("steps", []), 1):
        action = step.get("action")
        print(c(f"\n[{i}] {action}", C.CYAN + C.BOLD))
        if action == "read_file":
            print(read_file(step.get("path", "")))
        elif action == "write_file":
            path = step.get("path", "")
            content = step.get("content", "")
            print(c(f"Записать {len(content)} символов в {path}", C.YELLOW))
            if ask_yes_no("Подтвердить запись?"):
                print(write_file(path, content))
        elif action == "run_command":
            cmd = step.get("command", "")
            code, out = run_shell(cmd, confirm=True)
            print(c(f"[код {code}]", C.DIM))
            print(out or "(нет вывода)")
        elif action == "finish":
            print(c("Готово.", C.GREEN))
            break
        else:
            print(c(f"Неизвестное действие: {action}", C.RED))


# ============================================================
#  ОБРАБОТКА КОМАНД
# ============================================================
def handle_command(
    user: str,
    cfg: dict,
    history: list[dict],
    plugins: PluginAPI,
) -> bool:
    try:
        parts = shlex.split(user)
    except ValueError as e:
        print(c(f"Ошибка разбора команды: {e}", C.RED))
        return True

    if not parts:
        return True

    cmd = parts[0].lower()

    if cmd in plugins.commands:
        try:
            plugins.commands[cmd]["handler"](
                parts[1:], {"cfg": cfg, "history": history}
            )
        except Exception as e:
            print(c(f"Ошибка плагина: {e}", C.RED))
        return True

    if cmd in ("/exit", "/quit"):
        return False

    elif cmd == "/help":
        print_help(plugins.commands)

    elif cmd == "/clear":
        history[:] = [{"role": "system", "content": cfg["system_prompt"]}]
        save_history(history)
        print(c("История очищена.", C.YELLOW))

    elif cmd == "/config":
        print_config(cfg)

    elif cmd == "/reload":
        new_cfg = load_config()
        cfg.clear()
        cfg.update(new_cfg)
        print(c("Конфиг перечитан.", C.GREEN))

    elif cmd == "/ollama":
        show_ollama_hint()

    elif cmd == "/copy":
        if not parts[1:]:
            print(c("Использование: /copy N", C.RED))
            print(c("Где N — номер блока кода (смотри 'Код #N' в ответе).", C.DIM))
            print(c("Все блоки: /code", C.DIM))
        else:
            try:
                n = int(parts[1])
            except ValueError:
                print(c("N должно быть числом", C.RED))
                return True
            found = next((s for s in CODE_SNIPPETS if s["n"] == n), None)
            if not found:
                print(c(f"Блок #{n} не найден. /code — список.", C.RED))
            else:
                if _copy_to_clipboard(found["code"]):
                    print(c(f"✓ Код #{n} скопирован в буфер обмена", C.GREEN))
                    print(c(f"  язык: {found['lang']}, {len(found['code'])} символов", C.DIM))
                else:
                    print(c("Не удалось скопировать автоматически.", C.RED))
                    if found["path"]:
                        print(c(f"Файл: {found['path']}", C.YELLOW))
                        print(c("Скопируй вручную из файла.", C.DIM))

    elif cmd == "/code":
        if not CODE_SNIPPETS:
            print(c("В этой сессии ещё не было блоков кода.", C.YELLOW))
        else:
            print(c(f"\nБлоки кода в сессии ({len(CODE_SNIPPETS)}):", C.CYAN))
            for s in CODE_SNIPPETS:
                preview = s["code"][:60].replace("\n", " ")
                print(f"  {c('#' + str(s['n']), C.YELLOW)} "
                      f"[{s['lang']}] {preview}...")
                print(c(f"     → /copy {s['n']}   файл: {s['path']}", C.DIM))
            print()

    elif cmd == "/plugins":
        if not plugins.commands:
            print(c("Плагины не загружены.", C.YELLOW))
        else:
            print(c("\nЗагруженные плагины:", C.CYAN))
            for name, meta in plugins.commands.items():
                print(f"  {c(name, C.MAGENTA)} — {meta.get('help', '')}")
            print()

    elif cmd == "/history":
        for m in history[-10:]:
            role = m["role"]
            content = str(m.get("content", ""))[:120]
            col = C.GREEN if role == "user" else C.BLUE
            print(f"  {c(role, col)}: {content}")

    elif cmd == "/set":
        if len(parts) < 3:
            print(c("Использование: /set key value", C.RED))
        else:
            key, value = parts[1], " ".join(parts[2:])
            if key not in ALLOWED_SET_KEYS:
                print(c(f"Неизвестный ключ: {key}", C.RED))
                print(c(f"Разрешены: {', '.join(sorted(ALLOWED_SET_KEYS))}", C.DIM))
                return True
            if key == "temperature":
                try:
                    value = float(value)
                except ValueError:
                    print(c("temperature — число", C.RED))
                    return True
            elif key == "max_tokens":
                try:
                    value = int(value)
                except ValueError:
                    print(c("max_tokens — целое", C.RED))
                    return True
            elif key in ("stream", "ollama_hint_shown"):
                value = value.lower() in ("1", "true", "yes", "on", "да")
            cfg[key] = value
            save_config(cfg)
            print(c(f"{key} = {value}", C.GREEN))

    elif cmd == "/model":
        if len(parts) < 2:
            print(c(f"Модель: {cfg['model']}", C.YELLOW))
        else:
            cfg["model"] = parts[1]
            save_config(cfg)
            print(c(f"Модель: {cfg['model']}", C.GREEN))

    elif cmd == "/provider":
        if len(parts) < 2:
            print(c(f"Провайдер: {cfg['provider']}", C.YELLOW))
        else:
            p = parts[1].lower()
            if p not in ("openai", "anthropic", "ollama", "custom"):
                print(c("openai | anthropic | ollama | custom", C.RED))
            else:
                cfg["provider"] = p
                if p == "openai":
                    cfg["api_base"] = "https://api.openai.com/v1"
                elif p == "anthropic":
                    cfg["api_base"] = "https://api.anthropic.com/v1"
                elif p == "ollama":
                    cfg["api_base"] = "http://localhost:11434/v1"
                elif p == "custom":
                    try:
                        url = input("API base URL: ").strip()
                        if url:
                            cfg["api_base"] = url
                    except (EOFError, KeyboardInterrupt):
                        pass
                save_config(cfg)
                print(c(f"Провайдер: {p}, base: {cfg['api_base']}", C.GREEN))

    elif cmd == "/file":
        if len(parts) < 2:
            print(c("Использование: /file PATH", C.RED))
        else:
            print(read_file(parts[1]))

    elif cmd == "/ls":
        print(list_dir(parts[1] if len(parts) > 1 else "."))

    elif cmd == "/write":
        if len(parts) < 2:
            print(c("Использование: /write PATH", C.RED))
        else:
            last = next(
                (m["content"] for m in reversed(history)
                 if m["role"] == "assistant"),
                None,
            )
            if last is None:
                print(c("Нет ответа для записи.", C.RED))
            elif ask_yes_no(f"Записать в {parts[1]}?"):
                print(write_file(parts[1], last))

    elif cmd == "/run":
        if len(parts) < 2:
            print(c("Использование: /run CMD", C.RED))
        else:
            command = " ".join(parts[1:])
            code, out = run_shell(command, confirm=True)
            print(c(f"[код {code}]", C.DIM))
            print(out or "(нет вывода)")

    elif cmd == "/img":
        if len(parts) < 2:
            print(c("Использование: /img PATH [текст]", C.RED))
        else:
            text = " ".join(parts[2:]) or "Что на этом изображении?"
            try:
                msg = build_vision_message(text, parts[1])
                send_message(cfg, history, msg["content"])
            except Exception as e:
                print(c(f"Ошибка: {e}", C.RED))

    elif cmd == "/git":
        sub = parts[1].lower() if len(parts) > 1 else "status"
        if sub == "status":
            print(git_status())
        elif sub == "diff":
            staged = "--cached" in parts or "-s" in parts
            print(git_diff(staged))
        elif sub == "log":
            print(git_log())
        elif sub == "branch":
            print(git_branch())
        else:
            print(c("git status | diff | log | branch", C.RED))

    elif cmd == "/agent":
        if len(parts) < 2:
            print(c("Использование: /agent TASK", C.RED))
        else:
            task = " ".join(parts[1:])
            run_agent(cfg, task)

    else:
        print(c(f"Неизвестная команда: {cmd}. /help", C.RED))

    return True


# ============================================================
#  ОСНОВНОЙ ЦИКЛ
# ============================================================
def repl(cfg: dict) -> None:
    plugins = load_plugins()
    setup_autocomplete()

    history = load_history()
    if not history:
        history.append({"role": "system", "content": cfg["system_prompt"]})

    print(c(f"{APP_NAME} v{VERSION}", C.MAGENTA + C.BOLD))
    print(c(f"{cfg['provider']} | {cfg['model']} | stream={cfg['stream']}", C.DIM))
    print(c("Команды: /help\n", C.DIM))

    while True:
        try:
            user = input(c(">>> ", C.GREEN + C.BOLD)).strip()
        except (EOFError, KeyboardInterrupt):
            print(c("\nВыход.", C.YELLOW))
            break
        if not user:
            continue

        if user.startswith("/"):
            if not handle_command(user, cfg, history, plugins):
                break
            continue

        send_message(cfg, history, user)


# ============================================================
#  ТОЧКА ВХОДА
# ============================================================
def print_cli_help() -> None:
    print(f"{APP_NAME} v{VERSION}")
    print()
    print("Использование:")
    print("  python unity.py            — запустить")
    print("  python unity.py --version  — версия")
    print("  python unity.py --help     — эта справка")
    print()
    print("Настройки хранятся в:")
    print(f"  {CONFIG_FILE}")
    print(f"  {HISTORY_FILE}")
    print(f"  {SNIPPETS_DIR}")


def main() -> int:
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ("--version", "-v"):
            print(f"{APP_NAME} v{VERSION}")
            return 0
        if arg in ("--help", "-h"):
            print_cli_help()
            return 0

    try:
        animate_boot()
    except Exception:
        pass

    cfg = load_config()

    if cfg["provider"] in ("openai", "anthropic", "custom") and not cfg["api_key"]:
        print(c(f"{APP_NAME} v{VERSION}", C.MAGENTA + C.BOLD))
        print(c("API-ключ не задан.", C.YELLOW))
        print()

        if not cfg.get("ollama_hint_shown"):
            show_ollama_hint()
            cfg["ollama_hint_shown"] = True
            save_config(cfg)
        else:
            print(c("Подсказка по Ollama: /ollama", C.DIM))
            print()

        print(c("Что делать?", C.WHITE + C.BOLD))
        print("  1) Введи API-ключ OpenAI/Anthropic сейчас")
        print("  2) Нажми Enter — пропустить (настроишь позже)")
        print("  3) Работай через Ollama: /provider ollama")
        print()
        print(c(f"Конфиг: {CONFIG_FILE}", C.DIM))
        print()

        try:
            key = input(c("API-ключ (или Enter — пропустить): ", C.CYAN)).strip()
        except (EOFError, KeyboardInterrupt):
            key = ""
        if key:
            cfg["api_key"] = key
            save_config(cfg)
            print(c("Ключ сохранён.", C.GREEN))

    try:
        repl(cfg)
    except KeyboardInterrupt:
        print(c("\nВыход.", C.YELLOW))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        import traceback
        print(f"\nКритическая ошибка: {e}")
        traceback.print_exc()
        if os.name == "nt":
            input("\nНажми Enter для выхода...")
        sys.exit(1)