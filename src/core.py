import re
import os
import sys
import time
import random
import yt_dlp
from playwright.sync_api import sync_playwright
from colorama import Fore, Style, init
from .config import get_setting
from .locale import get_text

init(autoreset=True)

def log(msg, color=Fore.WHITE):
    t = time.strftime("[%H:%M:%S]")
    print(f"{Fore.CYAN}{t} {color}{msg}{Style.RESET_ALL}")

def get_target_url(raw_url):
    url = raw_url.strip()
    if 'src="' in url:
        m = re.search(r'src="([^"]+)"', url)
        if m: url = m.group(1)
    
    if url.startswith("//"):
        url = "https:" + url
    
    return url if url.startswith("http") else None

def download_video(raw_url):
    lang = get_setting("language")
    path = get_setting("download_path")
    
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)

    target = get_target_url(raw_url)
    if not target:
        log(get_text(lang, 'invalid_url'), Fore.RED)
        return

    log(get_text(lang, 'status_browser_launch'), Fore.YELLOW)
    streams = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
        origin = "https://yummyani.me/" 
        
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            extra_http_headers={'Referer': origin, 'Origin': origin}
        )
        page = ctx.new_page()

        def on_req(req):
            u = req.url
            if ".m3u8" in u and "trash" not in u:
                if u not in streams:
                    log(get_text(lang, 'status_found').format(u.split('/')[-1].split('?')[0]), Fore.GREEN)
                    streams.append(u)

        page.on("request", on_req)

        try:
            log(get_text(lang, 'status_searching'), Fore.YELLOW)
            html = f'<html><head><base href="{origin}"></head><body style="background:black;"><iframe src="{target}" width="100%" height="100%" frameborder="0"></iframe></body></html>'
            page.set_content(html)
            
            start = time.time()
            while time.time() - start < 10:
                try: page.mouse.click(640, 360)
                except: pass
                time.sleep(2)
        except: pass
        browser.close()

    if not streams:
        log(get_text(lang, 'error_no_links'), Fore.RED)
        return

    print(f"\n{Fore.CYAN}--- {get_text(lang, 'menu_quality_select')} ---")
    
    q_map = {}
    for s in streams:
        res = "Unknown"
        if "1080" in s: res = "1080p (Full HD)"
        elif "720" in s: res = "720p (HD)"
        elif "480" in s: res = "480p (SD)"
        elif "360" in s: res = "360p (Low)"
        
        if res not in q_map or len(s) < len(q_map[res]):
            q_map[res] = s

    if "720p (HD)" not in q_map:
        for r in ["360p (Low)", "480p (SD)"]:
            if r in q_map:
                upd = q_map[r].replace("360.mp4", "720.mp4").replace("480.mp4", "720.mp4")
                if upd != q_map[r]:
                    q_map["720p (HD) [FORCE]"] = upd
                    break

    opts = list(q_map.keys())
    for i, o in enumerate(opts, 1):
        print(f"{i}. {o}")
    
    try:
        idx = int(input(Fore.YELLOW + get_text(lang, 'input_prompt')).strip()) - 1
        final = q_map[opts[idx]] if 0 <= idx < len(opts) else streams[-1]
    except:
        final = streams[-1]

    log(get_text(lang, 'status_downloading'), Fore.GREEN)
    fname = f"Kodik_{''.join([str(random.randint(0, 9)) for _ in range(10)])}"

    y_opts = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': os.path.join(path, f'{fname}.%(ext)s'),
        'concurrent_fragment_downloads': 10,
        'http_headers': {
            'Referer': 'https://kodik.info/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        },
        'nocheckcertificate': True,
        'quiet': False,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(y_opts) as ydl:
            ydl.download([final])
        log(get_text(lang, 'status_done').format(path), Fore.GREEN)
    except KeyboardInterrupt:
        log("\nAborted.", Fore.YELLOW)
        time.sleep(2)
        if os.path.exists(path):
            for f in os.listdir(path):
                if f.startswith(fname):
                    try: os.remove(os.path.join(path, f))
                    except: pass
    except Exception as e:
        log(get_text(lang, 'error_download').format(e), Fore.RED)
