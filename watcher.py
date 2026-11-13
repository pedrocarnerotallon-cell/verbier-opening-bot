"""
Vigila las plazas de la Opening Session de Verbier (forfait a CHF 5 yendo de San Nicolás)
y manda una notificación al móvil (ntfy) en cuanto haya plazas libres.

Usa el mismo dato que carga la web al pulsar "Book now":
  /en/shop/product/available-dates-times?activity_id=...
  -> {"availabilityByDate": {"426820-2026-12-05": {"available": 0, "max": 112, ...}}}
"""
import json
import os
import re
import sys
import time
import urllib.request

PRODUCTS = {
    "426820": ("con tren", "https://verbier4vallees.ch/en/online-shop/activities/opening-session-st.nicholas-express_activity_426820"),
    "410650": ("sin tren", "https://verbier4vallees.ch/en/online-shop/activities/opening-session_activity_410650"),
}
API = "https://verbier4vallees.ch/en/shop/product/available-dates-times?activity_id={}"
SHOP_LIST = "https://verbier4vallees.ch/en/online-shop/activities"

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
INTERVAL = int(os.environ.get("INTERVAL_SECONDS", "30"))
RUN_FOR = int(os.environ.get("RUN_FOR_SECONDS", str(5 * 3600 + 45 * 60)))
ONCE = os.environ.get("ONCE") == "1"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def fetch(url, referer=None):
    headers = {"User-Agent": UA, "Accept-Language": "en", "X-Requested-With": "XMLHttpRequest",
               "Accept": "application/json, text/javascript, */*; q=0.01"}
    if referer:
        headers["Referer"] = referer
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")


def availability(pid):
    """Devuelve {fecha: (disponibles, max)}"""
    data = json.loads(fetch(API.format(pid), PRODUCTS[pid][1]))
    out = {}
    for v in (data.get("availabilityByDate") or {}).values():
        out[v.get("date")] = (int(v.get("available") or 0), int(v.get("max") or 0))
    return out


def opening_products(raw):
    urls = re.findall(r'href="([^"]*_activity_(\d+))"', raw)
    return {pid for u, pid in urls if re.search(r"opening|nichol|nicolas|samichlaus", u, re.I)}


def nice(d):
    try:
        y, m, dd = d.split("-")
        return f"{int(dd)}/{int(m)}"
    except Exception:
        return d


def notify(title, msg, url=None, urgent=False):
    print(f"[NOTIFY] {title}: {msg}", flush=True)
    if TG_TOKEN and TG_CHAT:
        try:
            text = f"{title}\n{msg}" + (f"\n{url}" if url else "")
            body = json.dumps({"chat_id": TG_CHAT, "text": text, "disable_web_page_preview": True}).encode()
            urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data=body,
                                   headers={"Content-Type": "application/json"}), timeout=20)
        except Exception as e:
            print("telegram error:", e, flush=True)
    if not NTFY_TOPIC:
        return
    headers = {"Title": title.encode("utf-8"), "Priority": "urgent" if urgent else "default",
               "Tags": "rotating_light" if urgent else "information_source"}
    if url:
        headers["Click"] = url
    try:
        urllib.request.urlopen(urllib.request.Request(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"), headers=headers), timeout=20)
    except Exception as e:
        print("ntfy error:", e, flush=True)


def main():
    if os.environ.get("TEST_NOTIFY") == "1":
        notify("Bot Verbier activo ✅", "Si ves esto, las notificaciones funcionan.")

    prev = {}            # (pid, fecha) -> disponibles
    repeats = {}
    prev_max = {}        # (pid, fecha) -> plazas totales
    prev_max = {}        # (pid, fecha) -> total de plazas
    known_pids = set(PRODUCTS)
    fails = 0
    loops = 0
    start = time.time()
    report = []

    while True:
        try:
            for pid, (name, url) in list(PRODUCTS.items()):
                av = availability(pid)
                for date, (free, mx) in av.items():
                    key = (pid, date)
                    old = prev.get(key)
                    line = f"{time.strftime('%H:%M:%S')} {name} {date}: {free}/{mx} libres"
                    print(line, flush=True)
                    report.append(line)
                    if free > 0:
                        repeats[key] = repeats.get(key, 0) + 1
                    else:
                        repeats[key] = 0
                    if free > 0 and repeats[key] <= 6:  # repite el aviso unas veces mientras queden plazas
                        notify(f"🎅 ¡HAY PLAZAS! {nice(date)} · {name}", f"{free} plazas libres de {mx}. ¡Corre a reservar!", url, True)
                    elif old is None and date not in ("2026-12-05",):
                        notify(f"📅 Nueva fecha: {nice(date)} · {name}", f"{free}/{mx} plazas.", url, True)
                    # prev_max guarda el máximo visto; los +1/-1 sueltos son cancelaciones, no tandas
                    old_max = prev_max.get(key)
                    if old_max is not None and mx - old_max >= 5 and free == 0:
                        notify(f"⏱️ Salió una tanda y ya se agotó · {name}", f"+{mx - old_max} plazas a las {time.strftime('%H:%M')}. Ya no quedan.", url)
                    prev[key] = free
                    if old_max is None or mx - old_max >= 5:
                        prev_max[key] = mx

            if loops % 10 == 0:  # la lista de productos, cada ~10 min
                new = opening_products(fetch(SHOP_LIST)) - known_pids
                for pid in new:
                    known_pids.add(pid)
                    u = f"https://verbier4vallees.ch/en/online-shop/activities/x_activity_{pid}"
                    notify("🆕 Nuevo producto Opening Session", f"activity {pid}", None, True)
                    PRODUCTS[pid] = (f"nuevo {pid}", u)
            fails = 0
        except Exception as e:
            fails += 1
            print("Error:", repr(e), flush=True)
            report.append(f"Error: {e!r}")
            if fails == 5:
                notify("⚠️ Bot Verbier: errores", f"No consigo leer la disponibilidad ({e}). Sigo intentándolo.")

        loops += 1
        if ONCE:
            open("once_report.txt", "w").write("\n".join(report))
            break
        if time.time() - start + INTERVAL > RUN_FOR:
            break
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
