import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from core.pak_handler import list_files, extract_file
from core import locres as locres_mod
from collections import defaultdict

pak = r'C:\Users\markk\OneDrive\Desktop\claude workspace\Example\Wandering_Sword\Content\Paks\Maimaomaiplae_p.pak'
files = list_files(pak)
locres_files = [f for f in files if f.endswith('.locres')]

LANGS = {'en', 'zh-Hans', 'zh-Hant', 'zh-CN', 'th', 'ja', 'ko', 'fr', 'de', 'ru'}

by_lang = defaultdict(list)
for f in locres_files:
    segs = f.replace('\\', '/').split('/')
    for s in segs:
        if s in LANGS:
            by_lang[s].append(f)
            break

print('=== Languages in pak ===')
for lang, lst in sorted(by_lang.items()):
    print(f'  [{lang}] {len(lst)} files')
    for f in lst[:2]:
        print(f'      {f}')

print()
print('=== Game locres (non-Engine) content ===')
for fpath in sorted(locres_files):
    if 'Engine/' in fpath:
        continue
    try:
        raw = extract_file(pak, fpath)
        if not raw:
            continue
        lf = locres_mod.load(raw)
        d  = locres_mod.to_dict(lf)
        total = sum(len(v) for v in d.values())
        segs  = fpath.replace('\\', '/').split('/')
        lang  = [s for s in segs if s in LANGS]
        lang  = lang[0] if lang else '?'
        name  = segs[-1]
        sample = ''
        for ns, keys in d.items():
            for k, v in keys.items():
                if v and not v.startswith('('):
                    sample = v[:50]
                    break
            if sample:
                break
        print(f'  [{lang}] {name}: {total} strings  | {repr(sample)}')
    except Exception:
        pass
