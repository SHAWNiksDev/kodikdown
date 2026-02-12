import os
import sys
import time
import tkinter as tk
from tkinter import filedialog
from colorama import Fore, Style, init
from .locale import get_text
from .config import get_setting, update_setting
from .core import download_video

init(autoreset=True)

def cls():
    os.system('cls' if os.name == 'nt' else 'clear')

def pick_folder():
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    path = filedialog.askdirectory()
    root.destroy()
    return path

def header():
    l = get_setting("language")
    print(Fore.MAGENTA + "=" * 50)
    print(Fore.MAGENTA + "   " + get_text(l, 'menu_main_title'))
    print(Fore.MAGENTA + "=" * 50 + Style.RESET_ALL)

def settings():
    while True:
        cls()
        l = get_setting("language")
        cp = get_setting("download_path")
        
        print(Fore.CYAN + f"--- {get_text(l, 'settings_title')} ---")
        print(f"1. {get_text(l, 'settings_change_path').format(cp)}")
        print(f"2. {get_text(l, 'settings_change_lang').format(l)}")
        print(f"0. {get_text(l, 'settings_back')}")
        
        c = input(Fore.YELLOW + get_text(l, 'input_prompt')).strip()
        
        if c == '1':
            np = pick_folder()
            if np: update_setting("download_path", np)
        elif c == '2':
            langs = ['RU', 'EN', 'UK']
            nxt = langs[(langs.index(l) + 1) % 3] if l in langs else 'RU'
            update_setting("language", nxt)
        elif c == '0': break

def main():
    while True:
        try:
            cls()
            header()
            l = get_setting("language")
            
            print(f"1. {get_text(l, 'menu_enter_url')}")
            print(f"2. {get_text(l, 'menu_options')}")
            print(f"0. {get_text(l, 'menu_exit')}")
            
            c = input(Fore.YELLOW + get_text(l, 'input_prompt')).strip()
            
            if c == '1':
                u = input(Fore.GREEN + "URL: ").strip()
                if u:
                    download_video(u)
                    print(Fore.YELLOW + "\nDone. Enter to continue...")
                    input()
            elif c == '2': settings()
            elif c == '0':
                time.sleep(0.5)
                sys.exit()
        except KeyboardInterrupt:
            time.sleep(0.5)
            sys.exit()

if __name__ == "__main__":
    main()
