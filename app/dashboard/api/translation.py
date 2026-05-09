"""
Translation API Blueprint.

Endpoints:
  GET  /api/translation/config                 get translation service config
  POST /api/translation/config                 save translation service config
  POST /api/translation/translate              translate a piece of text
  GET  /api/translation/settings/<jid>         get per-conversation translation settings
  POST /api/translation/settings/<jid>         save per-conversation translation settings

Translation providers (tried in order when provider == "auto"):
  1. LibreTranslate  — if libretranslate_url is configured (or LIBRETRANSLATE_URL env)
  2. DeepL           — if deepl_key is configured (or DEEPL_API_KEY env)
  3. OpenAI          — if openai_key is configured (or OPENAI_API_KEY env)
  4. GLM (Zhipu AI) — if glm_key is configured (or GLM_API_KEY env)
  5. Qwen (Alibaba) — if qwen_key is configured (or QWEN_API_KEY env)
  6. stub            — always returns a "not configured" response

Config is persisted to data/translation_config.json so keys survive server restarts.
"""

import json
import logging
import os
import pathlib
import re
import time
import urllib.request
import urllib.parse
from threading import Lock

from flask import Blueprint, jsonify, request, current_app

from app.dashboard.api.auth import check_bearer
from app.dashboard.api.rate_limit import limiter
from app.dashboard.utils.db_init import get_db_connection

translation_bp = Blueprint("translation", __name__)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Persistent config file
# ---------------------------------------------------------------------------

_CONFIG_FILE = pathlib.Path(__file__).resolve().parents[3] / "data" / "translation_config.json"


def _load_config_file() -> dict:
    """Load saved config from disk. Returns {} if the file doesn't exist or is unreadable."""
    try:
        if _CONFIG_FILE.exists():
            with _CONFIG_FILE.open("r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load translation config from %s: %s", _CONFIG_FILE, exc)
    return {}


def _save_config_file(cfg: dict) -> None:
    """Persist current config to disk (plain-text including secrets)."""
    try:
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _CONFIG_FILE.open("w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not save translation config to %s: %s", _CONFIG_FILE, exc)


# ---------------------------------------------------------------------------
# In-memory translation service config  (seeded from env vars, then disk)
# ---------------------------------------------------------------------------

_config_lock = Lock()
_translation_config: dict = {
    "provider": "auto",
    "target_lang": "zh",
    "libretranslate_url": os.environ.get("LIBRETRANSLATE_URL", ""),
    "libretranslate_key": os.environ.get("LIBRETRANSLATE_API_KEY", ""),
    "deepl_key": os.environ.get("DEEPL_API_KEY", ""),
    "openai_key": os.environ.get("TRANSLATE_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY", ""),
    "openai_api_url": os.environ.get("TRANSLATE_OPENAI_API_URL", ""),
    "openai_model": os.environ.get("TRANSLATE_OPENAI_MODEL", "gpt-4o-mini"),
    "glm_key": os.environ.get("GLM_API_KEY", ""),
    "glm_model": os.environ.get("GLM_MODEL", "glm-4-flash"),
    "qwen_key": os.environ.get("QWEN_API_KEY", ""),
    "qwen_model": os.environ.get("QWEN_MODEL", "qwen-turbo"),
}
# Overlay with persisted values (saved keys override env-var defaults)
_translation_config.update(_load_config_file())

# ---------------------------------------------------------------------------
# In-memory settings store (per-jid)
# ---------------------------------------------------------------------------

_settings_lock = Lock()
# { jid: {"enabled": bool, "target_lang": str, "provider": str} }
_jid_settings: dict[str, dict] = {}

_DEFAULT_TARGET_LANG = "zh"
_DEFAULT_PROVIDER = "auto"  # auto = try providers in order


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

@translation_bp.before_request
def _check_auth():
    return check_bearer()


# ---------------------------------------------------------------------------
# GET /api/translation/config
# ---------------------------------------------------------------------------

@translation_bp.route("/config", methods=["GET"])
@limiter.limit("60/minute")
def get_config():
    """Return translation service config. API keys are masked."""
    with _config_lock:
        cfg = dict(_translation_config)
    # Mask secrets for display
    masked = {k: ("*" * 8 if k.endswith("_key") and v else v) for k, v in cfg.items()}
    return jsonify(masked)


# ---------------------------------------------------------------------------
# POST /api/translation/config
# ---------------------------------------------------------------------------

_ALLOWED_CONFIG_KEYS = {
    "provider", "target_lang",
    "libretranslate_url", "libretranslate_key",
    "deepl_key",
    "openai_key", "openai_api_url", "openai_model",
    "glm_key", "glm_model",
    "qwen_key", "qwen_model",
    "google_enabled",
}

@translation_bp.route("/config", methods=["POST"])
@limiter.limit("30/minute")
def save_config():
    """Save translation service config."""
    body = request.get_json(silent=True) or {}
    unknown = set(body.keys()) - _ALLOWED_CONFIG_KEYS
    if unknown:
        return jsonify({"error": f"Unknown config keys: {unknown}"}), 400

    with _config_lock:
        for key in _ALLOWED_CONFIG_KEYS:
            if key in body:
                # Don't overwrite a real key with the masked placeholder
                if body[key] != "********":
                    _translation_config[key] = str(body[key]).strip()
        snapshot = dict(_translation_config)
    _save_config_file(snapshot)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# POST /api/translation/translate
# ---------------------------------------------------------------------------

@translation_bp.route("/translate", methods=["POST"])
@limiter.limit("60/minute")
def translate_text():
    """
    Translate a text snippet.

    Body JSON:
      {
        "text":        str   (required),
        "from_lang":   str   (optional, default "auto"),
        "to_lang":     str   (optional, default "zh"),
        "provider":    str   (optional: "auto" | "libretranslate" | "deepl" | "openai" | "glm" | "qwen")
      }

    Response:
      { "translated": str, "from_lang": str, "to_lang": str, "provider": str }
    """
    body = request.get_json(silent=True) or {}
    text = str(body.get("text", "")).strip()
    from_lang = str(body.get("from_lang", "auto")).strip()
    with _config_lock:
        cfg_target = _translation_config.get("target_lang", _DEFAULT_TARGET_LANG)
        cfg_provider = _translation_config.get("provider", _DEFAULT_PROVIDER)
    to_lang = str(body.get("to_lang", cfg_target)).strip()
    provider = str(body.get("provider", cfg_provider)).strip()

    if not text:
        return jsonify({"error": "text is required"}), 400

    translated, used_provider, err = _do_translate(text, from_lang, to_lang, provider)
    if err:
        return jsonify({
            "error": err,
            "text": text,
            "translated": None,
            "provider": used_provider,
        }), 502

    return jsonify({
        "translated": translated,
        "original": text,
        "from_lang": from_lang,
        "to_lang": to_lang,
        "provider": used_provider,
    })


# ---------------------------------------------------------------------------
# GET /api/translation/settings/<jid>
# ---------------------------------------------------------------------------

@translation_bp.route("/settings/<path:jid>", methods=["GET"])
@limiter.limit("120/minute")
def get_settings(jid: str):
    with _settings_lock:
        settings = _jid_settings.get(jid, {
            "enabled": False,
            "target_lang": _DEFAULT_TARGET_LANG,
            "provider": _DEFAULT_PROVIDER,
        })
    return jsonify({"jid": jid, **settings})


# ---------------------------------------------------------------------------
# POST /api/translation/settings/<jid>
# ---------------------------------------------------------------------------

@translation_bp.route("/settings/<path:jid>", methods=["POST"])
@limiter.limit("30/minute")
def save_settings(jid: str):
    body = request.get_json(silent=True) or {}
    with _settings_lock:
        current = _jid_settings.get(jid, {
            "enabled": False,
            "target_lang": _DEFAULT_TARGET_LANG,
            "provider": _DEFAULT_PROVIDER,
        })
        if "enabled" in body:
            current["enabled"] = bool(body["enabled"])
        if "target_lang" in body:
            current["target_lang"] = str(body["target_lang"]).strip()
        if "provider" in body:
            current["provider"] = str(body["provider"]).strip()
        _jid_settings[jid] = current

    return jsonify({"jid": jid, **current})


# ---------------------------------------------------------------------------
# PATCH /api/translation/message/<id>
# ---------------------------------------------------------------------------

@translation_bp.route("/message/<int:message_id>", methods=["PATCH"])
@limiter.limit("300/minute")
def save_message_translation(message_id: int):
    """Persist a client-side translation result into the chat_messages row."""
    err = _check_auth()
    if err:
        return err

    body = request.get_json(silent=True) or {}
    translated_content = body.get("translated_content", "")
    if not isinstance(translated_content, str):
        return jsonify({"error": "translated_content must be a string"}), 400

    db_path = current_app.config["DASHBOARD_DB_PATH"]
    with get_db_connection(db_path) as conn:
        result = conn.execute(
            "UPDATE chat_messages SET translated_content = ? WHERE id = ?",
            (translated_content or None, message_id),
        )
        conn.commit()

    if result.rowcount == 0:
        return jsonify({"error": "message not found"}), 404

    return jsonify({"id": message_id, "translated_content": translated_content or None})


# ---------------------------------------------------------------------------
# Translation provider implementations
# ---------------------------------------------------------------------------

def _do_translate(
    text: str,
    from_lang: str,
    to_lang: str,
    provider: str,
) -> tuple[str | None, str, str | None]:
    """
    Returns (translated_text, provider_used, error_message).
    error_message is None on success.
    """
    providers_to_try: list[str] = (
        ["google", "libretranslate", "deepl", "openai", "glm", "qwen"]
        if provider == "auto"
        else [provider]
    )

    for p in providers_to_try:
        try:
            result = _call_provider(p, text, from_lang, to_lang)
            if result is not None:
                return result, p, None
        except Exception as exc:
            logger.debug("Provider %s failed: %s", p, exc)

    return (
        None,
        "none",
        "No translation provider configured. Set one of: LIBRETRANSLATE_URL, DEEPL_API_KEY, OPENAI_API_KEY, GLM_API_KEY, QWEN_API_KEY, or enable Google.",
    )


def _call_provider(provider: str, text: str, from_lang: str, to_lang: str) -> str | None:
    """Call a specific provider. Returns translated text or None if not configured."""
    if provider == "google":
        return _google_translate(text, from_lang, to_lang)
    if provider == "libretranslate":
        return _libretranslate(text, from_lang, to_lang)
    if provider == "deepl":
        return _deepl(text, from_lang, to_lang)
    if provider == "openai":
        return _openai_translate(text, from_lang, to_lang)
    if provider == "glm":
        return _glm_translate(text, from_lang, to_lang)
    if provider == "qwen":
        return _qwen_translate(text, from_lang, to_lang)
    return None


def _libretranslate(text: str, from_lang: str, to_lang: str) -> str | None:
    with _config_lock:
        base_url = (_translation_config.get("libretranslate_url") or os.environ.get("LIBRETRANSLATE_URL", "")).rstrip("/")
        api_key = _translation_config.get("libretranslate_key") or os.environ.get("LIBRETRANSLATE_API_KEY", "")
    if not base_url:
        return None
    payload = json.dumps({
        "q": text,
        "source": from_lang if from_lang != "auto" else "auto",
        "target": to_lang,
        "format": "text",
        "api_key": api_key,
    }).encode()

    req = urllib.request.Request(
        f"{base_url}/translate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        result = json.loads(resp.read())
    return result["translatedText"]


def _deepl(text: str, from_lang: str, to_lang: str) -> str | None:
    with _config_lock:
        api_key = _translation_config.get("deepl_key") or os.environ.get("DEEPL_API_KEY", "")
    if not api_key:
        return None

    # DeepL uses different endpoint for free vs pro keys
    base = (
        "https://api-free.deepl.com/v2"
        if api_key.endswith(":fx")
        else "https://api.deepl.com/v2"
    )
    params_dict: dict = {"text": text, "target_lang": to_lang.upper()}
    if from_lang and from_lang != "auto":
        params_dict["source_lang"] = from_lang.upper()

    payload = urllib.parse.urlencode(params_dict).encode()
    req = urllib.request.Request(
        f"{base}/translate",
        data=payload,
        headers={
            "Authorization": f"DeepL-Auth-Key {api_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        result = json.loads(resp.read())
    return result["translations"][0]["text"]


def _openai_translate(text: str, from_lang: str, to_lang: str) -> str | None:
    with _config_lock:
        api_key = (
            _translation_config.get("openai_key")
            or os.environ.get("TRANSLATE_OPENAI_API_KEY")
            or os.environ.get("OPENAI_API_KEY", "")
        )
    if not api_key:
        return None

    with _config_lock:
        api_url = (
            _translation_config.get("openai_api_url")
            or os.environ.get("TRANSLATE_OPENAI_API_URL", "")
        ).rstrip("/") or "https://api.openai.com/v1"
        model = _translation_config.get("openai_model") or os.environ.get("TRANSLATE_OPENAI_MODEL", "gpt-4o-mini")
    api_url = f"{api_url}/chat/completions"

    if from_lang == "auto":
        instruction = f"Translate the following text to {to_lang}. Only output the translation, nothing else."
    else:
        instruction = f"Translate the following text from {from_lang} to {to_lang}. Only output the translation, nothing else."

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": text},
        ],
        "temperature": 0.2,
        "max_tokens": 1024,
    }).encode()

    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        result = json.loads(resp.read())
    return result["choices"][0]["message"]["content"].strip()


def _glm_translate(text: str, from_lang: str, to_lang: str) -> str | None:
    """Zhipu AI GLM — OpenAI-compatible endpoint at open.bigmodel.cn."""
    with _config_lock:
        api_key = _translation_config.get("glm_key") or os.environ.get("GLM_API_KEY", "")
        model = _translation_config.get("glm_model") or os.environ.get("GLM_MODEL", "glm-4-flash")
    if not api_key:
        return None

    if from_lang == "auto":
        instruction = f"Translate the following text to {to_lang}. Only output the translation, nothing else."
    else:
        instruction = f"Translate the following text from {from_lang} to {to_lang}. Only output the translation, nothing else."

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": text},
        ],
        "temperature": 0.2,
        "max_tokens": 1024,
    }).encode()

    req = urllib.request.Request(
        "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        result = json.loads(resp.read())
    return result["choices"][0]["message"]["content"].strip()


def _qwen_translate(text: str, from_lang: str, to_lang: str) -> str | None:
    """Alibaba Qwen — OpenAI-compatible endpoint (DashScope compatible mode)."""
    with _config_lock:
        api_key = _translation_config.get("qwen_key") or os.environ.get("QWEN_API_KEY", "")
        model = _translation_config.get("qwen_model") or os.environ.get("QWEN_MODEL", "qwen-turbo")
    if not api_key:
        return None

    if from_lang == "auto":
        instruction = f"Translate the following text to {to_lang}. Only output the translation, nothing else."
    else:
        instruction = f"Translate the following text from {from_lang} to {to_lang}. Only output the translation, nothing else."

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": text},
        ],
        "temperature": 0.2,
        "max_tokens": 1024,
    }).encode()

    req = urllib.request.Request(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        result = json.loads(resp.read())
    return result["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Google Translate  (no API key required)
# ---------------------------------------------------------------------------

# Pre-compiled regexes matching the HTML spans in Google's async translate page
_GT_TEXT_RE = re.compile(r'id="tw-answ-target-text">([^<]+)</span>')

_GT_PA_URL = "https://translate-pa.googleapis.com/v1/translateHtml"
_GT_PA_KEY = "AIzaSyATBXajvzQLTDHEQbcpq0Ihe0vWDHmO520"
_GT_ASYNC_BASE = "https://www.google.com/async/translate?"
_GT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/144.0.0.0 Safari/537.36"
)


def _google_translate(text: str, from_lang: str, to_lang: str) -> str | None:
    """Google Translate — tries the translate-pa JSON API first, falls back to async HTML scrape."""
    # Normalise language codes for Google (e.g. "zh" → "zh-CN")
    _GL = {"zh": "zh-CN", "zh-tw": "zh-TW"}
    g_to = _GL.get(to_lang.lower(), to_lang)
    g_from = _GL.get(from_lang.lower(), from_lang) if from_lang not in ("auto", "") else "auto"

    result = _google_pa(text, g_from, g_to)
    if result is not None:
        return result
    # Fallback: async HTML scrape
    return _google_async(text, g_from, g_to)


def _google_pa(text: str, from_lang: str, to_lang: str) -> str | None:
    """translate-pa.googleapis.com — JSON+protobuf payload, returns structured JSON."""
    payload = json.dumps([
        [[text], from_lang, to_lang],
        "wt_lib",
    ]).encode()
    req = urllib.request.Request(
        _GT_PA_URL,
        data=payload,
        headers={
            "Content-Type": "application/json+protobuf",
            "X-Goog-Api-Key": _GT_PA_KEY,
            "User-Agent": _GT_UA,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310
            body = json.loads(resp.read())
        # Response shape: [[translated_text, ...], [detected_lang, ...]]
        if isinstance(body, list) and len(body) >= 1 and body[0]:
            return body[0][0]
    except Exception as exc:  # noqa: BLE001
        logger.debug("Google PA API failed: %s", exc)
    return None


def _google_async(text: str, from_lang: str, to_lang: str) -> str | None:
    """Fallback: Google async HTML translate endpoint, parsed with regex."""
    async_val = (
        f"sl:{from_lang},tl:{to_lang},st:{urllib.parse.quote(text)},"
        f"id:{int(time.time() * 1000)},qc:true,ac:true,"
        "_id:tw-async-translate,_pms:s,_fmt:pc"
    )
    params = urllib.parse.urlencode({"async": async_val})
    req = urllib.request.Request(
        _GT_ASYNC_BASE + params,
        headers={
            "Accept-Charset": "utf-8",
            "User-Agent": _GT_UA,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            body = resp.read().decode("utf-8", errors="replace")
        m = _GT_TEXT_RE.search(body)
        return m.group(1) if m else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("Google async scrape failed: %s", exc)
    return None
