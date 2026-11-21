#!/usr/bin/env python3
"""Добавление записей через форму issue на GitHub.

  issue_bot.py forms [--check] [--root .]   сгенерировать (или проверить) формы .github/ISSUE_TEMPLATE/*.yml
                                            из разделов _data/*.yml (список разделов в форме — выпадающий)
  issue_bot.py run --event FILE --out DIR   обработать событие GitHub Actions (issues.opened или issue_comment.created)

Что делает run:
  * issues.opened с формой «новое интервью» / «новая публикация» → добавляет запись в _data/*.yml,
    при выборе «Да» сохраняет адрес в Wayback Machine и добавляет ссылку WEBARCHIVE (если не вышло — запись
    всё равно добавляется, а в комментарии сказано, что архив не сохранился);
  * issue_comment.created с адресом archive.today (archive.is/.ph/.today…) → добавляет ссылку ARCHIVE.IS к записи
    из этой задачи и закрывает задачу;
  * issue_comment.created с адресом https://odysee.com/… → добавляет ссылку ODYSEE (резервная копия видео) к записи
    из этой задачи; задача остаётся открытой. Тот же адрес можно указать сразу в поле формы «Резервная копия на Odysee».
Принимаются только события от владельца репозитория (REPO_OWNER). Текст задачи считается недоверенными данными:
он разбирается этим скриптом и проверяется, в командную строку не подставляется.
"""
import argparse
import io
import json
import os
import re
import sys
import types
from contextlib import redirect_stdout

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import add_item as T  # noqa: E402
import archive_data as A  # noqa: E402

F_SECTION = "Раздел"
F_NEWSEC = "Название нового раздела"
F_LEVEL = "Уровень нового раздела"
F_AFTER = "Вставить новый раздел после"
NEW_SECTION = "➕ Новый раздел (название — в поле ниже)"
LEVELS = {"основной (заголовок 1-го уровня)": 1, "подраздел (2-го уровня)": 2}
# для какой страницы сколько разделов с конца пропустить в «после какого раздела вставить» по умолчанию:
# у публикаций последний раздел — «Пару авторских замечаний» (поддержка, кошельки), новые разделы идут перед ним
AFTER_FROM_END = {"media": 0, "publications": 1}
F_TITLE = "Название материала"
F_URL = "Адрес материала (URL)"
F_MARK = "Метка (как в текущем списке)"
F_LINKS = "Дополнительные ссылки"
F_ARCHIVE = "Сохранить в Wayback Machine"
F_ODYSEE = "Резервная копия на Odysee (URL)"
YES, NO = "Да", "Нет"
NO_MARK = "без метки"
MARK_SEP = " — "
NO_RESPONSE = "_No response_"
FORMS = {
    "media": ("new-interview.yml", "Новое интервью или комментарий в СМИ", "[Интервью] ", "new-interview"),
    "publications": ("new-publication.yml", "Новая публикация", "[Публикация] ", "new-publication"),
}
ODYSEE_URL = re.compile(r"https://odysee\.com/[^\s<>\"'\[\]{}|\\^`)]+")
ODYSEE_FIELD_OK = re.compile(r"^https://odysee\.com/[^\s<>\"'\[\]{}|\\^`]+$")
ARCHIVE_URL = re.compile(r"https?://(?:www\.)?archive\.(?:is|ph|today|md|fo|li|vn)/[A-Za-z0-9]{3,12}\b")
URL_OK = re.compile(r"^https?://[^\s<>\"'\[\]{}|\\^`]+$")
LINK_URL_OK = re.compile(r"^(https?://[^\s<>\"'\[\]{}|\\^`]+|/_posts/files/[^\s<>\"'\[\]{}|\\^`]+)$")
LABEL_OK = re.compile(r"^[A-Za-z0-9А-Яа-яЁёІіЎў .\-_()]{1,30}$")


# ------------------------------------------------------------------ формы
def section_titles(root, key):
    with open(os.path.join(root, T.DATA[key]), encoding="utf-8") as f:
        d = yaml.safe_load(f)
    titles = [s["title"] for s in d["sections"]]
    if len(set(titles)) != len(titles):
        raise SystemExit("в %s есть одинаковые названия разделов: форма их не примет" % T.DATA[key])
    return titles


def load_marks(root):
    with open(os.path.join(root, "_data", "marks.yml"), encoding="utf-8") as f:
        marks = yaml.safe_load(f)
    if tuple(m["code"] for m in marks) != A.MARK_CODES:
        raise SystemExit("_data/marks.yml и MARK_CODES в tools/archive_data.py расходятся")
    return marks


def mark_options(marks):
    return [NO_MARK] + ["%s%s%s" % (m["code"], MARK_SEP, m["name"]) for m in marks]


def build_form(key, titles, marks):
    fname, name, prefix, label = FORMS[key]
    body = [
        {"type": "markdown", "attributes": {"value": "Запись будет добавлена на страницу автоматически. "
         "Название — на языке оригинала, как в источнике."}},
        {"type": "dropdown", "id": "section", "attributes": {"label": F_SECTION, "options": [NEW_SECTION] + titles},
         "validations": {"required": True}},
        {"type": "input", "id": "title", "attributes": {"label": F_TITLE},
         "validations": {"required": True}},
        {"type": "input", "id": "url", "attributes": {"label": F_URL, "placeholder": "https://"},
         "validations": {"required": True}},
    ]
    if key == "publications":
        body.append({"type": "dropdown", "id": "mark", "attributes": {
            "label": F_MARK, "description": "Где опубликован текст; на странице метка стоит перед названием.",
            "options": mark_options(marks), "default": 0}})
    if key == "media":
        body.append({"type": "input", "id": "odysee", "attributes": {
            "label": F_ODYSEE, "description": "Свой ролик на Odysee как резервная ссылка, если видео пропадёт с YouTube (необязательно).",
            "placeholder": "https://odysee.com/…"}})
    body += [
        {"type": "textarea", "id": "links", "attributes": {
            "label": F_LINKS, "description": "По одной на строку: ПОДПИСЬ=АДРЕС, например RU=https://… (необязательно)"}},
        {"type": "dropdown", "id": "wayback", "attributes": {
            "label": F_ARCHIVE, "options": [YES, NO], "default": 0}},
    ]
    # создание нового раздела: заполняется, только если сверху выбран пункт «Новый раздел»
    new = [{"type": "input", "id": "new_section", "attributes": {
        "label": F_NEWSEC, "description": "Только если выбран пункт «Новый раздел» (в этом поле — название заголовка)."}}]
    if key == "publications":
        new.append({"type": "dropdown", "id": "level", "attributes": {
            "label": F_LEVEL, "options": list(LEVELS), "default": 1}})
    default_after = max(0, len(titles) - 1 - AFTER_FROM_END[key])
    new.append({"type": "dropdown", "id": "after", "attributes": {
        "label": F_AFTER, "description": "Только для нового раздела: он встанет сразу после выбранного.",
        "options": titles, "default": default_after}})
    body.append({"type": "markdown", "attributes": {"value": "**Новый раздел** — только если сверху выбран пункт «Новый раздел»."}})
    body += new
    return {"name": name, "description": "Добавить запись на страницу", "title": prefix, "labels": [label], "body": body}


def dump_form(form):
    return yaml.safe_dump(form, allow_unicode=True, sort_keys=False, width=10 ** 9)


def all_forms(root):
    out = {}
    for key in FORMS:
        out[os.path.join(".github", "ISSUE_TEMPLATE", FORMS[key][0])] = dump_form(build_form(key, section_titles(root, key), load_marks(root)))
    out[os.path.join(".github", "ISSUE_TEMPLATE", "config.yml")] = "blank_issues_enabled: false\n"
    return out


def cmd_forms(a):
    bad = False
    for rel, text in all_forms(a.root).items():
        path = os.path.join(a.root, rel)
        if a.check:
            cur = open(path, encoding="utf-8").read() if os.path.exists(path) else None
            print("%-48s %s" % (rel, "актуальна" if cur == text else "УСТАРЕЛА (перегенерируйте: forms)"))
            bad |= cur != text
        else:
            A.write(path, text)
            print("записано", rel)
    sys.exit(1 if bad else 0)


# ------------------------------------------------------------ разбор задачи
def parse_body(body):
    """Тело задачи из формы GitHub: блоки «### Поле» + значение. -> dict поле → текст ('' если не заполнено)."""
    fields, cur, buf = {}, None, []
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        if line.startswith("### "):
            if cur is not None:
                fields[cur] = "\n".join(buf).strip()
            cur, buf = line[4:].strip(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        fields[cur] = "\n".join(buf).strip()
    return {k: ("" if v == NO_RESPONSE else v) for k, v in fields.items()}


def balanced(s, a, b):
    n = 0
    for ch in s:
        n += (ch == a) - (ch == b)
        if n < 0:
            return False
    return n == 0


def validate_section_title(t):
    if not t or "\n" in t or len(t) > 200:
        raise ValueError("название нового раздела должно быть одной строкой до 200 символов")
    if t.startswith("#") or not balanced(t, "[", "]"):
        raise ValueError("название раздела не должно начинаться с «#» и содержать незакрытые скобки")
    return t


def validate(f):
    title, url = f.get(F_TITLE, ""), f.get(F_URL, "")
    if not title or "\n" in title or len(title) > 400:
        raise ValueError("название должно быть одной строкой до 400 символов")
    if not balanced(title, "[", "]"):
        raise ValueError("в названии не закрыта квадратная скобка")
    if not URL_OK.match(url) or len(url) > 2000 or not balanced(url, "(", ")"):
        raise ValueError("адрес должен начинаться с http:// или https://, без пробелов и с парными скобками")
    links = []
    for line in f.get(F_LINKS, "").split("\n"):
        line = line.strip()
        if not line:
            continue
        label, _, lurl = line.partition("=")
        label, lurl = label.strip(), lurl.strip()
        if not LABEL_OK.match(label) or not LINK_URL_OK.match(lurl) or not balanced(lurl, "(", ")"):
            raise ValueError("дополнительная ссылка не разобрана: «%s» (нужно ПОДПИСЬ=АДРЕС)" % line[:80])
        links.append("%s=%s" % (label, lurl))
    odysee = f.get(F_ODYSEE, "").strip()
    if odysee:
        if not ODYSEE_FIELD_OK.match(odysee) or len(odysee) > 2000 or not balanced(odysee, "(", ")"):
            raise ValueError("ссылка на Odysee должна начинаться с https://odysee.com/ и не содержать пробелов")
        links.append("ODYSEE=" + odysee)
    return title, url, links


def find_kind(root, f, labels, issue_title=""):
    for key, (_, _, prefix, label) in FORMS.items():
        if label in labels or (issue_title or "").startswith(prefix):
            return key
    sec = f.get(F_SECTION, "")
    hits = [k for k in FORMS if sec in section_titles(root, k)]
    if len(hits) != 1:
        raise ValueError("не удалось определить, интервью это или публикация (раздел «%s»)" % sec)
    return hits[0]


# ------------------------------------------------------------------ события
class Result:
    def __init__(self):
        self.changed = False
        self.close = False
        self.comment = ""
        self.commit = ""


def handle_issue(ev, root, wayback):
    r = Result()
    issue = ev["issue"]
    f = parse_body(issue.get("body"))
    if F_SECTION not in f or F_URL not in f:
        return r                                   # не наша форма
    labels = [l["name"] for l in issue.get("labels", [])]
    try:
        key = find_kind(root, f, labels, issue.get("title", ""))
        title, url, links = validate(f)
        mark = f.get(F_MARK, "")
        mark = "" if mark in ("", NO_MARK) else mark.split(MARK_SEP)[0].strip()
        is_new = f[F_SECTION] == NEW_SECTION
        section, level, after = f[F_SECTION], 1, None
        if is_new:
            section = validate_section_title(f.get(F_NEWSEC, ""))
            level = LEVELS.get(f.get(F_LEVEL, ""), 1) if key == "publications" else 1
            after = f.get(F_AFTER) or None
        extra = list(links)
        note = ""
        if f.get(F_ARCHIVE, YES) == YES:
            try:
                snap = wayback(url, access=os.environ.get("IA_ACCESS_KEY"), secret=os.environ.get("IA_SECRET_KEY"))
                extra.insert(0, "WEBARCHIVE=" + snap)
                note = "Wayback Machine: %s" % snap
            except Exception as e:                  # запись не теряем, даже если архив не сохранился
                note = "Wayback Machine: сохранить не удалось (%s). Запись добавлена без ссылки WEBARCHIVE." % str(e)[:200]
        a = types.SimpleNamespace(data=key, root=root, section=section, title=title, url=url,
                                  mark=mark or None, archive=False, link=extra, dry_run=False,
                                  new_section=is_new, level=level, after=after)
        buf = io.StringIO()
        with redirect_stdout(buf):
            T.cmd_add(a, wayback=wayback)
    except (ValueError, SystemExit) as e:
        r.comment = "Запись не добавлена: %s\n\nИсправьте задачу или создайте новую." % (str(e).split("\n")[0])
        return r
    r.changed, r.close = True, False
    r.commit = "Добавлено: %s (%s)" % (title[:80], T.DATA[key])
    r.comment = "\n".join([
        "Запись добавлена в `%s`, %s «%s»." % (T.DATA[key], "новый раздел" if is_new else "раздел", section),
        note,
        "",
        "archive.today (официального API нет, нужен один клик): [сохранить страницу](%s)." % T.archive_today_link(url),
        "Когда снимок будет готов, ответьте в этой задаче комментарием с коротким адресом (например `https://archive.is/AbCdE`) — "
        "ссылка ARCHIVE.IS добавится к записи.",
        "Резервную копию на Odysee можно добавить позже: ответьте комментарием с адресом `https://odysee.com/…` — "
        "добавится ссылка ODYSEE.",
    ]).strip()
    return r


def handle_comment(ev, root):
    r = Result()
    issue, comment = ev["issue"], ev["comment"]
    f = parse_body(issue.get("body"))
    if F_SECTION not in f or F_URL not in f:
        return r
    text = comment.get("body", "")
    m = ARCHIVE_URL.search(text)
    od = None if m else ODYSEE_URL.search(text)
    if not m and not od:
        return r
    labels = [l["name"] for l in issue.get("labels", [])]
    try:
        key = find_kind(root, f, labels, issue.get("title", ""))
        _, url, _ = validate(f)
        new_link = "ARCHIVE.IS=" + m.group(0) if m else "ODYSEE=" + od.group(0)
        a = types.SimpleNamespace(data=key, root=root, url=url, link=[new_link], dry_run=False)
        with redirect_stdout(io.StringIO()):
            T.cmd_attach(a)
    except (ValueError, SystemExit) as e:
        r.comment = "Ссылка не добавлена: %s" % str(e).split("\n")[0]
        return r
    if m:
        r.changed, r.close = True, True
        r.commit = "Добавлена ссылка ARCHIVE.IS (%s)" % T.DATA[key]
        r.comment = "Ссылка ARCHIVE.IS добавлена к записи. Задача закрыта."
    else:
        r.changed, r.close = True, False       # задачу не закрываем: ещё может понадобиться ARCHIVE.IS
        r.commit = "Добавлена ссылка ODYSEE (%s)" % T.DATA[key]
        r.comment = "Ссылка ODYSEE добавлена к записи."
    return r


def cmd_run(a, wayback=T.save_wayback):
    ev = json.load(open(a.event, encoding="utf-8"))
    owner = os.environ.get("REPO_OWNER", "")
    sender = (ev.get("sender") or {}).get("login", "")
    author = (ev.get("comment") or ev.get("issue") or {}).get("user", {}).get("login", "")
    if not owner or sender != owner or author != owner:
        print("событие не от владельца репозитория, пропуск")
        r = Result()
    elif "comment" in ev:
        r = handle_comment(ev, a.root)
    elif ev.get("action") == "opened" and "issue" in ev:
        r = handle_issue(ev, a.root, wayback)
    else:
        r = Result()
    os.makedirs(a.out, exist_ok=True)
    A.write(os.path.join(a.out, "comment.md"), r.comment + ("\n" if r.comment else ""))
    A.write(os.path.join(a.out, "commit.txt"), r.commit + "\n")
    lines = "changed=%s\nclose=%s\nhas_comment=%s\n" % (
        str(r.changed).lower(), str(r.close).lower(), str(bool(r.comment)).lower())
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a", encoding="utf-8") as fh:
            fh.write(lines)
    print(lines, end="")
    return r


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("forms")
    f.add_argument("--root", default=".")
    f.add_argument("--check", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--event", required=True)
    r.add_argument("--root", default=".")
    r.add_argument("--out", required=True)
    a = p.parse_args(argv)
    cmd_forms(a) if a.cmd == "forms" else cmd_run(a)


if __name__ == "__main__":
    main()
