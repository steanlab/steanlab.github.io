#!/usr/bin/env python3
"""Lossless conversion of the two archive pages (Markdown) to YAML data and back.

Репозиторий: steanlab-site-src (приватный). Файл: tools/archive_data.py

Команды (запускать из корня репозитория):
  python3 tools/archive_data.py convert   # _posts/*.md  ->  _data/*.yml
  python3 tools/archive_data.py check     # собрать Markdown обратно, сравнить с оригиналом, записать REPORT.md

Исходные файлы _posts/*.md этот скрипт НЕ изменяет.
Дефекты исходников (незакрытые скобки, опечатки в подписях и т. п.) переносятся как есть:
исправлять их можно только отдельным, одобренным шагом.
"""
import argparse
import collections
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys

import yaml

PAIRS = [
    ("_posts/2014-3-2-interview.md", "_data/media.yml"),
    ("_posts/2014-3-3-bibliography.md", "_data/publications.yml"),
]

HEADER = (
    "# Данные страницы, перенесённые из {src} скриптом tools/archive_data.py.\n"
    "# Порядок разделов и записей, заголовки, подписи ссылок и тексты сохранены как в источнике.\n"
    "# Описание структуры и найденные дефекты: REPORT.md\n"
)

# ------------------------------------------------------- approved fixes
# Одобренные исправления дефектов исходников. Номера строк относятся к ИСХОДНЫМ файлам _posts/*.md.
# Операции: sub (заменить подстроку, ровно одно вхождение), suffix (заменить конец строки),
# prefix (добавить начало строки), delete_dup (удалить строку, полностью совпадающую со строкой old).
# Буквы-двойники записаны кодами, чтобы не перепутать латиницу и кириллицу.
LAT_C, LAT_c = "C", "c"
CYR_C, CYR_c = "\u0421", "\u0441"
CYR_M = "\u041c"
CYR_U = "\u0423"

FIXES = {
    "_posts/2014-3-2-interview.md": [
        (7, "sub", LAT_C + "ортировка", CYR_C + "ортировка"),
        (18, "suffix", "6526620.html", "6526620.html)"),
        (22, "prefix", "", "- "),
        (155, "sub", " - [WEBARCHIVE]", ""),
        (156, "sub", " - [WEBARCHIVE]", ""),
        (239, "sub", "[" + LAT_C + "ергей", "[" + CYR_C + "ергей"),
        (275, "suffix", "83323.html))", "83323.html)"),
        (289, "sub", "(http://web.archive.org/screenshot/", "(https://web.archive.org/screenshot/"),
        (380, "sub", " - [WEBARCHIVE]", ""),
        (406, "sub", "4WbIq]-[WEBARCHIVE]", "4WbIq) - [WEBARCHIVE]"),
        (418, "sub", "[WEARCHIVE]", "[WEBARCHIVE]"),
        (441, "sub", " - [WEBARCHIVE]", ""),
        (460, "sub", "[ARCIVE.IS]", "[ARCHIVE.IS]"),
        (478, "sub", "Беларус" + LAT_c + "кий", "Беларус" + CYR_c + "кий"),
        (483, "sub", "[WEBARCHIVE_BY]", "[WEBARCHIVE BY]"),
        (483, "sub", "[WEBARCHIVE_EN]", "[WEBARCHIVE EN]"),
    ],
    "_posts/2014-3-3-bibliography.md": [
        (27, "sub", "## " + LAT_C + "ерия", "## " + CYR_C + "ерия"),
        (32, "sub", "## " + LAT_C + "ерия", "## " + CYR_C + "ерия"),
        (43, "sub", "## " + LAT_C + "ерия", "## " + CYR_C + "ерия"),
        (46, "sub", "[" + LAT_C + "лово", "[" + CYR_C + "лово"),
        (59, "sub", "## " + LAT_C + "ерия", "## " + CYR_C + "ерия"),
        (76, "sub", "file:///C:/Windows/system32", "https://habr.com/ru/articles/482654/"),
        (114, "sub", LAT_C + "цинтилляторы", CYR_C + "цинтилляторы"),
        (124, "sub", LAT_c + "пасибо", CYR_c + "пасибо"),
        (143, "sub", "Белару" + LAT_c + "ский", "Белару" + CYR_c + "ский"),
        (152, "sub", "«" + LAT_C + "пящая", "«" + CYR_C + "пящая"),
        (212, "sub", "[" + LAT_C + "делай", "[" + CYR_C + "делай"),
        (217, "sub", "P " + CYR_U + "[брать", "P [" + CYR_U + "брать"),
        (262, "sub", "[" + LAT_C + "кажи", "[" + CYR_C + "кажи"),
        (267, "sub", ") " + LAT_C + "кажи", ") " + CYR_C + "кажи"),
        (273, "sub", "[" + LAT_C + "ТОП", "[" + CYR_C + "ТОП"),
        (282, "sub", "[" + CYR_M + "esh-сети", "[Mesh-сети"),
        (296, "delete_dup", "281", ""),
        (297, "sub", "или " + LAT_C + "амый", "или " + CYR_C + "амый"),
    ],
}


def apply_fixes(text, fixes, name):
    """Apply FIXES to the original text. Returns (new_text, log). Every fix must match exactly once."""
    text = text.replace("\r\n", "\n")
    trailing_nl = text.endswith("\n")
    lines = text.split("\n")
    if trailing_nl:
        lines.pop()
    orig = list(lines)
    deleted = set()
    for n, op, old, new in fixes:
        l = lines[n - 1]
        if op == "sub":
            if l.count(old) != 1:
                raise SystemExit("%s:%d: «%s» найдено %d раз, ожидалось 1" % (name, n, old, l.count(old)))
            l = l.replace(old, new)
        elif op == "suffix":
            if not l.endswith(old):
                raise SystemExit("%s:%d: строка не оканчивается на «%s»" % (name, n, old))
            l = l[:-len(old)] + new
        elif op == "prefix":
            if not l.startswith("["):
                raise SystemExit("%s:%d: ожидалась строка, начинающаяся с «[»" % (name, n))
            l = new + l
        elif op == "delete_dup":
            if orig[int(old) - 1] != orig[n - 1]:
                raise SystemExit("%s:%d: строка не совпадает со строкой %s" % (name, n, old))
            deleted.add(n)
            continue
        else:
            raise SystemExit("неизвестная операция " + op)
        lines[n - 1] = l
    # одна запись журнала на строку: (номер, строка до, строка после или None, если удалена)
    log = [(n, orig[n - 1], None if n in deleted else lines[n - 1])
           for n in sorted({f[0] for f in fixes})]
    out = [l for i, l in enumerate(lines, 1) if i not in deleted]
    return "\n".join(out) + ("\n" if trailing_nl else ""), log


def load_source(a, src):
    orig = read(os.path.join(a.src_root, src))
    if getattr(a, "raw", False):
        return orig, orig, []
    fixed, log = apply_fixes(orig, FIXES.get(src, []), src)
    return orig, fixed, log


# ---------------------------------------------------------------- tokenizer


def tokenize(s):
    """Split a line into ('L', text, url) links and ('T', text) pieces (balanced [] and ())."""
    out, buf, i = [], "", 0
    while i < len(s):
        if s[i] == "[":
            d, j = 0, i
            while j < len(s):
                if s[j] == "[":
                    d += 1
                elif s[j] == "]":
                    d -= 1
                    if d == 0:
                        break
                j += 1
            if j < len(s) and s[j + 1:j + 2] == "(":
                k, d = j + 2, 1
                while k < len(s) and d > 0:
                    if s[k] == "(":
                        d += 1
                    elif s[k] == ")":
                        d -= 1
                    k += 1
                if d == 0:
                    if buf:
                        out.append(("T", buf))
                        buf = ""
                    out.append(("L", s[i + 1:j], s[j + 2:k - 1]))
                    i = k
                    continue
        buf += s[i]
        i += 1
    if buf:
        out.append(("T", buf))
    return out


KNOWN_MIRRORS = {"CONIFER", "GHOSTARCHIVE", "TELEGRA.PH", "MEDIUM", "TXT", "SCREENSHOT", "ODYSEE"}
LANGS = {"RU", "BE", "BY", "EN", "UA", "PL"}


def link_type(label, url):
    """Derived hint only: the label itself is always stored verbatim."""
    k = re.sub(r"[\s_()]+", "", label).upper()
    if url.lower().endswith(".mp3") or k in ("AUDIO", "ПАДКАСТ"):
        return "audio"
    if k.startswith(("WEBARCHIVE", "WEARCHIVE")):
        return "web_archive"
    if k.startswith(("ARCHIVE.IS", "ARCIVE.IS")):
        return "archive_is"
    if k in LANGS:
        return "language_version"
    if k in KNOWN_MIRRORS:
        return "mirror"
    return "other"


# ------------------------------------------------------------------- parser

BULLET = re.compile(r"^(\s*)([-*])\s+(.*)$")
HEAD = re.compile(r"^\s*(#{1,6})\s+(.*?)\s*$")
HR = re.compile(r"^_{3,}\s*$")
# Метки платформ перед названием материала (расшифровка для читателей: _data/marks.yml)
MARK_CODES = ("P", "M", "PK", "ST", "TG", "RD")
MARK = re.compile(r"^(%s|\(\+\d+\))$" % "|".join(MARK_CODES))


class Flow(dict):
    """Rendered as a one-line {a: b} mapping in YAML."""


def parse_item(body, plain=False):
    toks = tokenize(body)
    first = next((i for i, t in enumerate(toks) if t[0] == "L"), None)
    if first is None:
        return None
    item = {}
    lead = "".join(t[1] for t in toks[:first]).strip()
    if lead:
        item["mark" if MARK.match(lead) else "lead"] = lead
    item["title"] = toks[first][1]
    item["url"] = toks[first][2]
    if plain:
        item["plain"] = True
    parts = []
    for t in toks[first + 1:]:
        if t[0] == "L":
            parts.append(Flow(label=t[1], type=link_type(t[1], t[2]), url=t[2]))
        else:
            s = t[1].strip(" \t-")
            if s:
                parts.append(Flow(text=s))
    if parts:
        item["links"] = parts
    return item


def parse(text):
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    fm = []
    if lines and lines[0] == "---":
        end = lines.index("---", 1)
        fm = lines[1:end]
        lines = lines[end + 1:]
    data = {"front_matter": fm, "preamble": [], "sections": []}
    target = data["preamble"]
    buf = []

    def flush():
        if buf:
            target.append({"text": "\n".join(buf)})
            buf.clear()

    i, toc_seen = 0, 0
    while i < len(lines):
        l = lines[i]
        if (l.strip() == "**СОДЕРЖАНИЕ**" and lines[i + 1:i + 4] == ["", "* TOC", "{:toc}"]):
            flush()
            target.append({"toc": l})
            toc_seen += 1
            i += 4
            continue
        if not l.strip():
            flush()
            i += 1
            continue
        h = HEAD.match(l)
        if h:
            flush()
            sec = {"title": h.group(2), "level": len(h.group(1)), "entries": []}
            data["sections"].append(sec)
            target = sec["entries"]
            i += 1
            continue
        if HR.match(l):
            flush()
            target.append({"hr": l.rstrip()})
            i += 1
            continue
        b = BULLET.match(l)
        if b and not b.group(1):
            flush()
            item = parse_item(b.group(3))
            target.append(item if item else {"bullet": b.group(3)})
            i += 1
            continue
        if l.startswith("[") and tokenize(l)[0][0] == "L":
            flush()
            target.append(parse_item(l, plain=True))
            i += 1
            continue
        buf.append(l)
        i += 1
    flush()
    if toc_seen != 1:
        raise SystemExit("expected exactly one TOC block, found %d" % toc_seen)
    return data


# ----------------------------------------------------------------- renderer


def render_item(e):
    pre = e.get("mark") or e.get("lead")
    s = (pre + " " if pre else "") + "[%s](%s)" % (e["title"], e["url"])
    for p in e.get("links", []):
        s += " - " + ("[%s](%s)" % (p["label"], p["url"]) if "label" in p else p["text"])
    return s if e.get("plain") else "- " + s


def render_entry(e):
    """-> (kind, lines)"""
    if "toc" in e:
        return "block", [e["toc"], "", "* TOC", "{:toc}"]
    if "hr" in e:
        return "block", [e["hr"]]
    if "text" in e:
        return "block", e["text"].split("\n")
    if "bullet" in e:
        return "li", ["- " + e["bullet"]]
    if "title" in e and "url" in e:
        return ("block" if e.get("plain") else "li"), [render_item(e)]
    raise ValueError("unknown entry: %r" % (e,))


def render(data):
    blocks = []
    for e in data["preamble"]:
        blocks.append(render_entry(e))
    for sec in data["sections"]:
        blocks.append(("block", ["#" * sec["level"] + " " + sec["title"]]))
        for e in sec["entries"]:
            blocks.append(render_entry(e))
    out = ["---"] + list(data["front_matter"]) + ["---", ""]
    prev = None
    for kind, lines in blocks:
        if prev is not None and not (prev == "li" and kind == "li"):
            out.append("")
        out.extend(lines)
        prev = kind
    return "\n".join(out) + "\n"


# --------------------------------------------------------------- YAML dump


def _flow(dumper, data):
    return dumper.represent_mapping("tag:yaml.org,2002:map", data, flow_style=True)


def _str(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


yaml.SafeDumper.add_representer(Flow, _flow)
yaml.SafeDumper.add_representer(str, _str)


def dump_yaml(data, src):
    body = yaml.dump(data, Dumper=yaml.SafeDumper, allow_unicode=True, sort_keys=False,
                     width=10 ** 9, default_flow_style=False)
    return HEADER.format(src=src) + body


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# ---------------------------------------------------------------- convert


def cmd_convert(a):
    for src, dst in PAIRS:
        _, fixed, log = load_source(a, src)
        data = parse(fixed)
        data = {"source": src, **data}
        print("%s: применено исправлений: %d" % (src, len(log)))
        write(os.path.join(a.out_root, dst), dump_yaml(data, src))
        print("wrote", dst)


# ------------------------------------------------------------------ check

SEP = re.compile(r"[\s\-–—]+")
URL = re.compile(r"https?://[^\s<>\"\]\)]+|/_posts/files/[^\s\)]+")
LATIN = re.compile(r"[A-Za-z]")
CYR = re.compile(r"[Ѐ-ӿ]")


def norm_line(l):
    return SEP.sub("", re.sub(r"^\s*[-*]\s+", "", l, count=1))


def significant(text):
    """[(original line number, normalized line)] for every line that has content."""
    res = []
    for n, l in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        s = norm_line(l)
        if s:
            res.append((n, s))
    return res


def psych_load(path):
    try:
        r = subprocess.run(
            ["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.load_file(ARGV[0]))", path],
            capture_output=True, text=True, timeout=120)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None, "ruby недоступен"
    if r.returncode != 0:
        return None, r.stderr.strip()[:300]
    return json.loads(r.stdout), ""


def items_of(data):
    for sec in data["sections"]:
        for e in sec["entries"]:
            if "title" in e and "url" in e:
                yield sec, e


def stats_and_defects(data):
    st = collections.OrderedDict()
    secs = data["sections"]
    st["разделов"] = len(secs)
    st["уровни заголовков"] = dict(collections.Counter(s["level"] for s in secs))
    it = list(items_of(data))
    st["записей со ссылками"] = len(it)
    st["из них без маркера списка"] = sum(1 for _, e in it if e.get("plain"))
    st["пунктов без ссылок"] = sum(1 for s in secs for e in s["entries"] if "bullet" in e)
    st["текстовых блоков"] = sum(1 for s in secs for e in s["entries"] if "text" in e) + \
        sum(1 for e in data["preamble"] if "text" in e)
    types = collections.Counter(p["type"] for _, e in it for p in e.get("links", []) if "label" in p)
    st["дополнительных ссылок по типам"] = dict(types)
    st["основных ссылок"] = len(it)

    def has_archive(e):
        if re.search(r"archive\.(org|is|ph|today)", e["url"]):
            return True
        return any(p.get("type") in ("web_archive", "archive_is") or
                   re.search(r"archive\.(org|is|ph|today)", p.get("url", "")) for p in e.get("links", []))

    st["записей без архивной копии"] = sum(1 for _, e in it if not has_archive(e))

    d = collections.OrderedDict()
    d["незакрытые или повреждённые ссылки (текст сохранён как есть)"] = [
        "%s → %s" % (e["title"][:60], p["text"][:90])
        for _, e in it for p in e.get("links", []) if "text" in p and "](" in p["text"]]
    d["подпись архива без адреса, например [WEBARCHIVE]"] = [
        e["title"][:70] for _, e in it for p in e.get("links", [])
        if "text" in p and re.fullmatch(r"\[[A-Za-z_. ]+\]", p["text"])]
    d["необычные подписи ссылок (возможные опечатки)"] = sorted({
        p["label"] for _, e in it for p in e.get("links", []) if "label" in p and
        not re.fullmatch(r"WEBARCHIVE(BE|BY|EN|RU|UA)?|ARCHIVE\.IS|AUDIO|RU|BE|BY|EN|CONIFER|GHOSTARCHIVE|MEDIUM|"
                         r"TELEGRA\.PH|TXT|SCREENSHOT|ПАДКАСТ|\d+",
                         re.sub(r"[\s_()]+", "", p["label"]).upper())})
    d["текст перед ссылкой, не похожий на маркер платформы"] = [
        "%s → %s" % (e["lead"], e["title"][:60]) for _, e in it if "lead" in e]
    d["адреса file:// и http://"] = [
        "%s: %s" % (e["title"][:50], u) for _, e in it
        for u in [e["url"]] + [p["url"] for p in e.get("links", []) if "url" in p]
        if u.startswith(("file://", "http://"))]
    cnt = collections.Counter(e["url"] for _, e in it)
    d["повторяющиеся основные ссылки"] = [u for u, c in cnt.items() if c > 1]
    tcnt = collections.Counter(s["title"] for s in secs)
    d["повторяющиеся заголовки разделов (влияют на якоря)"] = [t for t, c in tcnt.items() if c > 1]

    mixed = collections.Counter()
    where = collections.Counter()
    pieces = [("заголовок раздела", s["title"]) for s in secs]
    pieces += [("название записи", e["title"]) for _, e in it]
    pieces += [("текст", e["text"]) for s in secs for e in s["entries"] if "text" in e]
    pieces += [("текст", e["text"]) for e in data["preamble"] if "text" in e]
    for kind, t in pieces:
        for w in re.findall(r"\w+", t):
            if LATIN.search(w) and CYR.search(w):
                mixed[w] += 1
                where[kind] += 1
    d["слова со смешением латиницы и кириллицы"] = ["%s ×%d" % (w, c) for w, c in mixed.most_common(25)]
    d["_mixed_where"] = dict(where)
    return st, d


def check_pair(a, src, dst):
    res = {"src": src, "dst": dst, "ok": True, "notes": []}
    source, orig, log = load_source(a, src)   # orig здесь = исходный текст с одобренными исправлениями
    res["sha256"] = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    res["fixes"] = log
    yml_path = os.path.join(a.data_root, dst)
    with open(yml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    rendered = render(data)

    # 0. изменены ровно те строки исходника, которые перечислены в FIXES (и ничего больше)
    if not getattr(a, "raw", False):
        so_lines = source.replace("\r\n", "\n").rstrip("\n").split("\n")
        fx_lines = orig.replace("\r\n", "\n").rstrip("\n").split("\n")
        sm = difflib.SequenceMatcher(None, so_lines, fx_lines, autojunk=False)
        old_changed, new_changed = [], []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag != "equal":
                old_changed += so_lines[i1:i2]
                new_changed += fx_lines[j1:j2]
        want_old = [b for _, b, _ in log]
        want_new = [a_ for _, _, a_ in log if a_ is not None]
        if sorted(old_changed) != sorted(want_old) or sorted(new_changed) != sorted(want_new):
            res["ok"] = False
            res["notes"].append("изменены не только одобренные строки")
        res["changed_lines"] = len(want_old)

    # 1. line-by-line comparison of everything except spacing, dashes and list markers
    so, sr = significant(orig), significant(rendered)
    diffs = []
    if len(so) != len(sr):
        diffs.append("число непустых строк: оригинал %d, собрано %d" % (len(so), len(sr)))
    for (n1, a1), (n2, a2) in zip(so, sr):
        if a1 != a2:
            diffs.append("строка %d оригинала отличается от строки %d собранного" % (n1, n2))
            if len(diffs) > 15:
                break
    res["lines"] = (len(so), len(sr))
    if diffs:
        res["ok"] = False
        res["notes"] += diffs

    # 2. independent checks: all URLs in order, number of links
    u1, u2 = URL.findall(orig), URL.findall(rendered)
    res["urls"] = (len(u1), len(u2))
    if u1 != u2:
        res["ok"] = False
        res["notes"].append("последовательность адресов не совпала")
    c1, c2 = orig.count("]("), rendered.count("](")
    res["links_md"] = (c1, c2)
    if c1 != c2:
        res["ok"] = False
        res["notes"].append("число конструкций ](: %d и %d" % (c1, c2))

    # 3. YAML is read identically by Ruby's Psych (the parser Jekyll uses)
    other, err = psych_load(yml_path)
    if other is None:
        res["psych"] = "не проверено: " + err
    else:
        res["psych"] = "совпало" if other == data else "РАСХОДИТСЯ"
        if other != data:
            res["ok"] = False
            res["notes"].append("Ruby Psych прочитал данные иначе, чем PyYAML")

    res["stats"], res["defects"] = stats_and_defects(data)
    return res


def fmt_value(v):
    return json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)


def make_report(results):
    L = ["# Отчёт по переносу интервью и библиографии в данные", ""]
    L.append("Проверка: из данных собирается Markdown и сравнивается с исходным файлом построчно "
             "(без учёта пробелов, дефисов-разделителей и маркеров списка), отдельно сверяются все адреса "
             "по порядку и число ссылок, а YAML читается двумя разными разборщиками (PyYAML и Ruby Psych, "
             "которым пользуется Jekyll).")
    L.append("")
    L.append("## Итог")
    L.append("")
    L.append("| Файл данных | Источник | Строк (ориг. / собрано) | Адресов | Ссылок `](` | Psych | Результат |")
    L.append("|---|---|---|---|---|---|---|")
    for r in results:
        L.append("| `%s` | `%s` | %d / %d | %d / %d | %d / %d | %s | %s |" % (
            r["dst"], r["src"], r["lines"][0], r["lines"][1], r["urls"][0], r["urls"][1],
            r["links_md"][0], r["links_md"][1], r["psych"], "без потерь" if r["ok"] else "ЕСТЬ РАСХОЖДЕНИЯ"))
    for r in results:
        L += ["", "## %s" % r["dst"], "", "Источник `%s`, контрольная сумма SHA-256 (начало): `%s`" % (r["src"], r["sha256"]), ""]
        if r.get("fixes"):
            L.append("Применённые исправления (%d), номера строк исходного файла:" % len(r["fixes"]))
            for n, before, after in r["fixes"]:
                if after is None:
                    L.append("- стр. %d: строка удалена (полный дубль строки с тем же содержанием)" % n)
                else:
                    i = 0
                    while i < min(len(before), len(after)) and before[i] == after[i]:
                        i += 1
                    j = 0
                    while j < min(len(before), len(after)) - i and before[-1 - j] == after[-1 - j]:
                        j += 1
                    lo, hi = max(0, i - 12), 12

                    def win(s):
                        return (s[lo:len(s) - j + hi] if j + hi < len(s) else s[lo:])[:70].replace("`", "'")

                    L.append("- стр. %d: `…%s…` → `…%s…`" % (n, win(before), win(after)))
            L.append("")
        if r["notes"]:
            L.append("Расхождения:")
            L += ["- " + n for n in r["notes"]]
            L.append("")
        L.append("Состав:")
        for k, v in r["stats"].items():
            L.append("- %s: %s" % (k, fmt_value(v)))
        L += ["", "Оставшиеся замечания (не исправлялись, сохранены как в источнике):"]
        for k, v in r["defects"].items():
            if k.startswith("_"):
                continue
            L.append("- %s: %d" % (k, len(v)))
            for x in v[:12]:
                L.append("  - `%s`" % str(x).replace("`", "'"))
            if len(v) > 12:
                L.append("  - … и ещё %d" % (len(v) - 12))
        if r["defects"].get("_mixed_where"):
            L.append("- где найдено смешение алфавитов: %s" % fmt_value(r["defects"]["_mixed_where"]))
    L.append("")
    return "\n".join(L)


def cmd_check(a):
    results = [check_pair(a, s, d) for s, d in PAIRS]
    report = make_report(results)
    write(a.report, report)
    for r in results:
        print("%-28s %s" % (r["dst"], "OK" if r["ok"] else "РАСХОЖДЕНИЯ: " + "; ".join(r["notes"][:5])))
    print("report:", a.report)
    sys.exit(0 if all(r["ok"] for r in results) else 1)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert")
    c.add_argument("--src-root", default=".")
    c.add_argument("--out-root", default=".")
    c.add_argument("--raw", action="store_true", help="не применять одобренные исправления")
    k = sub.add_parser("check")
    k.add_argument("--raw", action="store_true", help="сравнивать с исходником без исправлений")
    k.add_argument("--src-root", default=".")
    k.add_argument("--data-root", default=".")
    k.add_argument("--report", default="REPORT.md")
    a = p.parse_args()
    (cmd_convert if a.cmd == "convert" else cmd_check)(a)


if __name__ == "__main__":
    main()
