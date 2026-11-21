#!/usr/bin/env python3
"""Проверка шаблона _layouts/archive.html без Jekyll.

Здесь нет Jekyll и Liquid, поэтому тело шаблона (до тега <article>) исполняется мини-интерпретатором
подмножества Liquid (assign, capture, for, if/elsif/else, unless, comment, вывод значений, обрезка
пробелов `{%-` и `-%}`). Результат — Markdown, который Jekyll передал бы в markdownify.
Он сравнивается СТРОГО (байт в байт) с тем, что собирает tools/archive_data.py (render) из тех же
данных, после замены вводного абзаца и слова «СОДЕРЖАНИЕ» на тексты выбранного языка.
Это проверка логики шаблона, а не замена сборки Jekyll: настоящая сборка проверяется на GitHub Pages.
"""
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import archive_data as A  # noqa: E402

TOKEN = re.compile(r"(\{%-?.*?-?%\}|\{\{-?.*?-?\}\})", re.S)


def tokenize(src):
    out = []
    for part in TOKEN.split(src):
        if not part:
            continue
        if part.startswith("{%") or part.startswith("{{"):
            kind = "tag" if part.startswith("{%") else "out"
            left = part[2] == "-"
            right = part[-3] == "-"
            body = part[2 + left:len(part) - 2 - right].strip()
            out.append([kind, body, left, right])
        else:
            out.append(["text", part, False, False])
    # обрезка пробелов только в соседних текстовых узлах
    for i, t in enumerate(out):
        if t[0] == "text":
            continue
        if t[2] and i > 0 and out[i - 1][0] == "text":
            out[i - 1][1] = out[i - 1][1].rstrip()
        if t[3] and i + 1 < len(out) and out[i + 1][0] == "text":
            out[i + 1][1] = out[i + 1][1].lstrip()
    return [tuple(t[:2]) for t in out if not (t[0] == "text" and t[1] == "")]


def parse(tokens):
    """-> дерево: ('text',s) ('out',expr) ('assign',name,expr) ('capture',name,body) ('for',v,expr,body)
    ('if',[(cond,body),...,(None,body)]) ('unless',cond,body)"""
    pos = 0

    def block(stop):
        nonlocal pos
        nodes = []
        while pos < len(tokens):
            kind, body = tokens[pos]
            if kind == "text":
                nodes.append(("text", body)); pos += 1; continue
            if kind == "out":
                nodes.append(("out", body)); pos += 1; continue
            word = body.split(None, 1)[0]
            if word in stop:
                return nodes
            pos += 1
            if word == "assign":
                m = re.fullmatch(r"assign\s+(\w+)\s*=\s*(.*)", body, re.S)
                nodes.append(("assign", m.group(1), m.group(2).strip()))
            elif word == "capture":
                name = body.split()[1]
                inner = block({"endcapture"}); pos += 1
                nodes.append(("capture", name, inner))
            elif word == "comment":
                block({"endcomment"}); pos += 1
            elif word == "for":
                m = re.fullmatch(r"for\s+(\w+)\s+in\s+(.*)", body)
                inner = block({"endfor"}); pos += 1
                nodes.append(("for", m.group(1), m.group(2).strip(), inner))
            elif word in ("if", "unless"):
                branches = []
                cond = body.split(None, 1)[1]
                while True:
                    inner = block({"elsif", "else", "endif", "endunless"})
                    branches.append((cond, inner))
                    k, b = tokens[pos]; pos += 1
                    w = b.split(None, 1)[0]
                    if w == "elsif":
                        cond = b.split(None, 1)[1]
                    elif w == "else":
                        cond = None
                    else:
                        break
                nodes.append((word, branches))
            else:
                raise SystemExit("неподдерживаемый тег: " + body)
        return nodes

    tree = block(set())
    return tree


def lookup(ctx, expr):
    expr = expr.strip()
    if expr in ("nil", "null"):
        return None
    if expr in ("true", "false"):
        return expr == "true"
    if len(expr) >= 2 and expr[0] == expr[-1] and expr[0] in "\"'":
        return expr[1:-1]
    if re.fullmatch(r"-?\d+", expr):
        return int(expr)
    # путь вида a.b[c].d
    parts = re.findall(r"[\w\-]+|\[[^\]]+\]", expr)
    if not parts or not re.fullmatch(r"[\w\-]+(\.[\w\-]+|\[[^\]]+\])*", expr):
        raise SystemExit("не разобрал выражение: " + expr)
    cur = ctx.get(parts[0])
    for p in parts[1:]:
        if cur is None:
            return None
        if p.startswith("["):
            p = lookup(ctx, p[1:-1])
        if isinstance(cur, dict):
            cur = cur.get(p)
        elif isinstance(cur, list) and p == "size":
            cur = len(cur)
        else:
            return None
    return cur


def truthy(v):
    return v is not None and v is not False


def cond_eval(ctx, c):
    # в шаблоне используются простые условия и одиночное «or»; and/or в Liquid вычисляются справа налево
    if " or " in c:
        left, right = c.split(" or ", 1)
        return cond_eval(ctx, left) or cond_eval(ctx, right)
    if " and " in c:
        left, right = c.split(" and ", 1)
        return cond_eval(ctx, left) and cond_eval(ctx, right)
    m = re.fullmatch(r"(.+?)\s*(==|!=)\s*(.+)", c)
    if m:
        a, b = lookup(ctx, m.group(1)), lookup(ctx, m.group(3))
        return (a == b) if m.group(2) == "==" else (a != b)
    return truthy(lookup(ctx, c))


def evaluate(ctx, expr):
    """Значение выражения с фильтрами `| plus: N` и `| default: X` (остальные фильтры игнорируются)."""
    parts = [x.strip() for x in expr.split("|")]
    v = lookup(ctx, parts[0])
    for f in parts[1:]:
        name, _, arg = f.partition(":")
        name, arg = name.strip(), arg.strip()
        if name == "plus":
            v = (v or 0) + lookup(ctx, arg)
        elif name == "default":
            v = v if truthy(v) and v != "" else lookup(ctx, arg)
    return v


def run(nodes, ctx):
    out = []
    for n in nodes:
        k = n[0]
        if k == "text":
            out.append(n[1])
        elif k == "out":
            v = evaluate(ctx, n[1])
            out.append("" if v is None else str(v))
        elif k == "assign":
            ctx[n[1]] = evaluate(ctx, n[2])
        elif k == "capture":
            ctx[n[1]] = run(n[2], ctx)
        elif k == "for":
            src_expr, lim = n[2], None
            m = re.fullmatch(r"(.*?)\s+limit:\s*(\d+)", src_expr)
            if m:
                src_expr, lim = m.group(1), int(m.group(2))
            items = lookup(ctx, src_expr) or []
            for item in (items[:lim] if lim is not None else items):
                ctx[n[1]] = item
                out.append(run(n[3], ctx))
        elif k == "if":
            for cond, body in n[1]:
                if cond is None or cond_eval(ctx, cond):
                    out.append(run(body, ctx)); break
        elif k == "unless":
            cond, body = n[1][0]
            if not cond_eval(ctx, cond):
                out.append(run(body, ctx))
    return "".join(out) if all(isinstance(x, str) for x in out) else "".join(
        x if isinstance(x, str) else str(x) for x in out)


def render_layout(path, ctx):
    src = open(path, encoding="utf-8").read()
    src = re.sub(r"\A---\n.*?\n---\n", "", src, flags=re.S)
    head = src.split("<article", 1)[0]          # всё до разметки страницы — это сборка Markdown
    tree = parse(tokenize(head))
    c = dict(ctx)
    run(tree, c)
    return c["md"]


def render_body(path, ctx):
    """Исполняет весь файл шаблона (без front matter) и возвращает текст; для проверки главной."""
    src = open(path, encoding="utf-8").read()
    src = re.sub(r"\A---\n.*?\n---\n", "", src, flags=re.S)
    return run(parse(tokenize(src)), dict(ctx))


def check_home(root, i18n):
    """Числа на главной должны совпасть с подсчётом из данных на Python для каждого языка."""
    media = yaml.safe_load(open(os.path.join(root, "_data", "media.yml"), encoding="utf-8"))
    facts = yaml.safe_load(open(os.path.join(root, "_data", "facts.yml"), encoding="utf-8"))
    recs = [e for s in media["sections"] for e in s["entries"] if "url" in e]
    copies = sum(1 for e in recs for l in e.get("links", []) if l.get("type") in ("web_archive", "archive_is"))
    ok = True
    for lang in ("en", "ru", "be"):
        latest = yaml.safe_load(open(os.path.join(root, "_data", "latest.yml"), encoding="utf-8"))
        ctx = {"site": {"data": {"media": media, "facts": facts, "i18n": i18n, "latest": latest},
                        "footer-links": {"email": "x@example.org"}},
               "page": {"lang": lang}, "content": ""}
        out = render_body(os.path.join(root, "_layouts", "home.html"), ctx)
        got = re.findall(r'<div class="stat-n">(.*?)</div><div class="stat-l">(.*?)</div>', out)
        want = [(str(len(recs)), i18n[lang]["stat_records"]), (str(copies), i18n[lang]["stat_copies"]),
                (str(facts["patents"]), i18n[lang]["stat_patents"]), (str(facts["texts"]), i18n[lang]["stat_texts"])]
        same = got == want
        urls = re.findall(r'<h3><a href="(.*?)">', out)
        same &= urls == [r["url"] for r in latest[:4]]
        same &= "{{" not in out and "{%" not in out and 'href="mailto:x@example.org"' in out
        print("главная       %-3s %s  %s" % (lang, "совпало" if same else "РАСХОЖДЕНИЕ", [g[0] for g in got]))
        ok &= same
    return ok


def check_media(root, i18n):
    """Страница СМИ: карточки в порядке _data/media_cards.yml, все адреса и ссылки на месте, подписи на языке страницы."""
    cards = yaml.safe_load(open(os.path.join(root, "_data", "media_cards.yml"), encoding="utf-8"))
    media = yaml.safe_load(open(os.path.join(root, "_data", "media.yml"), encoding="utf-8"))
    src_urls = sorted(e["url"] for s in media["sections"] for e in s["entries"] if "url" in e)
    ok = sorted(c["url"] for c in cards["cards"]) == src_urls and cards["total"] == len(src_urls)
    print("media_cards   все %d адресов из media.yml на месте: %s" % (len(src_urls), "да" if ok else "НЕТ"))
    for lang in ("en", "ru", "be"):
        ctx = {"site": {"data": {"media_cards": cards, "i18n": i18n}}, "page": {"lang": lang, "title": "T"}}
        out = render_body(os.path.join(root, "_layouts", "media.html"), ctx)
        body = out.split("<script>", 1)[0]
        rows = re.findall(r'<article class="row" ', body)
        urls = re.findall(r'<h2><a href="(.*?)">', body)
        t = i18n[lang]
        chips_audio = body.count('<span class="chip">%s</span>' % t["badge_audio"])
        src_labels = body.count(">%s</a>" % t["l_src"])
        same = (len(rows) == cards["total"] and urls == [c["url"] for c in cards["cards"]]
                and chips_audio == sum(c["audio"] for c in cards["cards"]) and src_labels == cards["total"]
                and "{{" not in body and "{%" not in body)
        n_links = len(re.findall(r'<div class="links">.*?</div>', body, re.S))
        total_links = sum(len(re.findall(r"<a ", m)) for m in re.findall(r'<div class="links">.*?</div>', body, re.S))
        want_links = sum(1 + sum(1 for l in c["links"] if l["kind"] != "audio") for c in cards["cards"])
        players = len(re.findall(r'<audio controls preload="none" src="', body))
        same &= players == sum(1 for c in cards["cards"] for l in c["links"] if l["kind"] == "audio")
        same &= total_links == want_links and n_links == cards["total"]
        print("media         %-3s %s  (%d карточек, %d ссылок)" % (lang, "совпало" if same else "РАСХОЖДЕНИЕ", len(rows), total_links))
        ok &= same
    return ok


def check_static(root, i18n):
    """Статические проверки шаблонов: опечатки `%%`, переменные во внутренних слоях, ключи i18n, latest.yml."""
    ok = True
    files = []
    for d in ("_layouts", "_includes"):
        for f in sorted(os.listdir(os.path.join(root, d))):
            files.append(os.path.join(d, f))
    for f in ("about.md", "projects.md", "bibliography.md", "interview.md"):
        files.append(f)
    for lang in ("ru", "be"):
        for f in sorted(os.listdir(os.path.join(root, lang))):
            files.append(os.path.join(lang, f))
    bad = []
    used = set()
    for f in files:
        src = open(os.path.join(root, f), encoding="utf-8").read()
        if "{%%" in src or "%%}" in src:
            bad.append(f + ": найдено «%%»")
        for tag in re.findall(r"\{\{.*?\}\}|\{%.*?%\}", src, re.S):
            for k in re.findall(r"(?<![\w.])t\.([a-z_0-9]+)", tag):
                used.add(k)
    print("шаблоны: «%%» не найдено" if not bad else "шаблоны: ОШИБКИ " + "; ".join(bad))
    ok &= not bad
    # внутренние слои (layout: default) рисуются раньше внешнего: lang/t/home задаём в каждом сами
    for f in sorted(os.listdir(os.path.join(root, "_layouts"))):
        src = open(os.path.join(root, "_layouts", f), encoding="utf-8").read()
        body = re.sub(r"\{%-?\s*assign .*?-?%\}", "", src, flags=re.S)
        tags = " ".join(re.findall(r"\{\{.*?\}\}|\{%.*?%\}", body, re.S))
        for var, pat in (("t", r"(?<![\w.])t\."), ("home", r"(?<![\w.])home\b"), ("lang", r"(?<![\w.])lang\b")):
            if re.search(pat, tags) and ("assign %s =" % var) not in src and f != "default.html" or (
                    f == "default.html" and re.search(pat, tags) and ("assign %s =" % var) not in src):
                print("слой %-14s использует «%s», но не задаёт его" % (f, var))
                ok = False
    print("слои: переменные t/home заданы везде, где используются" if ok else "слои: ЕСТЬ ПРОБЛЕМЫ")
    missing = sorted((l, k) for l in ("en", "ru", "be") for k in used if k not in i18n[l])
    print("i18n: все ключи из шаблонов есть в en/ru/be" if not missing else "i18n: НЕТ КЛЮЧЕЙ %s" % missing)
    ok &= not missing
    parity = [l for l in ("ru", "be") if set(i18n[l]) != set(i18n["en"])]
    print("i18n: наборы ключей одинаковы" if not parity else "i18n: РАЗНЫЕ НАБОРЫ %s" % parity)
    ok &= not parity
    import make_latest as ML
    cur = ML.is_current(root)
    print("latest.yml: " + ("актуален" if cur else "УСТАРЕЛ (python3 tools/make_latest.py)"))
    ok &= cur
    return ok


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    i18n = yaml.safe_load(open(os.path.join(root, "_data", "i18n.yml"), encoding="utf-8"))
    ok = True
    ok &= check_static(root, i18n)
    marks = yaml.safe_load(open(os.path.join(root, "_data", "marks.yml"), encoding="utf-8"))
    same_marks = tuple(m["code"] for m in marks) == A.MARK_CODES
    print("метки: _data/marks.yml и MARK_CODES %s" % ("совпадают" if same_marks else "РАСХОДЯТСЯ"))
    ok &= same_marks
    ok &= check_home(root, i18n)
    ok &= check_media(root, i18n)
    for data_name, intro_key in (("publications", "publications_intro"),):
        data = yaml.safe_load(open(os.path.join(root, "_data", data_name + ".yml"), encoding="utf-8"))
        want_all = A.render(data)
        body = want_all.split("\n---\n", 1)[1].lstrip("\n")
        # хвост после блока `____` (разделы) должен совпасть полностью
        marker = "\n____\n"
        want_tail = body.split(marker, 1)[1]
        for lang in ("en", "ru", "be"):
            ctx = {"site": {"data": {data_name: data, "i18n": i18n}},
                   "page": {"data": data_name, "lang": lang, "intro_key": intro_key}}
            got = render_layout(os.path.join(root, "_layouts", "archive.html"), ctx)
            head_expected = "%s\n\n**%s**\n\n* TOC\n{:toc}\n\n____\n" % (
                i18n[lang][intro_key], i18n[lang]["contents"])
            same = got == head_expected + want_tail
            print("%-13s %-3s %s  (%d строк)" % (data_name, lang, "совпало" if same else "РАСХОЖДЕНИЕ",
                                                  got.count("\n")))
            if not same:
                ok = False
                import difflib
                a, b = (head_expected + want_tail).split("\n"), got.split("\n")
                for i, l in enumerate(difflib.unified_diff(a, b, "ожидалось", "шаблон", lineterm="", n=1)):
                    if i > 25:
                        break
                    print("   ", l)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
