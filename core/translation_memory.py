"""
translation_memory.py — GameLang Translator
Speaker-aware + Conversation Pair + 22-method optimization
"""

import re, json, hashlib, os, asyncio, time
from dataclasses import dataclass, field
from typing import Optional
from difflib import SequenceMatcher

# ── Translation Rules ─────────────────────────────────────────────────────────
RULES = {
    "no_translate_types": [
        "character_name", "group_name", "organization",
        "place_name", "proper_noun", "game_title",
    ],
    "always_translate": [
        "verb", "adjective", "general_dialog", "ui", "description"
    ],
    "context_dependent": [
        "hunt", "empire", "elder", "master", "lord", "spirit"
    ],
}

# ── UI Patterns ───────────────────────────────────────────────────────────────
UI_PATTERNS = [
    r'^(ok|cancel|back|close|exit|yes|no|confirm|save|load|quit|resume)$',
    r'^(settings|options|menu|inventory|map|status|help|pause|equip|remove)$',
    r'^(level\s*up!?|game\s*over|you\s*(have\s*)?died\.?|new\s*game|continue)$',
    r'^\d+(\s*[/x]\s*\d+)?$', r'^\d+\s*%$', r'^\+?\-?\d+$',
    r'^\[.{1,20}\]$', r'^\(.{1,20}\)$', r'^[A-Za-z]+\s*:$',
]

# คำที่ต้องเช็ค context เสมอ ห้าม classify เป็น UI
CONTEXT_REQUIRED = {
    "master", "lord", "lady", "elder", "young", "attack",
    "defend", "skill", "run", "flee", "hunt", "spirit", "ghost",
}

# ── Speaker Registers ─────────────────────────────────────────────────────────
SPEAKER_REGISTER = {
    "formal":  {"self": "ข้า",   "other": "ท่าน",       "style": "archaic"},
    "polite":  {"self": "ผม",    "other": "คุณ",         "style": "polite"},
    "casual":  {"self": "เรา",   "other": "แก",          "style": "casual"},
    "neutral": {"self": "คุณ",   "other": "คุณ",         "style": "neutral"},
    "villain": {"self": "ข้า",   "other": "เจ้า",        "style": "threatening"},
    "reverent":{"self": "ข้า",   "other": "เจ้านาย",     "style": "reverent"},
    "mentor":  {"self": "",      "other": "เจ้า/ลูกศิษย์","style": "instructing"},
    "filial":  {"self": "หนู",   "other": "พ่อ/แม่",     "style": "filial"},
    "intimate":{"self": "เรา",   "other": "แก",          "style": "intimate"},
}

# ── Genre Templates ───────────────────────────────────────────────────────────
GENRE_TEMPLATES = {
    "wuxia": {
        "style": "วรรณกรรมจีนโบราณ ใช้ ข้า/ท่าน ศัพท์กำลังภายใน",
        "tone":  "กล้าหาญ มีเกียรติ โศกเศร้า",
        "forbidden_modern": True,
    },
    "slavic_fantasy": {
        "style": "แฟนตาซียุโรปตะวันออก มืด สมจริง",
        "tone":  "หนักแน่น มีอารมณ์ขัน เสียดสีบ้าง",
        "geralt_rule": "พูดน้อย สั้น ไม่เกิน 2 ประโยค",
    },
    "samurai": {
        "style": "วรรณกรรมซามูไร เกียรติยศ เสียสละ หน้าที่",
        "tone":  "หนักแน่น สงบ มีศักดิ์ศรี",
        "haiku_rule": "ใช้ Sonnet เท่านั้น ทีละบท",
    },
    "fantasy": {
        "style": "แฟนตาซียุโรป",
        "tone":  "มหากาพย์ ยิ่งใหญ่",
    },
    "scifi": {
        "style": "วิทยาศาสตร์ ทับศัพท์เทคนิค",
        "tone":  "ภาษากลาง เป็นทางการ",
    },
    "horror": {
        "style": "สยองขวัญ บรรยากาศหนัก",
        "tone":  "ภาษาหนักแน่น กดดัน",
    },
    "casual": {
        "style": "เกมสบายๆ",
        "tone":  "ภาษาพูดทั่วไป ไม่เป็นทางการ",
    },
}

# ── Offline Fallback Dictionary ───────────────────────────────────────────────
FALLBACK_DICT = {
    "attack": "โจมตี", "defense": "ป้องกัน", "health": "พลังชีวิต",
    "mana": "เวทย์มนต์", "stamina": "ความอดทน", "level": "เลเวล",
    "experience": "ประสบการณ์", "gold": "ทอง", "silver": "เงิน",
    "sword": "ดาบ", "shield": "โล่", "armor": "เกราะ", "bow": "ธนู",
    "enemy": "ศัตรู", "boss": "บอส", "quest": "ภารกิจ", "map": "แผนที่",
    "save": "บันทึก", "load": "โหลด", "exit": "ออก", "back": "ย้อนกลับ",
    "confirm": "ยืนยัน", "cancel": "ยกเลิก", "yes": "ใช่", "no": "ไม่",
    "inventory": "กระเป๋า", "equipment": "อุปกรณ์", "skill": "สกิล",
    "magic": "เวทย์", "fire": "ไฟ", "water": "น้ำ", "wind": "ลม",
    "earth": "ดิน", "light": "แสง", "dark": "มืด", "poison": "พิษ",
}


# ── Data Classes ──────────────────────────────────────────────────────────────
@dataclass
class MemoryEntry:
    original:   str
    translated: str
    speaker:    Optional[str]
    listener:   Optional[str]
    register:   str
    game_id:    str
    version:    str = "1.0"
    use_count:  int = 0
    confidence: float = 1.0


@dataclass
class ConversationPair:
    speaker:   str
    listener:  str
    register:  str
    pronoun_self:  str
    pronoun_other: str
    tone_note: str = ""


# ── Translation Memory ────────────────────────────────────────────────────────
class TranslationMemory:
    def __init__(self, game_id: str, memory_path: str, game_version: str = "1.0"):
        self.game_id      = game_id
        self.memory_path  = memory_path
        self.game_version = game_version
        self._ui:     dict[str, MemoryEntry] = {}        # key = fingerprint
        self._dialog: dict[tuple, MemoryEntry] = {}      # key = (fp, speaker, listener)
        self._cross:  dict[str, str] = {}                # cross-game UI cache
        self._load()

    # ── Fingerprint ───────────────────────────────────────────────────────────
    def _fp(self, text: str) -> str:
        return hashlib.md5(text.strip().lower().encode()).hexdigest()[:8]

    # ── UI ────────────────────────────────────────────────────────────────────
    def is_ui(self, text: str) -> bool:
        t = text.strip()
        if t.lower() in CONTEXT_REQUIRED:
            return False
        for p in UI_PATTERNS:
            if re.match(p, t, re.IGNORECASE):
                return True
        if len(t) <= 12 and ' ' not in t and not t[0].isupper():
            return True
        return False

    def lookup_ui(self, text: str) -> Optional[str]:
        key = self._fp(text)
        # ลอง cross-game ก่อน
        if key in self._cross:
            return self._cross[key]
        e = self._ui.get(key)
        if e and e.version == self.game_version:
            e.use_count += 1
            return e.translated
        return None

    def save_ui(self, original: str, translated: str, confidence: float = 1.0):
        key = self._fp(original)
        entry = MemoryEntry(original, translated, None, None, "neutral",
                            self.game_id, self.game_version,
                            confidence=confidence)
        self._ui[key] = entry
        # บันทึกลง cross-game ด้วย
        self._cross[key] = translated

    # ── Dialog ────────────────────────────────────────────────────────────────
    def lookup_dialog(self, text: str, speaker: Optional[str],
                      listener: Optional[str], register: str) -> Optional[str]:
        fp  = self._fp(text)
        spk = (speaker or "").lower()
        lst = (listener or "").lower()

        # ลองหา exact pair ก่อน
        key = (fp, spk, lst)
        e   = self._dialog.get(key)
        if e and e.version == self.game_version:
            e.use_count += 1
            return e.translated

        # fallback: same speaker ต่าง listener
        for k, v in self._dialog.items():
            if k[0] == fp and k[1] == spk and v.register == register \
               and v.version == self.game_version:
                return None  # มีแต่ต่าง pair → ส่ง API ใหม่

        # fallback: same register
        for k, v in self._dialog.items():
            if k[0] == fp and v.register == register \
               and v.confidence >= 0.9 \
               and v.version == self.game_version:
                return v.translated
        return None

    def save_dialog(self, original: str, translated: str,
                    speaker: Optional[str], listener: Optional[str],
                    register: str, confidence: float = 1.0):
        key = (self._fp(original), (speaker or "").lower(),
               (listener or "").lower())
        self._dialog[key] = MemoryEntry(
            original, translated, speaker, listener,
            register, self.game_id, self.game_version,
            confidence=confidence
        )

    # ── Persistence ───────────────────────────────────────────────────────────
    def save(self):
        os.makedirs(os.path.dirname(self.memory_path) or ".", exist_ok=True)
        data = {
            "game_id": self.game_id, "version": self.game_version,
            "ui": {k: {"o":v.original,"t":v.translated,"c":v.confidence}
                   for k,v in self._ui.items()},
            "dialog": {f"{k[0]}|{k[1]}|{k[2]}":
                       {"o":v.original,"t":v.translated,"s":v.speaker,
                        "l":v.listener,"r":v.register,"c":v.confidence}
                       for k,v in self._dialog.items()},
            "cross": self._cross,
        }
        with open(self.memory_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(',',':'))

    def _load(self):
        if not os.path.exists(self.memory_path):
            return
        try:
            with open(self.memory_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            saved_ver = data.get("version", "1.0")
            for k, v in data.get("ui", {}).items():
                if saved_ver == self.game_version:
                    self._ui[k] = MemoryEntry(
                        v["o"],v["t"],None,None,"neutral",
                        self.game_id,saved_ver,confidence=v.get("c",1.0))
            for k, v in data.get("dialog", {}).items():
                parts = k.split("|")
                if len(parts) == 3 and saved_ver == self.game_version:
                    self._dialog[(parts[0],parts[1],parts[2])] = MemoryEntry(
                        v["o"],v["t"],v.get("s"),v.get("l"),
                        v["r"],self.game_id,saved_ver,confidence=v.get("c",1.0))
            self._cross = data.get("cross", {})
        except Exception:
            pass

    def stats(self) -> dict:
        return {
            "ui_entries":     len(self._ui),
            "dialog_entries": len(self._dialog),
            "cross_entries":  len(self._cross),
            "total_saved":    sum(e.use_count for e in
                                  list(self._ui.values())+list(self._dialog.values())),
        }


# ── Listener Detector ─────────────────────────────────────────────────────────
class ListenerDetector:
    def __init__(self, scene_map: dict = None):
        self.scene_map = scene_map or {}

    def detect(self, item: dict, prev_items: list, idx: int) -> Optional[str]:
        # วิธี 1: tag ตรงๆ
        if item.get("listener"):
            return item["listener"]

        # วิธี 2: parse scene
        scene = item.get("scene", "")
        if scene:
            for pattern, pair in self.scene_map.items():
                if pattern in scene.lower():
                    spk = item.get("speaker", "").lower()
                    if pair[0].lower() == spk:
                        return pair[1]
                    elif pair[1].lower() == spk:
                        return pair[0]

        # วิธี 3: infer จาก dialog ก่อนหน้า
        if idx > 0 and prev_items:
            prev = prev_items[-1]
            if prev.get("speaker") != item.get("speaker"):
                return prev.get("speaker")
            return prev.get("listener")

        return None


# ── Validation ────────────────────────────────────────────────────────────────
class TranslationValidator:
    def __init__(self, glossary: list[str], register: str):
        self.glossary = glossary
        self.register = register
        self.expected_pronouns = SPEAKER_REGISTER.get(register, {})

    def verify(self, original: str, translated: str) -> tuple[bool, float, str]:
        """คืนค่า (valid, confidence, reason)"""
        # 1. ตรวจ glossary terms
        for term in self.glossary:
            if term.lower() in original.lower():
                if term not in translated:
                    return False, 0.3, f"glossary term '{term}' หายไป"

        # 2. ตรวจ placeholder
        placeholders = re.findall(r'\{[^}]+\}', original)
        for ph in placeholders:
            if ph not in translated:
                return False, 0.4, f"placeholder '{ph}' หายไป"

        # 3. ตรวจความยาว (ไม่ควรสั้นหรือยาวเกิน 3x)
        orig_len = len(original.split())
        trans_len = len(translated.split())
        if orig_len > 3 and (trans_len < orig_len * 0.3 or
                              trans_len > orig_len * 3.5):
            return False, 0.5, "ความยาวผิดปกติ"

        # 4. ตรวจ empty output
        if not translated.strip():
            return False, 0.0, "ผลการแปลว่างเปล่า"

        confidence = 0.95
        return True, confidence, "ok"

    def check_terminology(self, translations: dict[str, str]) -> list[dict]:
        """ตรวจ Terminology Consistency ทั้งเกม"""
        word_map: dict[str, dict[str, int]] = {}
        for orig, trans in translations.items():
            for word in orig.lower().split():
                if len(word) > 4:
                    thai_words = trans.split()
                    if thai_words:
                        word_map.setdefault(word, {})
                        # นับคำแปลที่ใช้บ่อยที่สุด
                        for tw in thai_words[:2]:
                            word_map[word][tw] = word_map[word].get(tw, 0) + 1

        inconsistent = []
        for word, counts in word_map.items():
            if len(counts) > 1:
                dominant = max(counts, key=counts.get)
                total = sum(counts.values())
                minority = total - counts[dominant]
                if minority > 0 and minority / total > 0.1:
                    inconsistent.append({
                        "word": word,
                        "dominant": dominant,
                        "variants": counts,
                        "flag_count": minority,
                    })
        return inconsistent


# ── Semantic Deduplication ────────────────────────────────────────────────────
def semantic_dedup(strings: list[str],
                   threshold: float = 0.92) -> dict[str, str]:
    """
    จัดกลุ่ม strings ที่คล้ายกัน คืน map ของ duplicate → original
    """
    groups: dict[str, str] = {}
    seen: list[str] = []
    for s in strings:
        matched = False
        for ref in seen:
            ratio = SequenceMatcher(None, s.lower(), ref.lower()).ratio()
            if ratio >= threshold:
                groups[s] = ref
                matched = True
                break
        if not matched:
            seen.append(s)
    return groups


# ── Cluster Strings ───────────────────────────────────────────────────────────
def cluster_strings(items: list[dict]) -> dict[str, list[dict]]:
    """จัดกลุ่ม strings ตาม location/scene type"""
    clusters: dict[str, list[dict]] = {
        "combat": [], "dialog": [], "ui": [],
        "item": [], "lore": [], "ambient": [], "other": [],
    }
    combat_kw  = {"attack","fight","defend","hp","damage","kill","die","wound"}
    item_kw    = {"sword","armor","potion","ring","staff","blade","shield"}
    lore_kw    = {"ancient","legend","history","tale","story","myth","lore"}
    ambient_kw = {"hmm","aye","hey","oh","ah","yes","no","hello","goodbye"}

    for item in items:
        t    = item.get("text","").lower()
        loc  = item.get("location","").lower()
        words = set(t.split())

        if any(k in loc for k in ["combat","fight","battle"]) or \
           words & combat_kw:
            clusters["combat"].append(item)
        elif any(k in loc for k in ["shop","item","inventory"]) or \
             words & item_kw:
            clusters["item"].append(item)
        elif any(k in loc for k in ["lore","journal","codex"]) or \
             words & lore_kw:
            clusters["lore"].append(item)
        elif len(t.split()) <= 3 and words & ambient_kw:
            clusters["ambient"].append(item)
        elif item.get("speaker"):
            clusters["dialog"].append(item)
        else:
            clusters["other"].append(item)

    return {k: v for k, v in clusters.items() if v}


# ── Pick Model ────────────────────────────────────────────────────────────────
def pick_model(text: str, register: str, is_haiku_poetry: bool = False) -> tuple[str, int]:
    """คืน (model_name, max_tokens)"""
    if is_haiku_poetry:
        return "claude-sonnet-4-20250514", 300
    words = len(text.split())
    if words <= 6 and register in ("neutral", "casual"):
        return "claude-haiku-4-5-20251001", 100
    return "claude-sonnet-4-20250514", 500


# ── Anchor Strings ────────────────────────────────────────────────────────────
def build_anchor_examples(memory: TranslationMemory,
                           register: str, n: int = 6) -> str:
    """ดึง anchor strings จาก memory มาเป็นตัวอย่างใน prompt"""
    examples = []
    for entry in list(memory._dialog.values()):
        if entry.register == register and entry.confidence >= 0.95:
            examples.append(f'"{entry.original}" → "{entry.translated}"')
        if len(examples) >= n:
            break
    if not examples:
        for entry in list(memory._ui.values())[:3]:
            examples.append(f'"{entry.original}" → "{entry.translated}"')
    return "\n".join(examples)


# ── Context Builder ───────────────────────────────────────────────────────────
def build_system_prompt(context: dict, register: str,
                        pair: Optional[ConversationPair],
                        anchors: str, depth: str = "full") -> str:
    """
    สร้าง system prompt ตาม depth:
    minimal  = world + tone เท่านั้น (~80 tokens)
    standard = + register + glossary (~150 tokens)
    full     = + pair + anchors (~250 tokens)
    """
    genre    = context.get("genre", "fantasy")
    template = GENRE_TEMPLATES.get(genre, {})
    glossary = context.get("no_translate", [])
    reg_info = SPEAKER_REGISTER.get(register, SPEAKER_REGISTER["neutral"])

    lines = [
        f"Translate EN→TH. Game:{context.get('game','')}",
        f"World:{context.get('world','')} | Tone:{context.get('tone','')}",
    ]

    if depth in ("standard", "full"):
        lines.append(
            f"Register:{register} self={reg_info['self']} "
            f"other={reg_info['other']}"
        )
        if glossary:
            lines.append(f"Keep:{','.join(glossary[:15])}")
        # Translation rules
        lines.append("Rules: ห้ามแปลชื่อตัวละคร/กลุ่ม/สถานที่/ชื่อเฉพาะ")

    if depth == "full":
        if pair:
            lines.append(
                f"Pair:{pair.speaker}→{pair.listener} "
                f"({pair.pronoun_self}/{pair.pronoun_other})"
            )
        if template.get("geralt_rule"):
            lines.append(f"Special:{template['geralt_rule']}")
        if anchors:
            lines.append(f"Examples:\n{anchors}")

    lines.append("Return JSON array only, same order.")
    return "\n".join(lines)


# ── API Call ──────────────────────────────────────────────────────────────────
def _call_api(system: str, texts: list[str],
              model: str = "claude-sonnet-4-20250514",
              max_tokens: int = 2000) -> Optional[list[str]]:
    try:
        import anthropic
        client = anthropic.Anthropic()
        resp   = client.messages.create(
            model=model, max_tokens=max_tokens,
            system=[{"type":"text","text":system,
                     "cache_control":{"type":"ephemeral"}}],
            messages=[{"role":"user",
                       "content":json.dumps(texts, ensure_ascii=False)}]
        )
        raw  = resp.content[0].text.strip()
        raw  = re.sub(r'^```json|```$', '', raw, flags=re.MULTILINE).strip()
        return json.loads(raw)
    except Exception as e:
        # Offline fallback
        results = []
        for t in texts:
            words = t.lower().split()
            fb = [FALLBACK_DICT.get(w, w) for w in words]
            results.append(" ".join(fb) if any(
                w in FALLBACK_DICT for w in words) else t)
        return results


# ── Smart Translator ──────────────────────────────────────────────────────────
class SmartTranslator:
    def __init__(self, game_id: str, game_context: dict,
                 speaker_roles: dict = None,
                 pair_matrix: dict = None,
                 scene_map: dict = None,
                 game_version: str = "1.0",
                 memory_dir: str = ".gamelang_memory",
                 lore_db: "LoreConsistencyDB" = None,
                 tone_bank: "ToneReferenceBank" = None,
                 char_profiles: dict = None):
        self.game_id       = game_id
        self.context       = game_context
        self.speaker_roles = speaker_roles or {}
        self.pair_matrix   = pair_matrix or {}
        self.game_version  = game_version
        self.lore_db       = lore_db
        self.tone_bank     = tone_bank or ToneReferenceBank.build_defaults()
        self.char_profiles = char_profiles or {}
        self.memory = TranslationMemory(
            game_id,
            os.path.join(memory_dir, f"{game_id}_memory.json"),
            game_version
        )
        self.detector      = ListenerDetector(scene_map or {})
        self._results: dict[int, str] = {}
        self._prev_context: list[dict] = []  # Shared Context Window

    def _get_register(self, speaker: Optional[str],
                      listener: Optional[str]) -> str:
        if not speaker:
            return "neutral"
        spk = speaker.lower()
        lst = (listener or "").lower()
        # เช็ค pair matrix ก่อน
        if (spk, lst) in self.pair_matrix:
            return self.pair_matrix[(spk, lst)]
        if (lst, spk) in self.pair_matrix:
            r = self.pair_matrix[(lst, spk)]
            # inverse: ถ้า Jin→Shifu = "respectful" แล้ว Shifu→Jin = "mentor"
            inverse = {"formal":"mentor","reverent":"formal","filial":"mentor"}
            return inverse.get(r, r)
        return self.speaker_roles.get(spk, "polite")

    def _get_pair(self, speaker: Optional[str],
                  listener: Optional[str]) -> Optional[ConversationPair]:
        if not speaker or not listener:
            return None
        register = self._get_register(speaker, listener)
        reg_info = SPEAKER_REGISTER.get(register, SPEAKER_REGISTER["neutral"])
        return ConversationPair(
            speaker=speaker, listener=listener, register=register,
            pronoun_self=reg_info["self"], pronoun_other=reg_info["other"],
        )

    def _scene_depth(self, location: str) -> str:
        """กำหนด context depth ตาม scene importance"""
        if any(k in (location or "").lower() for k in
               ["main","story","chapter","quest","cutscene","boss"]):
            return "full"
        if any(k in (location or "").lower() for k in
               ["dialog","npc","town","camp"]):
            return "standard"
        return "minimal"

    def process_batch(self, strings: list[dict]) -> list[str]:
        self._results.clear()
        pending_ui:     list[tuple] = []
        pending_dialog: list[tuple] = []
        seen_items = []

        # ── Sort by priority + tag phases ───────────────────────────────────
        strings = sort_by_priority(strings)
        strings = tag_narrative_phases(strings)

        # ── Semantic Dedup ──────────────────────────────────────────────────
        texts     = [s.get("text","") for s in strings]
        dedup_map = semantic_dedup(texts)

        # ── Cluster ─────────────────────────────────────────────────────────
        clusters = cluster_strings(strings)

        # ── Pass 1: จัดประเภท + memory lookup ──────────────────────────────
        for i, item in enumerate(strings):
            text = item.get("text","").strip()
            if not text:
                self._results[i] = ""; continue

            speaker  = item.get("speaker")
            listener = self.detector.detect(item, seen_items, i)
            seen_items.append({**item, "listener": listener})

            # Semantic dedup: ถ้าเป็น duplicate ใช้ผลจาก original
            if text in dedup_map:
                orig_text = dedup_map[text]
                orig_idx  = next((j for j,s in enumerate(strings)
                                  if s.get("text","") == orig_text), None)
                if orig_idx is not None and orig_idx in self._results:
                    self._results[i] = self._results[orig_idx]; continue

            if self.memory.is_ui(text):
                cached = self.memory.lookup_ui(text)
                if cached:
                    self._results[i] = cached
                else:
                    pending_ui.append((i, text))
            else:
                register = self._get_register(speaker, listener)
                cached   = self.memory.lookup_dialog(text, speaker,
                                                     listener, register)
                if cached:
                    self._results[i] = cached
                else:
                    location = item.get("location","")
                    pending_dialog.append((i, text, speaker, listener,
                                           register, location))

        # ── Pass 2: แปล UI batch เดียว ──────────────────────────────────────
        if pending_ui:
            self._translate_ui(pending_ui)

        # ── Pass 3: แปล Dialog แยกตาม register + depth ──────────────────────
        if pending_dialog:
            self._translate_dialog(pending_dialog)

        self.memory.save()
        return [self._results.get(i,"") for i in range(len(strings))]

    def _translate_ui(self, items: list[tuple]):
        BATCH = 50
        for start in range(0, len(items), BATCH):
            chunk  = items[start:start+BATCH]
            texts  = [t for _,t in chunk]
            # Abbreviation expansion
            expanded = []
            restores = []
            for t in texts:
                exp, restore = expand_abbreviations(t)
                expanded.append(exp)
                restores.append(restore)
            texts_to_send = expanded
            system = (f"Translate UI strings EN→TH. Return JSON array only.\n"
                      f"Game:{self.context.get('game','')} | neutral Thai\n"
                      f"Rules: ห้ามแปลชื่อเฉพาะ ทับศัพท์ term เกม\n"
                      + self.tone_bank.to_prompt_section("neutral", n=4) +
                      "\nReturn JSON array only.")
            model, mt = pick_model(texts[0], "neutral")
            results = _call_api(system, texts, model, max_tokens=min(mt*len(texts),2000))
            if results:
                validator = TranslationValidator(
                    self.context.get("no_translate",[]), "neutral")
                for (i, text), th in zip(chunk, results):
                    valid, conf, _ = validator.verify(text, th)
                    if valid:
                        self._results[i] = th
                        self.memory.save_ui(text, th, conf)
                    else:
                        # retry single
                        r2 = _call_api(system, [text], model, 200)
                        if r2:
                            self._results[i] = r2[0]
                            self.memory.save_ui(text, r2[0], 0.8)

    def _translate_dialog(self, items: list[tuple]):
        # จัดกลุ่มตาม register + depth
        groups: dict[tuple, list] = {}
        for item in items:
            i, text, spk, lst, register, loc = item
            depth = self._scene_depth(loc)
            key   = (register, depth)
            groups.setdefault(key, []).append(item)

        validator_cache: dict[str, TranslationValidator] = {}
        glossary = self.context.get("no_translate", [])

        for (register, depth), group in groups.items():
            BATCH = 50
            if register not in validator_cache:
                validator_cache[register] = TranslationValidator(
                    glossary, register)
            validator = validator_cache[register]

            for start in range(0, len(group), BATCH):
                chunk  = group[start:start+BATCH]
                texts  = [t for _,t,_,_,_,_ in chunk]
                spk0   = chunk[0][2]
                lst0   = chunk[0][3]
                pair   = self._get_pair(spk0, lst0)
                anchors= build_anchor_examples(self.memory, register)
                phase  = strings[chunk[0][0]].get("phase", "unknown") \
                         if chunk[0][0] < len(strings) else "unknown"
                system = build_system_prompt_v2(
                    self.context, register, pair,
                    self.tone_bank, self.lore_db,
                    phase=phase, depth=depth)

                is_haiku = self.context.get("genre") == "samurai"
                model, mt = pick_model(texts[0], register,
                                       is_haiku_poetry=is_haiku)
                results = call_api_with_schema(
                    system, texts, model,
                    max_tokens=min(mt*len(texts), 3000),
                    prev_context=self._prev_context[-3:])

                if results:
                    for (i,text,spk,lst,reg,loc), th in zip(chunk, results):
                        valid, conf, reason = validator.verify(text, th)
                        if valid:
                            self._results[i] = th
                            self.memory.save_dialog(text, th, spk, lst,
                                                    reg, conf)
                        else:
                            # Rollback per string: retry เดี่ยว + full context
                            sys2 = build_system_prompt(
                                self.context, reg,
                                self._get_pair(spk, lst),
                                anchors, "full")
                            r2 = _call_api(sys2, [text], model,
                                           max_tokens=mt)
                            th2 = r2[0] if r2 else FALLBACK_DICT.get(
                                text.lower().split()[0], text)
                            self._results[i] = th2
                            self.memory.save_dialog(text, th2, spk, lst,
                                                    reg, 0.7)

    def get_stats(self) -> dict:
        return self.memory.stats()


# ════════════════════════════════════════════════════════════════════════════
# BATCH 3 — Response Schema, Incremental Glossary, Temperature Scheduling,
#            Abbreviation Expansion, Shared Context Window,
#            Post-Translation Compression, Batch Priority Queue
# ════════════════════════════════════════════════════════════════════════════

# ── Abbreviation Map ──────────────────────────────────────────────────────────
ABBREVIATIONS = {
    "dmg": "damage", "str": "strength", "def": "defense",
    "hp":  "health points", "mp": "mana points", "sp": "stamina points",
    "exp": "experience", "lv": "level", "atk": "attack",
    "crit": "critical hit", "acc": "accuracy", "eva": "evasion",
    "res": "resistance", "regen": "regeneration", "max": "maximum",
    "min": "minimum", "qty": "quantity", "req": "required",
}

COMPRESS_RULES = {
    # UI ควรสั้น
    "ui":     {"max_words": 4,  "style": "กระชับ"},
    "combat": {"max_words": 6,  "style": "สั้นหนักแน่น"},
    "dialog": {"max_words": 30, "style": "ธรรมชาติ"},
    "lore":   {"max_words": 50, "style": "บรรยาย"},
}

PRIORITY_ORDER = {
    "tutorial": 1, "main_story": 2, "main": 2,
    "side_quest": 3, "quest": 3, "npc": 4,
    "ambient": 5, "hidden": 6, "lore": 6,
}


def expand_abbreviations(text: str) -> tuple[str, dict]:
    """ขยาย abbreviation ก่อนส่ง API คืน (expanded_text, restore_map)"""
    restore = {}
    words   = text.split()
    result  = []
    for w in words:
        clean = w.lower().strip(".,!?:;")
        if clean in ABBREVIATIONS:
            expanded = ABBREVIATIONS[clean]
            restore[expanded] = w
            result.append(w.replace(clean, expanded))
        else:
            result.append(w)
    return " ".join(result), restore


def compress_translation(text: str, string_type: str) -> str:
    """ตรวจและย่อคำแปลที่ยาวเกินสำหรับ type นั้น"""
    rule = COMPRESS_RULES.get(string_type, COMPRESS_RULES["dialog"])
    words = text.split()
    if len(words) > rule["max_words"] * 1.5:
        # flag ให้ review แต่ไม่ตัดอัตโนมัติ — return as-is พร้อม marker
        return text + "  # COMPRESS_REVIEW"
    return text


def sort_by_priority(items: list[dict]) -> list[dict]:
    """จัดเรียง strings ตาม priority ก่อนแปล"""
    def score(item):
        loc = (item.get("location") or "").lower()
        for key, pri in PRIORITY_ORDER.items():
            if key in loc:
                return pri
        return 5
    return sorted(items, key=score)


def build_tool_schema() -> list[dict]:
    """Response Schema Enforcement ผ่าน tool use"""
    return [{
        "name": "submit_translations",
        "description": "ส่งผลการแปลทั้งหมด",
        "input_schema": {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "คำแปลตามลำดับ",
                }
            },
            "required": ["results"],
        }
    }]


def call_api_with_schema(system: str, texts: list[str],
                          model: str = "claude-sonnet-4-20250514",
                          max_tokens: int = 2000,
                          prev_context: list[dict] = None) -> Optional[list[str]]:
    """API call พร้อม tool use schema + shared context window"""
    try:
        import anthropic
        client = anthropic.Anthropic()

        # Shared Context Window — แนบ prev translations ถ้ามี
        user_content = json.dumps(texts, ensure_ascii=False)
        if prev_context:
            ctx_str = "\n".join(
                f'"{p["en"]}" → "{p["th"]}"'
                for p in prev_context[-3:]  # แค่ 3 ประโยคล่าสุด
            )
            user_content = f"บทสนทนาก่อนหน้า:\n{ctx_str}\n\nแปล:\n{user_content}"

        resp = client.messages.create(
            model=model, max_tokens=max_tokens,
            system=[{"type": "text", "text": system,
                     "cache_control": {"type": "ephemeral"}}],
            tools=build_tool_schema(),
            tool_choice={"type": "tool", "name": "submit_translations"},
            messages=[{"role": "user", "content": user_content}]
        )

        # ดึงผลจาก tool use
        for block in resp.content:
            if block.type == "tool_use" and block.name == "submit_translations":
                return block.input.get("results", [])

        # fallback: parse text
        for block in resp.content:
            if hasattr(block, "text"):
                raw = re.sub(r'^```json|```$', '', block.text,
                             flags=re.MULTILINE).strip()
                return json.loads(raw)
    except Exception as e:
        pass
    return None


# ════════════════════════════════════════════════════════════════════════════
# BATCH 4 — Pre-Translation Context Scan, Character Voice Profile,
#            Narrative Arc Awareness, Dialogue Flow Check,
#            Cultural Adaptation Layer, Lore Consistency Database,
#            Emotion Intensity Calibration
# ════════════════════════════════════════════════════════════════════════════

# ── Narrative Phases ──────────────────────────────────────────────────────────
NARRATIVE_PHASES = {
    "prologue":  {"intensity": 0.5, "desc": "แนะนำโลก บรรยากาศกลาง"},
    "rising":    {"intensity": 0.7, "desc": "tension เพิ่มขึ้น conflict เริ่ม"},
    "climax":    {"intensity": 1.0, "desc": "หนักสุด emotional peak"},
    "falling":   {"intensity": 0.6, "desc": "คลี่คลาย ผลลัพธ์"},
    "epilogue":  {"intensity": 0.4, "desc": "สงบ ไตร่ตรอง บทสรุป"},
    "unknown":   {"intensity": 0.6, "desc": "ไม่ระบุ"},
}

# ── Cultural Adaptation Patterns ──────────────────────────────────────────────
CULTURAL_ADAPT = {
    # สำนวนฝรั่งที่แปลตรงแล้วแปลก
    "by the gods":      "เทพเจ้าช่วย",
    "son of a":         "อ้าย",
    "for the love of":  "เพื่อ",
    "gods be damned":   "ช่างมัน",
    "blast it":         "อุ๊ตส่าห์",
    "by my blade":      "ข้าสาบาน",
    "hell of a":        "ยิ่งใหญ่",
    "damn it all":      "แย่จริงๆ",
}

# ── Emotion Levels ────────────────────────────────────────────────────────────
EMOTION_MARKERS = {
    "high":   ["!", "!!", "?!", "...!", "CAPS"],
    "medium": [".", "?", "..."],
    "low":    [",", "-", ";"],
}


@dataclass
class CharacterVoiceProfile:
    name:           str
    speech_length:  str        # "สั้น" / "กลาง" / "ยาว"
    personality:    str
    catchphrases:   list[str]
    forbidden_words: list[str]
    max_sentence_words: int = 20


@dataclass
class LoreEntry:
    term:       str
    decision:   str            # "keep" / "translate" / "adapt"
    thai:       str            # คำแปลหรือทับศัพท์ที่ตัดสินใจ
    reason:     str = ""


class LoreConsistencyDB:
    """Database ของ lore decisions ที่ทำไปแล้ว"""

    def __init__(self, path: str):
        self.path    = path
        self._db:    dict[str, LoreEntry] = {}
        self._load()

    def add(self, term: str, decision: str, thai: str, reason: str = ""):
        self._db[term.lower()] = LoreEntry(term, decision, thai, reason)
        self._save()

    def lookup(self, term: str) -> Optional[LoreEntry]:
        return self._db.get(term.lower())

    def to_glossary(self) -> list[str]:
        """คืน list ของ terms ที่ตัดสินใจ keep"""
        return [e.term for e in self._db.values() if e.decision == "keep"]

    def to_prompt_section(self) -> str:
        """สร้างส่วน lore decisions สำหรับ system prompt"""
        lines = ["Lore decisions:"]
        for e in list(self._db.values())[:20]:  # จำกัด 20 entries
            if e.decision == "keep":
                lines.append(f"  {e.term} → คงไว้")
            elif e.decision == "translate":
                lines.append(f"  {e.term} → {e.thai}")
        return "\n".join(lines)

    def _save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(
                {k: {"term":v.term,"dec":v.decision,"th":v.thai,"r":v.reason}
                 for k,v in self._db.items()},
                f, ensure_ascii=False, indent=2
            )

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                self._db[k] = LoreEntry(v["term"],v["dec"],v["th"],v.get("r",""))
        except Exception:
            pass


def detect_emotion(text: str) -> tuple[str, float]:
    """ตรวจ emotion intensity จากตัวบ่งชี้ในข้อความ"""
    score = 0.5
    if text.isupper() and len(text) > 3:
        score += 0.3
    if "!!" in text or "?!" in text:
        score += 0.25
    elif "!" in text:
        score += 0.15
    if "..." in text:
        score -= 0.1
    score = max(0.1, min(1.0, score))
    if score >= 0.75:
        level = "high"
    elif score >= 0.45:
        level = "medium"
    else:
        level = "low"
    return level, round(score, 2)


def detect_phase(location: str, scene_id: str = "") -> str:
    """ตรวจ narrative phase จาก location/scene"""
    combined = (location + " " + scene_id).lower()
    if any(k in combined for k in ["prologue","intro","tutorial","opening"]):
        return "prologue"
    if any(k in combined for k in ["climax","final","boss","ending","last"]):
        return "climax"
    if any(k in combined for k in ["epilogue","after","credit","post"]):
        return "epilogue"
    if any(k in combined for k in ["chapter_1","act_1","early","begin"]):
        return "rising"
    if any(k in combined for k in ["chapter_3","chapter_4","act_3","late"]):
        return "falling"
    return "unknown"


def apply_cultural_adaptation(text: str) -> str:
    """แทนที่สำนวนฝรั่งด้วยสำนวนที่เป็นธรรมชาติในภาษาไทย"""
    result = text
    for pattern, replacement in CULTURAL_ADAPT.items():
        result = re.sub(
            re.escape(pattern), replacement, result, flags=re.IGNORECASE
        )
    return result


def check_dialogue_flow(pairs: list[tuple[str,str]]) -> list[dict]:
    """
    ตรวจว่า dialog ไหลตามธรรมชาติ
    pairs = [(en_original, th_translated), ...]
    คืน list ของปัญหาที่พบ
    """
    issues = []
    for i in range(1, len(pairs)):
        prev_en, prev_th = pairs[i-1]
        curr_en, curr_th = pairs[i]

        # ตรวจว่า question ก่อนหน้าได้รับการตอบ
        if prev_en.strip().endswith("?"):
            # คำถามควรมีคำตอบ ตรวจว่า th ตอบสนองหรือไม่
            if len(curr_th.split()) < 2:
                issues.append({
                    "index": i,
                    "type": "short_response_to_question",
                    "prev": prev_th,
                    "curr": curr_th,
                })

        # ตรวจ pronoun consistency
        if "ข้า" in prev_th and "ผม" in curr_th:
            issues.append({
                "index": i,
                "type": "pronoun_drift",
                "from": "ข้า",
                "to": "ผม",
            })

    return issues


def pre_translation_scan(strings: list[dict],
                          context: dict) -> dict:
    """
    อ่านไฟล์ภาษาทั้งหมดก่อนแปล สรุป:
    - ตัวละครหลัก
    - recurring themes
    - tone โดยรวม
    - คำเฉพาะที่เจอบ่อย
    """
    speakers    = {}
    word_freq:  dict[str, int] = {}
    total       = len(strings)

    for item in strings:
        spk = item.get("speaker")
        if spk:
            speakers[spk] = speakers.get(spk, 0) + 1
        for w in item.get("text", "").lower().split():
            if len(w) > 4:
                word_freq[w] = word_freq.get(w, 0) + 1

    # top speakers
    top_speakers = sorted(speakers.items(), key=lambda x: -x[1])[:10]
    # frequent unique terms (น่าจะเป็น proper nouns)
    freq_terms   = [w for w,c in sorted(word_freq.items(), key=lambda x:-x[1])
                    if c > total * 0.005 and w not in FALLBACK_DICT][:20]

    return {
        "total_strings":  total,
        "top_speakers":   top_speakers,
        "frequent_terms": freq_terms,
        "scan_complete":  True,
    }


# ════════════════════════════════════════════════════════════════════════════
# BATCH 5 — Tone Reference Strings, Narrative Phase Tagging
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class ToneReference:
    en:       str
    th:       str
    register: str
    note:     str = ""


class ToneReferenceBank:
    """
    เก็บ reference strings เป็นมาตรฐาน tone
    10 strings ต่อ register — แนบทุก batch เพื่อ lock tone
    """
    def __init__(self):
        self._bank: dict[str, list[ToneReference]] = {}

    def add(self, register: str, en: str, th: str, note: str = ""):
        self._bank.setdefault(register, []).append(
            ToneReference(en, th, register, note)
        )

    def get_refs(self, register: str, n: int = 10) -> list[ToneReference]:
        return self._bank.get(register, [])[:n]

    def to_prompt_section(self, register: str, n: int = 10) -> str:
        refs = self.get_refs(register, n)
        if not refs:
            return ""
        lines = [f"Tone references ({register}):"]
        for r in refs:
            lines.append(f'  "{r.en}" → "{r.th}"')
        return "\n".join(lines)

    @classmethod
    def build_defaults(cls) -> "ToneReferenceBank":
        """สร้าง default references สำหรับ register ทั่วไป"""
        bank = cls()

        # formal / archaic
        for en, th in [
            ("Hmm.",                   "ฮืม"),
            ("I understand.",          "ข้าเข้าใจ"),
            ("As you wish.",           "ตามแต่ท่านประสงค์"),
            ("This changes nothing.",  "สิ่งนี้ไม่ได้เปลี่ยนแปลงอะไร"),
            ("Farewell.",              "ลาก่อน"),
        ]:
            bank.add("formal", en, th)

        # casual
        for en, th in [
            ("Hey!",          "เฮ้!"),
            ("Sure.",         "โอเค"),
            ("No problem.",   "ไม่เป็นไร"),
            ("Let's go!",     "ไปเลย!"),
            ("Later.",        "แล้วเจอกัน"),
        ]:
            bank.add("casual", en, th)

        # villain
        for en, th in [
            ("You dare?",       "เจ้ากล้าดีนัก"),
            ("Pathetic.",       "น่าสมเพช"),
            ("You will pay.",   "เจ้าจะต้องจ่าย"),
            ("How amusing.",    "น่าขบขัน"),
            ("Kneel.",          "คุกเข่าลง"),
        ]:
            bank.add("villain", en, th)

        return bank


def build_system_prompt_v2(context: dict,
                            register: str,
                            pair: Optional[ConversationPair],
                            tone_bank: ToneReferenceBank,
                            lore_db: Optional[LoreConsistencyDB],
                            phase: str = "unknown",
                            depth: str = "full") -> str:
    """
    system prompt เวอร์ชัน v2 รวม:
    - Tone Reference Strings
    - Narrative Phase Tagging
    - Lore Consistency DB
    - Cultural Adaptation note
    - Character Voice Profile (ถ้ามี)
    """
    genre    = context.get("genre", "fantasy")
    template = GENRE_TEMPLATES.get(genre, {})
    reg_info = SPEAKER_REGISTER.get(register, SPEAKER_REGISTER["neutral"])
    phase_info = NARRATIVE_PHASES.get(phase, NARRATIVE_PHASES["unknown"])

    lines = [
        f"Translate EN→TH. Game:{context.get('game','')}",
        f"World:{context.get('world','')} | Tone:{context.get('tone','')}",
        f"Phase:{phase} (intensity:{phase_info['intensity']}) — "
        f"{phase_info['desc']}",
    ]

    if depth in ("standard", "full"):
        lines.append(
            f"Register:{register} | self={reg_info['self']} "
            f"other={reg_info['other']}"
        )
        no_tr = context.get("no_translate", [])
        if lore_db:
            no_tr = list(set(no_tr + lore_db.to_glossary()))
        if no_tr:
            lines.append(f"Keep:{','.join(no_tr[:20])}")
        lines.append(
            "Rules: ห้ามแปลชื่อตัวละคร/กลุ่ม/สถานที่/ชื่อเฉพาะ | "
            "ปรับสำนวนให้เป็นธรรมชาติภาษาไทย"
        )
        if lore_db:
            lines.append(lore_db.to_prompt_section())

    if depth == "full":
        if pair:
            lines.append(
                f"Pair:{pair.speaker}→{pair.listener} "
                f"({pair.pronoun_self}/{pair.pronoun_other})"
            )
        spec = template.get("geralt_rule") or template.get("haiku_rule")
        if spec:
            lines.append(f"Special:{spec}")

        # Tone Reference Strings
        tone_section = tone_bank.to_prompt_section(register, n=6)
        if tone_section:
            lines.append(tone_section)

    lines.append("Return JSON array only, same order.")
    return "\n".join(lines)


def tag_narrative_phases(strings: list[dict]) -> list[dict]:
    """Tag narrative phase ให้ทุก string ก่อนประมวลผล"""
    result = []
    for item in strings:
        phase = detect_phase(
            item.get("location", ""),
            item.get("scene", ""),
        )
        result.append({**item, "phase": phase})
    return result
