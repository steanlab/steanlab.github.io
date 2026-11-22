#!/usr/bin/env python3
"""Снимок страниц-перечней сайта в Wayback Machine после добавления записи.

Вызывается из .github/workflows/add-item.yml в самом конце, когда запись уже закоммичена.
Сначала ждёт, пока GitHub Pages опубликует именно этот коммит (иначе в архив попадёт старая версия страницы),
затем сохраняет страницы «СМИ и интервью» и «Публикации» на всех трёх языках.
Ошибки не роняют workflow: итог печатается и пишется в сводку запуска (GITHUB_STEP_SUMMARY).

  snapshot_pages.py --sha КОММИТ [--repo ВЛАДЕЛЕЦ/РЕПОЗИТОРИЙ] [--site https://steanlab.github.io]
Ключи Internet Archive берутся из IA_ACCESS_KEY и IA_SECRET_KEY (без них используется обычное сохранение без ключей).
"""
import argparse
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import add_item as T  # noqa: E402

PAGES = ["interview/", "bibliography/"]
PREFIXES = ["", "ru/", "be/"]


def page_urls(site):
    site = site.rstrip("/") + "/"
    return [site + pre + p for p in PAGES for pre in PREFIXES]


def wait_built(repo, sha, token, timeout=600, step=15, opener=None, sleep=time.sleep, fallback=240):
    """Ждёт, пока Pages соберёт коммит sha. Если состояние сборки прочитать нельзя, ждёт фиксированное время."""
    op = opener or urllib.request.build_opener()
    t0 = time.time()
    while time.time() - t0 < timeout:
        req = urllib.request.Request("https://api.github.com/repos/%s/pages/builds/latest" % repo, headers={
            "Accept": "application/vnd.github+json", "Authorization": "Bearer %s" % token,
            "X-GitHub-Api-Version": "2022-11-28"})
        try:
            b = json.load(op.open(req, timeout=30))
        except Exception:
            sleep(fallback)
            return "ожидание %d с (состояние сборки прочитать не удалось)" % fallback
        if b.get("commit") == sha:
            if b.get("status") == "built":
                return "сборка Pages завершена"
            if b.get("status") == "errored":
                raise RuntimeError("сборка Pages завершилась ошибкой, снимок не делаем")
        sleep(step)
    raise RuntimeError("сборка Pages не завершилась за %d с" % timeout)


def main(argv=None, wayback=T.save_wayback, wait=wait_built):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", required=True)
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    ap.add_argument("--site", default=os.environ.get("SITE_URL", "https://steanlab.github.io"))
    a = ap.parse_args(argv)
    lines = []
    try:
        lines.append("Ожидание: " + wait(a.repo, a.sha, os.environ.get("GH_TOKEN", "")))
    except Exception as e:
        lines.append("Снимки страниц не сделаны: %s" % e)
        print("\n".join(lines))
        return 0
    access, secret = os.environ.get("IA_ACCESS_KEY"), os.environ.get("IA_SECRET_KEY")
    for url in page_urls(a.site):
        try:
            lines.append("%s -> %s" % (url, wayback(url, access=access, secret=secret, wait=150)))
        except Exception as e:
            lines.append("%s -> не удалось (%s)" % (url, str(e)[:150]))
        time.sleep(3)
    out = "\n".join(lines)
    print(out)
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        with open(summ, "a", encoding="utf-8") as f:
            f.write("### Снимки страниц в Wayback Machine\n\n```\n%s\n```\n" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
