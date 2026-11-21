#!/usr/bin/env python3
"""Собирает по данным архива два служебных файла (руками не править):
  _data/latest.yml       последние добавленные записи для блока «Последнее добавленное» на главной;
  _data/media_cards.yml  все записи СМИ одним списком по убыванию даты, плюс список изданий со счётчиками
                         (для страницы СМИ: карточки, поиск, фильтр по изданию).
Исходные данные: _data/media.yml и _data/publications.yml.

Дата записи:
  1) если адрес материала есть в _data/added.yml, то дата из него (записи, добавленные через форму);
  2) иначе самая ранняя метка времени среди ссылок на Wayback Machine (web.archive.org/web/ГГГГММДДччммсс/...);
     такая дата приблизительная (approx: true), на сайте она показывается со значком ≈;
  3) записи без даты в список не попадают.
Порядок: дата по убыванию; при равной дате позже стоящая в файле запись выше. В файл попадают LIMIT записей.

  python3 tools/make_latest.py           пересобрать оба файла
  python3 tools/make_latest.py --check   только проверить, что файлы актуальны (код выхода 1, если нет)
"""
import argparse
import os
import re
import sys
import urllib.parse

import yaml

LIMIT = 8
WAYBACK = re.compile(r"web\.archive\.org/web/(\d{14})")
HEADER = ("# Собирается автоматически: python3 tools/make_latest.py (его вызывает tools/add_item.py).\n"
          "# Руками не править.\n")
SOURCES = (("media", "_data/media.yml"), ("publications", "_data/publications.yml"))


def entry_date(entry, added):
    """(ГГГГ-ММ-ДД, приблизительная ли дата) или None."""
    d = added.get(entry["url"])
    if d:
        return str(d), False
    stamps = []
    for l in entry.get("links", []):
        m = WAYBACK.search(l.get("url", ""))
        if m:
            stamps.append(m.group(1))
    if not stamps:
        return None
    s = min(stamps)
    return "%s-%s-%s" % (s[:4], s[4:6], s[6:8]), True


def build(media, publications, added, limit=LIMIT):
    rows = []
    order = 0
    for kind, data in (("media", media), ("publications", publications)):
        for sec in data["sections"]:
            for e in sec["entries"]:
                order += 1
                if "url" not in e or "title" not in e:
                    continue
                got = entry_date(e, added)
                if got:
                    day, approx = got
                    rows.append((day, order, {"date": day, "approx": approx, "kind": kind, "section": sec["title"],
                                              "title": e["title"], "url": e["url"]}))
    rows.sort(key=lambda r: (r[0], r[1]), reverse=True)
    return [r[2] for r in rows[:limit]]


def load(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_added(root):
    p = os.path.join(root, "_data/added.yml")
    return (load(root, "_data/added.yml") if os.path.exists(p) else None) or {}


def compute(root):
    return build(load(root, "_data/media.yml"), load(root, "_data/publications.yml"), read_added(root))


# --- карточки страницы СМИ -------------------------------------------------------------------------------

# Jekyll не публикует файлы из папок на «_» (в том числе _posts/files), поэтому аудио на странице СМИ
# отдаётся напрямую из репозитория. Когда файлы будут перенесены в обычную папку (например /audio/),
# достаточно заменить AUDIO_SRC и AUDIO_DST.
AUDIO_SRC = "/_posts/files/"
AUDIO_DST = "https://raw.githubusercontent.com/steanlab/steanlab.github.io/main/_posts/files/"


def audio_url(url):
    if url.startswith(AUDIO_SRC):
        return AUDIO_DST + urllib.parse.quote(url[len(AUDIO_SRC):])
    return url


SUFFIX = re.compile(r"^web\s*archive\s*(.*)$", re.I)


def card_links(entry):
    """Ссылки карточки: kind (тип), label (дополнительная подпись или пусто), url. Кусочки текста без адреса пропускаются."""
    out = []
    for l in entry.get("links", []):
        if "url" not in l:
            continue
        kind = l.get("type", "other")
        label = str(l.get("label", ""))
        if kind == "web_archive":
            m = SUFFIX.match(label.strip())
            label = (m.group(1) if m else "").strip()
        elif kind == "archive_is":
            label = ""
        elif kind == "audio":
            label = "" if label.upper() == "AUDIO" else label
        elif kind == "language_version":
            label = label.strip("() ")
        out.append({"kind": kind, "label": label, "url": audio_url(l["url"]) if kind == "audio" else l["url"]})
    return out


def build_cards(media, added):
    rows = []
    counts = {}
    for order, (sec, e) in enumerate((s, e) for s in media["sections"] for e in s["entries"]):
        if "url" not in e or "title" not in e:
            continue
        got = entry_date(e, added)
        day, approx = got if got else ("", False)
        links = card_links(e)
        counts[sec["title"]] = counts.get(sec["title"], 0) + 1
        card = {"date": day, "approx": approx, "outlet": sec["title"], "title": e["title"], "url": e["url"],
                "audio": any(l["kind"] == "audio" for l in links),
                "search": (e["title"] + " " + sec["title"]).lower(), "links": links}
        rows.append((day, order, card))
    dated = sorted((r for r in rows if r[0]), key=lambda r: (r[0], r[1]), reverse=True)
    undated = [r for r in rows if not r[0]]
    cards = [r[2] for r in dated + undated]
    outlets = [{"name": n, "count": c} for n, c in sorted(counts.items(), key=lambda x: (-x[1], x[0].lower()))]
    return {"total": len(cards), "outlets": outlets, "cards": cards}


def dump(obj, header):
    return header + yaml.dump(obj, Dumper=yaml.SafeDumper, allow_unicode=True, sort_keys=False,
                              width=10 ** 9, default_flow_style=False)


CARDS_HEADER = ("# Собирается автоматически: python3 tools/make_latest.py (его вызывает tools/add_item.py).\n"
                "# Руками не править.\n")


def outputs(root):
    """{путь: текст} для всех генерируемых файлов."""
    return {
        "_data/latest.yml": dump(compute(root), HEADER),
        "_data/media_cards.yml": dump(build_cards(load(root, "_data/media.yml"), read_added(root)), CARDS_HEADER),
    }


def regenerate(root):
    paths = []
    for rel, text in outputs(root).items():
        path = os.path.join(root, rel)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        paths.append(path)
    return paths


def stale(root):
    bad = []
    for rel, text in outputs(root).items():
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            bad.append(rel)
            continue
        with open(path, encoding="utf-8", newline="") as f:
            if f.read() != text:
                bad.append(rel)
    return bad


def is_current(root):
    return not stale(root)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.check:
        bad = stale(a.root)
        print("служебные файлы " + ("актуальны" if not bad else "УСТАРЕЛИ: %s; выполните python3 tools/make_latest.py" % ", ".join(bad)))
        return 0 if not bad else 1
    for p in regenerate(a.root):
        print("записано:", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
