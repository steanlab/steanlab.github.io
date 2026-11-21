#!/usr/bin/env python3
"""Добавление нового интервью или публикации в _data/media.yml / _data/publications.yml.

  add     добавить запись в конец раздела (в разделах порядок «старые сверху»); по желанию сразу
          сохранить страницу в Wayback Machine и добавить ссылку WEBARCHIVE
  attach  добавить ссылку к существующей записи (например, ARCHIVE.IS после ручного сохранения или ODYSEE=https://odysee.com/…)

Примеры:
  python3 tools/add_item.py add --data media --section "Белсат" \\
      --title "Заголовок материала" --url https://example.org/a --archive
  python3 tools/add_item.py add --data publications --section "Серия «Слово о демосцене»" \\
      --title "..." --url https://... --mark P
  python3 tools/add_item.py add --data publications --new-section --level 2 --after "Тематические статьи: Химия" \\
      --section "Тематические статьи: Новая тема" --title "..." --url https://... --mark ST
  python3 tools/add_item.py attach --data media --url https://example.org/a --link ARCHIVE.IS=https://archive.is/AbCdE

Ключи Wayback (необязательно, с ними надёжнее): переменные окружения IA_ACCESS_KEY и IA_SECRET_KEY
(https://archive.org/account/s3.php). Без ключей используется обычное сохранение без авторизации.
archive.today официального API не имеет: скрипт печатает ссылку «в один клик», а готовый короткий
адрес добавляется командой attach.

Данные перезаписываются тем же дампером, что и при переносе (tools/archive_data.py), поэтому остальные
записи не меняются ни на байт. Перед записью проверяется, что собранный Markdown разбирается обратно в те же
данные и что адрес ещё не встречался на странице.
"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import archive_data as A  # noqa: E402
import make_latest as ML  # noqa: E402

DATA = {"media": "_data/media.yml", "publications": "_data/publications.yml"}
MARKS = A.MARK_CODES
SAVE_BASE = "https://web.archive.org"


def load(path):
    with open(path, encoding="utf-8") as f:
        d = yaml.safe_load(f)
    for s in d["sections"]:
        for e in s["entries"]:
            if "links" in e:
                e["links"] = [A.Flow(l) for l in e["links"]]
    return d


def all_urls(d):
    urls = set()
    for s in d["sections"]:
        for e in s["entries"]:
            if "url" in e:
                urls.add(e["url"])
            for l in e.get("links", []):
                if "url" in l:
                    urls.add(l["url"])
    return urls


def find_entry(d, url):
    hits = [e for s in d["sections"] for e in s["entries"] if e.get("url") == url]
    return hits[0] if len(hits) == 1 else None


def make_link(label, url):
    return A.Flow([("label", label), ("type", A.link_type(label, url)), ("url", url)])


def archive_today_link(url):
    """Ссылка «в один клик»: откроет archive.today и сразу запустит сохранение."""
    return "https://archive.ph/?run=1&url=" + urllib.parse.quote(url, safe="")


def save_wayback(url, base=SAVE_BASE, access=None, secret=None, wait=180, step=5, opener=None):
    """Сохраняет страницу в Wayback Machine и возвращает адрес снимка.
    С ключами — через Save Page Now 2 (POST /save, опрос /save/status/<id>); без них — GET /save/<url>."""
    op = opener or urllib.request.build_opener()
    if access and secret:
        body = urllib.parse.urlencode({"url": url, "capture_all": "1"}).encode()
        req = urllib.request.Request(base + "/save", data=body, headers={
            "Accept": "application/json", "Authorization": "LOW %s:%s" % (access, secret)})
        job = json.load(op.open(req, timeout=60))
        if "job_id" not in job:
            raise RuntimeError("Wayback не принял задание: %r" % (job,))
        t0 = time.time()
        while time.time() - t0 < wait:
            req = urllib.request.Request(base + "/save/status/" + job["job_id"], headers={
                "Accept": "application/json", "Authorization": "LOW %s:%s" % (access, secret)})
            st = json.load(op.open(req, timeout=60))
            if st.get("status") == "success":
                return "https://web.archive.org/web/%s/%s" % (st["timestamp"], st.get("original_url", url))
            if st.get("status") == "error":
                raise RuntimeError("Wayback: %s" % (st.get("message") or st,))
            time.sleep(step)
        raise RuntimeError("Wayback: не дождался завершения за %d с" % wait)
    req = urllib.request.Request(base + "/save/" + url, headers={"User-Agent": "Mozilla/5.0 (steanlab-site-src)"})
    resp = op.open(req, timeout=wait)
    loc = resp.headers.get("Content-Location") or resp.headers.get("Location") or ""
    if "/web/" not in loc:
        raise RuntimeError("Wayback не вернул адрес снимка (HTTP %s)" % resp.status)
    return loc if loc.startswith("http") else "https://web.archive.org" + loc


def self_check(d, src):
    """Собранный Markdown должен разбираться обратно в те же разделы и записи."""
    again = A.parse(A.render(d))
    def plain(x):
        return json.loads(json.dumps(x, ensure_ascii=False))
    if plain(again["sections"]) != plain(d["sections"]):
        raise SystemExit("самопроверка не пройдена: данные не переживают сборку Markdown и разбор обратно")


ADDED = "_data/added.yml"
ADDED_HEADER = ("# Когда запись была добавлена через форму issue: адрес материала → дата (ГГГГ-ММ-ДД). Пишет tools/add_item.py.\n"
                "# У записей, которых здесь нет, дата берётся из метки времени ссылки на веб-архив (≈ дата).\n")


def mark_added(root, url):
    """Запоминает дату добавления записи (для блока «Последнее добавленное» на главной)."""
    path = os.path.join(root, ADDED)
    cur = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cur = yaml.safe_load(f) or {}
    day = os.environ.get("ADDED_DATE") or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    cur[url] = day
    text = ADDED_HEADER + yaml.dump(cur, Dumper=yaml.SafeDumper, allow_unicode=True, sort_keys=False,
                                     width=10 ** 9, default_flow_style=False)
    A.write(path, text)


def save_data(d, key, root, added_url=None):
    src = "_posts/2014-3-2-interview.md" if key == "media" else "_posts/2014-3-3-bibliography.md"
    self_check(d, src)
    A.write(os.path.join(root, DATA[key]), A.dump_yaml(d, src))
    if added_url:
        mark_added(root, added_url)
    ML.regenerate(root)


def new_section(d, title, level=1, after=None):
    """Создаёт пустой раздел и вставляет его после раздела `after` (None — в конец). Название должно быть новым:
    одинаковые заголовки на странице получают разные якоря и портят оглавление."""
    if any(s["title"] == title for s in d["sections"]):
        raise SystemExit("раздел «%s» уже существует" % title)
    if level not in (1, 2, 3):
        raise SystemExit("уровень раздела: 1, 2 или 3")
    sec = {"title": title, "level": level, "entries": []}
    if after is None:
        d["sections"].append(sec)
    else:
        idx = [i for i, s in enumerate(d["sections"]) if s["title"] == after]
        if len(idx) != 1:
            raise SystemExit("не найден раздел «%s», после которого нужно вставить новый" % after)
        d["sections"].insert(idx[0] + 1, sec)
    return sec


def cmd_add(a, wayback=save_wayback):
    path = os.path.join(a.root, DATA[a.data])
    d = load(path)
    if a.url in all_urls(d):
        raise SystemExit("этот адрес уже есть в данных: " + a.url)
    if getattr(a, "new_section", False):
        sec = new_section(d, a.section, getattr(a, "level", 1), getattr(a, "after", None))
        secs = [sec]
    else:
        secs = [s for s in d["sections"] if s["title"] == a.section]
    if len(secs) != 1:
        names = "\n  ".join(s["title"] for s in d["sections"])
        raise SystemExit("раздел «%s» найден %d раз. Разделы:\n  %s" % (a.section, len(secs), names))
    if a.mark and a.mark not in MARKS:
        raise SystemExit("метка может быть только %s" % ", ".join(MARKS))
    e = {}
    if a.mark:
        e["mark"] = a.mark
    e["title"], e["url"] = a.title, a.url
    links = []
    if a.archive:
        snap = wayback(a.url, access=os.environ.get("IA_ACCESS_KEY"), secret=os.environ.get("IA_SECRET_KEY"))
        links.append(make_link("WEBARCHIVE", snap))
        print("Wayback:", snap)
    for item in a.link or []:
        label, _, url = item.partition("=")
        if not url:
            raise SystemExit("--link ожидает ПОДПИСЬ=АДРЕС")
        links.append(make_link(label, url))
    if links:
        e["links"] = links
    secs[0]["entries"].append(e)
    if a.dry_run:
        self_check(d, "")
        print("(пробный запуск, файл не записан)")
    else:
        save_data(d, a.data, a.root, added_url=a.url)
        print("добавлено в", DATA[a.data], "→ раздел «%s»" % a.section)
    print("archive.today, один клик:", archive_today_link(a.url))
    print("потом: python3 tools/add_item.py attach --data %s --url %s --link ARCHIVE.IS=https://archive.is/КОД" % (a.data, a.url))


def cmd_attach(a):
    path = os.path.join(a.root, DATA[a.data])
    d = load(path)
    e = find_entry(d, a.url)
    if e is None:
        raise SystemExit("запись с адресом %s не найдена (или найдена не одна)" % a.url)
    used = all_urls(d)
    for item in a.link:
        label, _, url = item.partition("=")
        if not url:
            raise SystemExit("--link ожидает ПОДПИСЬ=АДРЕС")
        if url in used:
            raise SystemExit("адрес уже есть в данных: " + url)
        e.setdefault("links", []).append(make_link(label, url))
    if not a.dry_run:
        save_data(d, a.data, a.root)
    print("ссылки добавлены" if not a.dry_run else "(пробный запуск)")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("add", "attach"):
        s = sub.add_parser(name)
        s.add_argument("--data", choices=sorted(DATA), required=True)
        s.add_argument("--root", default=".")
        s.add_argument("--dry-run", action="store_true")
        s.add_argument("--url", required=True)
        s.add_argument("--link", action="append", help="ПОДПИСЬ=АДРЕС, можно несколько раз")
        if name == "add":
            s.add_argument("--section", required=True, help="название раздела (с --new-section — название нового)")
            s.add_argument("--new-section", action="store_true", help="создать раздел с этим названием")
            s.add_argument("--level", type=int, default=1, help="уровень заголовка нового раздела (1–3)")
            s.add_argument("--after", help="вставить новый раздел после раздела с этим названием (по умолчанию — в конец)")
            s.add_argument("--title", required=True)
            s.add_argument("--mark")
            s.add_argument("--archive", action="store_true", help="сохранить в Wayback Machine и добавить WEBARCHIVE")
    a = p.parse_args(argv)
    if a.cmd == "attach" and not a.link:
        p.error("для attach нужен хотя бы один --link")
    {"add": cmd_add, "attach": cmd_attach}[a.cmd](a)


if __name__ == "__main__":
    main()
