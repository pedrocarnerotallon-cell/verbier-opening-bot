"""
Vigila las entradas de la Opening Session de Verbier (forfait a CHF 5 yendo de San Nicolás)
y manda una notificación al móvil (ntfy) cuando cambie algo.

Avisa cuando:
  - Una de las páginas deja de mostrar el aviso de "agotado"  -> ¡posibles entradas!
  - Cambia el texto de disponibilidad (p. ej. nueva tanda que se agota)
  - Aparece la fecha 6 de diciembre en alguna página
  - Aparece un producto nuevo de "Opening / St. Nicholas" en la tienda
"""
import hashlib
import html
import os
import re
import sys
import time
import urllib.request

PAGES = {
    "5 dic · con tren": "https://verbier4vallees.ch/en/online-shop/activities/opening-session-st.nicholas-express_activity_426820",
    "5 dic · sin tren": "https://verbier4vallees.ch/en/online-shop/activities/opening-session_activity_410650",
}
SHOP_LIST = "https://verbier4vallees.ch/en/online-shop/activities"

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
INTERVAL = int(os.environ.get("INTERVAL_SECONDS", "120"))      # cada cuánto revisa
RUN_FOR = int(os.environ.get("RUN_FOR_SECONDS", str(5 * 3600 + 45 * 60)))  # cuánto dura cada ejecución

SOLD_OUT = [
    "quota has been sold out",
    "tickets for this event are sold out",
    "are sold out",
    "currently not bookable",
    "not bookable",
]
DAY6 = re.compile(r"0?6\.12\.(20)?26|6(th)? december 2026|december 6(th)?,? 2026|06/12/(20)?26")
STATUS_WORDS = re.compile(r"sold out|not bookable|quota", re.I)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def to_text(raw):
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", "\n", raw)
    lines = [re.sub(r"\s+", " ", html.unescape(l)).strip() for l in raw.split("\n")]
    return [l for l in lines if l]


def analyse(raw):
    lines = to_text(raw)
    low = " ".join(lines).lower()
    status = [l for l in lines if STATUS_WORDS.search(l) and len(l) < 200]
    return {
        "sold_out": any(p in low for p in SOLD_OUT),
        "status": " | ".join(dict.fromkeys(status)),
        "day6": bool(DAY6.search(low)),
    }


def opening_products(raw):
    urls = re.findall(r'href="([^"]*_activity_\d+)"', raw)
    return {u for u in urls if re.search(r"opening|nichol|nicolas|samichlaus", u, re.I)}


def notify(title, msg, url=None, urgent=False):
    print(f"[NOTIFY] {title}: {msg}", flush=True)
    if not NTFY_TOPIC:
        return
    headers = {"Title": title.encode("utf-8"), "Priority": "urgent" if urgent else "default",
               "Tags": "rotating_light" if urgent else "information_source"}
    if url:
        headers["Click"] = url
    req = urllib.request.Request(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"), headers=headers)
    try:
        urllib.request.urlopen(req, timeout=20)
    except Exception as e:
        print("ntfy error:", e, flush=True)


def main():
    if os.environ.get("TEST_NOTIFY") == "1":
        notify("Bot Verbier activo ✅", "Si ves esto, las notificaciones funcionan.")

    prev = {}
    known_products = None
    fails = 0
    start = time.time()

    while True:
        try:
            for name, url in PAGES.items():
                cur = analyse(fetch(url))
                old = prev.get(name)
                if old is None:
                    if not cur["sold_out"]:
                        notify(f"🎅 ¡Entradas posibles! ({name})", "No aparece el aviso de agotado. ¡Entra ya!", url, True)
                else:
                    if old["sold_out"] and not cur["sold_out"]:
                        notify(f"🎅 ¡HAN SALIDO ENTRADAS! ({name})", "El aviso de agotado ha desaparecido. ¡Corre!", url, True)
                    elif cur["status"] != old["status"]:
                        notify(f"Sigue agotado · cambió el aviso ({name})", (cur["status"][:300] or "(sin aviso)") + "\nProbablemente ha salido y se ha agotado una tanda.", url)
                if cur["day6"] and not (old or {}).get("day6"):
                    notify(f"📅 Aparece el 6 de diciembre ({name})", "Revisa la página.", url, True)
                print(time.strftime("%H:%M:%S"), name, "AGOTADO" if cur["sold_out"] else "DISPONIBLE?", "|", cur["status"][:120], flush=True)
                prev[name] = cur

            products = opening_products(fetch(SHOP_LIST))
            if known_products is not None:
                for u in products - known_products:
                    full = u if u.startswith("http") else "https://verbier4vallees.ch" + u
                    notify("🆕 Nuevo producto Opening Session", full, full, True)
            known_products = products if known_products is None else known_products | products
            fails = 0
        except Exception as e:
            fails += 1
            print("Error:", e, flush=True)
            if fails == 5:
                notify("⚠️ Bot Verbier: errores", f"No consigo leer la web ({e}). Sigo intentándolo.")

        if time.time() - start + INTERVAL > RUN_FOR:
            break
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
