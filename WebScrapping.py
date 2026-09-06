import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import re
import asyncio
import requests
import feedparser
import urllib3
import time
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# Desactivar advertencias SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# -------------------------------------------------------------------
# CONFIGURACIÓN DE TELEGRAM
# -------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = "8913372178:AAGHVEh8g9AnNvvC-UAwrYmFVvOWH9maL0k"  # Reemplazar con tu Token completo
TELEGRAM_CHAT_ID = "383871975"            # Tu Chat ID verificado

# -------------------------------------------------------------------
# MATRIZ DE FILTRADO (SUDAMÉRICA -> EUROPA / ASIA)
# -------------------------------------------------------------------
ORIGIN_PATTERNS = [
    r"\bbuenos\s*aires\b", r"\bezeiza\b", r"\beze\b", r"\bard\b",
    r"\bargentina\b", r"\bsouth\s*america\b", r"\bsudamerica\b",
    r"\bsao\s*paulo\b", r"\bgru\b", r"\bsantiago\b", r"\bscl\b", 
    r"\bbogota\b", r"\bbog\b", r"\blima\b", r"\blim\b", r"\brio\b"
]

DESTINATION_PATTERNS = [
    # Europa
    r"\beurope\b", r"\beuropa\b", r"\bmadrid\b", r"\bmad\b", r"\bbarcelona\b", r"\bbcn\b",
    r"\blondon\b", r"\blhr\b", r"\blgw\b", r"\bparis\b", r"\bcdg\b", r"\brome\b", r"\bfco\b",
    r"\bamsterdam\b", r"\bams\b", r"\bfrankfurt\b", r"\bfra\b", r"\bmilan\b", r"\bmxp\b",
    r"\blisbon\b", r"\blis\b", r"\bzurich\b", r"\bzrh\b", r"\bberlin\b", r"\bprague\b",
    # Asia
    r"\basia\b", r"\btokyo\b", r"\bhnd\b", r"\bnrt\b", r"\bjapon\b", r"\bjapan\b",
    r"\bbangkok\b", r"\bbkk\b", r"\bthailand\b", r"\btailandia\b", r"\bseoul\b", r"\bicn\b",
    r"\bkorea\b", r"\bbali\b", r"\bdps\b", r"\bindonesia\b", r"\bsingapore\b", r"\bsin\b",
    r"\bbeijing\b", r"\bshanghai\b", r"\bpek\b", r"\bpvg\b", r"\bchina\b", r"\bhong\s*kong\b",
    r"\bhkg\b", r"\bvietnam\b", r"\bhanoi\b", r"\bsgn\b", r"\bdelhi\b", r"\bdel\b", r"\bindia\b"
]

DEAL_PATTERNS = [
    r"\berror\s*fare\b", r"\bglitch\b", r"\bmisprice\b", r"\bcheap\b", 
    r"\bbusiness\s*class\b", r"\bfirst\s*class\b", r"\b0\s*usd\b", 
    r"\b90%\b", r"\b80%\b", r"\b70%\b", r"\bhacked\b", r"\boferta\b", r"\bimperdible\b"
]

seen_urls = set()

def is_relevant_deal(text: str) -> bool:
    text_lower = text.lower()
    has_deal_keyword = any(re.search(p, text_lower) for p in DEAL_PATTERNS)
    has_origin = any(re.search(p, text_lower) for p in ORIGIN_PATTERNS)
    has_destination = any(re.search(p, text_lower) for p in DESTINATION_PATTERNS)
    
    if re.search(r"\berror\s*fare\b|\bglitch\b", text_lower) and has_destination:
        return True
        
    return has_deal_keyword and has_origin and has_destination

def send_telegram_alert(title: str, url: str, source: str, retries: int = 3):
    message = (
        f"🚨 ¡OFERTA / ERROR FARE DETECTADA! 🚨\n\n"
        f"📌 Fuente: {source}\n"
        f"✈️ Detalle: {title}\n\n"
        f"🔗 Enlace: {url}"
    )
    
    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": False
    }
    
    for attempt in range(1, retries + 1):
        try:
            res = requests.post(telegram_url, json=payload, timeout=10)
            if res.status_code == 200:
                print(f"[+] Alerta enviada con éxito a Telegram desde {source}")
                return
            else:
                print(f"[!] Telegram respondió con código {res.status_code}")
                break
        except requests.exceptions.RequestException:
            if attempt < retries:
                time.sleep(2)
            else:
                print(f"[!] Error de conexión con Telegram tras {retries} intentos.")

# -------------------------------------------------------------------
# 1. MONITOREO RSS (Secret Flying, Promociones Aéreas, Turismocity)
# -------------------------------------------------------------------
def fetch_rss_feeds_sync():
    rss_sources = {
        "Secret Flying (General)": "https://www.secretflying.com/feed/",
        "Secret Flying (Europa)": "https://www.secretflying.com/euro-deals/feed/",
        "Secret Flying (Asia)": "https://www.secretflying.com/asia-deals/feed/",
        "FlyerTalk Mileage Run": "https://www.flyertalk.com/forum/external.php?type=rss2&forumids=372",
        "HolidayPirates UK": "https://www.holidaypirates.com/feed",
        "Promociones Aéreas AR": "https://www.promociones-aereas.com.ar/feed",
        "Turismocity Blog AR": "https://www.turismocity.com.ar/blog/feed"
    }

    print("[+] Escaneando Feeds RSS...")
    for source, url in rss_sources.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:
                link = entry.link
                title = entry.title
                
                if link not in seen_urls:
                    if is_relevant_deal(title):
                        seen_urls.add(link)
                        send_telegram_alert(title, link, source)
        except Exception as e:
            print(f"[!] Error leyendo RSS {source}: {e}")

# -------------------------------------------------------------------
# 2. SCRAPING GOING (PLAYWRIGHT)
# -------------------------------------------------------------------
async def fetch_going_headless():
    url = "https://www.going.com/deals"
    print("[+] Escaneando Going vía Playwright...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(ignore_https_errors=True)
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=10000)
            elements = await page.query_selector_all("a")
            
            for elem in elements:
                text = await elem.inner_text()
                href = await elem.get_attribute("href")
                if href and text and is_relevant_deal(text):
                    full_link = href if href.startswith("http") else f"https://www.going.com{href}"
                    if full_link not in seen_urls:
                        seen_urls.add(full_link)
                        send_telegram_alert(text.strip(), full_link, "Going")
        except Exception:
            print("[!] Going no disponible o inaccesible en este ciclo.")
        finally:
            await browser.close()

# Servidor HTTP ficticio para mantener feliz a Render
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK - Monitor Activo")

def run_health_check_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# Iniciar el servidor en un hilo secundario
threading.Thread(target=run_health_check_server, daemon=True).start()

# -------------------------------------------------------------------
# BUCLE PRINCIPAL (5 MINUTOS)
# -------------------------------------------------------------------
async def main():
    print("🚀 Monitor de Error Fares activado (Origen: Sudamérica | Destino: Europa / Asia)...")
    
    ciclo = 1
    while True:
        timestamp = time.strftime("%H:%M:%S")
        print(f"\n==================== CICLO #{ciclo} [{timestamp}] ====================")
        
        # 1. Escaneo RSS
        try:
            await asyncio.to_thread(fetch_rss_feeds_sync)
        except Exception as e:
            print(f"[!] Error en tarea RSS: {e}")
            
        # 2. Escaneo Going (máximo 15 segundos)
        try:
            await asyncio.wait_for(fetch_going_headless(), timeout=15.0)
        except asyncio.TimeoutError:
            print("[!] Timeout en Going (excedió 15s). Saltando...")
        except Exception as e:
            print(f"[!] Error en tarea Going: {e}")
            
        print(f"[⏳] Ciclo #{ciclo} finalizado. Esperando 5 minutos para el próximo escaneo...")
        ciclo += 1
        
        # Pausa exacta de 5 minutos (1800 segundos)
        await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(main())
