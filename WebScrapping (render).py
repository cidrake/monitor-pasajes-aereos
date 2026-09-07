import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import re
import asyncio
import requests
import urllib.request
import feedparser
import urllib3
import time
import re
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

DOMESTIC_DESTINATION_PATTERNS = [
    r"\bbariloche\b", r"\bsalta\b", r"\biguazu\b", r"\biguazú\b", r"\bushuaia\b", r"\bcalafate\b", 
    r"\btucuman\b", r"\btucumán\b", r"\bneuquen\b", r"\bneuquén\b", r"\bjujuy\b", r"\bsan\s+juan\b", 
    r"\bposadas\b", r"\bbahia\s+blanca\b", r"\bbahía\s+blanca\b", r"\bcomodoro\s+rivadavia\b", 
    r"\btrelew\b", r"\bpuerto\s+madryn\b", r"\bmendoza\b", r"\bcordoba\b", r"\bcórdoba\b", 
    r"\bcabotaje\b", r"\bnacionales\b"
]

seen_urls = set()

def is_relevant_deal(text: str) -> bool:
    text_lower = text.lower()
    
    # 1. Regla de "Error Fare" o "Glitch" (Acepta si encuentra cualquier destino internacional o nacional)
    has_any_destination = any(re.search(p, text_lower) for p in DESTINATION_PATTERNS + DOMESTIC_DESTINATION_PATTERNS)
    if re.search(r"\berror\s*fare\b|\bglitch\b", text_lower) and has_any_destination:
        return True

    # 2. Búsqueda de patrones generales
    has_deal_keyword = any(re.search(p, text_lower) for p in DEAL_PATTERNS)
    has_origin = any(re.search(p, text_lower) for p in ORIGIN_PATTERNS)
    has_intl_destination = any(re.search(p, text_lower) for p in DESTINATION_PATTERNS)
    
    # 3. Validación de Vuelos Internacionales (Origen Arg + Destino Intl + Keyword)
    is_intl_deal = has_deal_keyword and has_origin and has_intl_destination

    # 4. Validación de Vuelos Nacionales / Cabotaje (Origen Arg + Destino Nacional, o frase explícita de cabotaje)
    has_domestic_destination = any(re.search(p, text_lower) for p in DOMESTIC_DESTINATION_PATTERNS)
    is_domestic_deal = (has_origin and has_domestic_destination) or re.search(r"\bvuelos?\s+por\s+argentina\b|\bcabotaje\b", text_lower)

    return is_intl_deal or is_domestic_deal

def send_telegram_alert(title: str, url: str = "", source: str = "Sistema", price: str = None, retries: int = 3):
    # Formatear la línea de precio si está presente
    price_line = f"💰 Precio: {price}\n" if price else ""
    url_line = f"🔗 Enlace: {url}\n" if url else ""
    
    message = (
        f"🚨 ¡OFERTA / ALERTA DETECTADA! 🚨\n\n"
        f"📌 Fuente: {source}\n"
        f"✈️ Detalle: {title}\n"
        f"{price_line}"
        f"{url_line}"
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
# 1. MONITOREO RSS (FlyerTalk, HolidayPirates, Promociones Aéreas)
# -------------------------------------------------------------------
def fetch_rss_feeds_sync():
    rss_sources = {
        # Fuentes Internacionales
        "FlyerTalk Mileage Run": "https://www.flyertalk.com/forum/external.php?type=rss2&forumids=372",
        "HolidayPirates UK": "https://www.holidaypirates.com/feed",

        # Fuentes Locales (Argentina y Cabotaje)
        "Promociones Aéreas": "https://promociones-aereas.com.ar/feed",
        "Sir Chandler": "https://www.sirchandler.com.ar/feed/",
        "Ratamundo": "https://ratamundo.com/feed/",
        "Infoviajera": "https://www.infoviajera.com/feed/",
    }

    print("[+] Escaneando Feeds RSS...")
    for source, url in rss_sources.items():
        try:
            feed = feedparser.parse(url)
            print(f"   -> Revisando: {feed.feed.get('title', source)} ({len(feed.entries)} entradas)")
            
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
# 2. SCRAPING PLAYWRIGHT (Secret Flying, Turismocity, Going)
# -------------------------------------------------------------------
def extract_price(text):
    """Busca patrones de moneda e importes en el texto."""
    match = re.search(r'(\$|USD|EUR|€|ARS)\s?\d+([.,]\d+)?|\d+\s?(USD|EUR|€|ARS)', text, re.IGNORECASE)
    return match.group(0) if match else "Precio no especificado"

async def fetch_playwright_sites():
    sitios = [
        {"nombre": "Secret Flying (Euro)", "url": "https://www.secretflying.com/euro-deals/"},
        {"nombre": "Secret Flying (Asia)", "url": "https://www.secretflying.com/asia-deals/"},
        {"nombre": "Turismocity Blog", "url": "https://www.turismocity.com.ar/blog/"}
    ]
    
    print("[+] Escaneando sitios dinámicos vía Playwright...", flush=True)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                ignore_https_errors=True,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            
            for sitio in sitios:
                page = await context.new_page()
                try:
                    await page.route("**/*", lambda route: route.abort() 
                        if route.request.resource_type in ["image", "font", "media"] 
                        else route.continue_())
                    
                    await page.goto(sitio["url"], wait_until="domcontentloaded", timeout=8000)
                    
                    # Seleccionamos el contenedor padre (artículo/tarjeta)
                    cards = await page.query_selector_all(
                        "article, .post, .card, .entry-preview, "
                        ".blog-post, .post-item, .entry, "              # Específicos de blogs en español
                        "h2.entry-title, h3.entry-title, h2 a, h3 a"    # Fallback directo a títulos
                    )
                    
                    cards = cards[:10]  # Procesar hasta 10 entradas por sitio
                    
                    encontrados = 0
                    urls_procesadas = set()
                    
                    for card in cards:
                        # Extraer el enlace dentro de la tarjeta
                        link_elem = await card.query_selector("a[href]")
                        if not link_elem:
                            continue
                            
                        href = await link_elem.get_attribute("href")
                        card_text = await card.inner_text()
                        card_text_clean = " ".join(card_text.split())
                        
                        if href and len(card_text_clean) > 10 and href not in urls_procesadas:
                            urls_procesadas.add(href)
                            encontrados += 1
                            
                            # Extraer precio del texto completo de la tarjeta
                            precio = extract_price(card_text_clean)
                            
                            # Imprimir en consola cada entrada encontrada con su precio
                            print(f"   -> [{sitio['nombre']}] Encontrado: {card_text_clean[:40]}... | Precio: {precio}", flush=True)
                            
                            if href not in seen_urls and is_relevant_deal(card_text_clean):
                                seen_urls.add(href)
                                alert_msg = f"{card_text_clean[:100]}...\n💰 Precio detectado: {precio}"
                                send_telegram_alert(alert_msg, href, sitio["nombre"])
                                
                    print(f"   -> [Playwright] {sitio['nombre']}: {encontrados} entradas procesadas.", flush=True)
                except Exception as e:
                    print(f"   -> [Playwright] Timeout/Error en {sitio['nombre']}. Saltando...", flush=True)
                finally:
                    await page.close()
        finally:
            await browser.close()
        
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

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

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
    print("🚀 Monitor de Error Fares activado (Origen: Sudamérica | Destino: Europa / Asia)...", flush=True)
    
    ciclo = 1
    while True:
        timestamp = time.strftime("%H:%M:%S")
        print(f"\n==================== CICLO #{ciclo} [{timestamp}] ====================", flush=True)
        
        # 1. Escaneo RSS
        try:
            await asyncio.to_thread(fetch_rss_feeds_sync)
        except Exception as e:
            print(f"[!] Error en tarea RSS: {e}", flush=True)
            
        # 2. Escaneo Secret Flying y Turismocity vía Playwright (máximo 120s)
        try:
            await asyncio.wait_for(fetch_playwright_sites(), timeout=120.0)
        except asyncio.TimeoutError:
            print("[!] Timeout en sitios Playwright (excedió 120s). Saltando...", flush=True)
        except Exception as e:
            print(f"[!] Error en tarea Playwright sitios: {e}", flush=True)

        # 3. Escaneo Going (máximo 45s)
        try:
            await asyncio.wait_for(fetch_going_headless(), timeout=45.0)
        except asyncio.TimeoutError:
            print("[!] Timeout en Going (excedió 45s). Saltando...", flush=True)
        except Exception as e:
            print(f"[!] Error en tarea Going: {e}", flush=True)
            
        print(f"[⏳] Ciclo #{ciclo} finalizado. Esperando 5 minutos para el próximo escaneo...", flush=True)
        ciclo += 1

        # Al terminar todas las tareas del ciclo:
        try:
            mensaje_ping = f"✅ Ciclo #{ciclo} finalizado correctamente a las {timestamp}. Bot activo."
            send_telegram_alert(title=mensaje_ping, url="https://render.com", source="Monitor Render")
        except Exception as e:
            print(f"[!] Error al enviar heartbeat a Telegram: {e}", flush=True)
    
        # Pausa de 5 minutos
        await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(main())
