import json
import os

CFG = "config.json"
DEF = {
    "language": "RU",
    "download_path": os.path.join(os.getcwd(), "Video")
}

def load_config():
    if not os.path.exists(CFG):
        save_config(DEF)
        return DEF
    try:
        with open(CFG, "r", encoding="utf-8") as f:
            c = json.load(f)
            for k, v in DEF.items():
                if k not in c: c[k] = v
            return c
    except: return DEF

def save_config(c):
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=4, ensure_ascii=False)

def get_setting(k):
    return load_config().get(k)

def update_setting(k, v):
    c = load_config()
    c[k] = v
    save_config(c)

if not os.path.exists(DEF["download_path"]):
    os.makedirs(DEF["download_path"], exist_ok=True)
