import requests
import config

GRAPH_URL = "https://graph.facebook.com/v19.0"


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"}


def send_text(to: str, text: str) -> bool:
    url = f"{GRAPH_URL}/{config.WHATSAPP_PHONE_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    r = requests.post(url, json=payload, headers={**_headers(), "Content-Type": "application/json"})
    if not r.ok:
        print(f"[WA] Error enviando a {to}: {r.status_code} {r.text[:200]}")
    return r.ok


def send_messages(to: str, texts: list) -> None:
    for text in texts:
        send_text(to, text)


def get_media_url(media_id: str) -> str:
    r = requests.get(f"{GRAPH_URL}/{media_id}", headers=_headers())
    r.raise_for_status()
    return r.json()["url"]


def download_media(media_id: str) -> bytes:
    url = get_media_url(media_id)
    r = requests.get(url, headers=_headers())
    r.raise_for_status()
    return r.content
