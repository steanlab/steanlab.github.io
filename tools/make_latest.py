#!/usr/bin/env python3
"""Собирает _data/latest.yml: последние добавленные записи из _data/media.yml и _data/publications.yml
(для блока «Последнее добавленное» на главной).

Дата записи:
  1) если адрес материала есть в _data/added.yml, то дата из него (записи, добавленные через форму);
  2) иначе самая ранняя метка времени среди ссылок на Wayback Machine (web.archive.org/web/ГГГГММДДччммсс/...);
     такая дата приблизительная (approx: true), на сайте она показывается со значком ≈;
  3) записи без даты в список не попадают.
Порядок: дата по убыванию; при равной дате позже стоящая в файле запись выше. В файл попадают LIMIT записей.

  python3 tools/make_latest.py           пересобрать _data/latest.yml
  python3 tools/make_latest.py --check   только проверить, что файл актуален (код выхода 1, если нет)
"""
import argparse
import os
import re
import sys

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


def compute(root):
    media = load(root, "_data/media.yml")
    pubs = load(root, "_data/publications.yml")
    p = os.path.join(root, "_data/added.yml")
    added = (load(root, "_data/added.yml") if os.path.exists(p) else None) or {}
    return build(media, pubs, added)


def render(items):
    return HEADER + yaml.dump(items, Dumper=yaml.SafeDumper, allow_unicode=True, sort_keys=False,
                              width=10 ** 9, default_flow_style=False)


def regenerate(root):
    text = render(compute(root))
    path = os.path.join(root, "_data", "latest.yml")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def is_current(root):
    path = os.path.join(root, "_data", "latest.yml")
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8", newline="") as f:
        return f.read() == render(compute(root))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.check:
        ok = is_current(a.root)
        print("_data/latest.yml " + ("актуален" if ok else "УСТАРЕЛ: выполните python3 tools/make_latest.py"))
        return 0 if ok else 1
    print("записано:", regenerate(a.root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
