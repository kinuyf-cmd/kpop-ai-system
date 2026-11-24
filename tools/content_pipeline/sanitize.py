"""LLM が書いた本文 HTML を許可リストで組み直す(2026-11-13 セキュリティレビュー指摘への対応)。

執筆役は外部ページを読むため、ページ内の指示(プロンプトインジェクション)で <script>・on*= 属性・
javascript: URL・iframe を混ぜられうる。本文は自動公開されるので、ここで許可したタグ/属性以外を落とす。
FAQPage の JSON-LD は消毒の後にパイプライン自身が付ける(LLM 由来の script は1つも通さない)。
"""
from __future__ import annotations

import html
from html.parser import HTMLParser
from urllib.parse import urlparse

ALLOWED = {"p", "h2", "h3", "h4", "ul", "ol", "li", "a", "strong", "em", "b", "br",
           "table", "thead", "tbody", "tr", "th", "td", "div", "span", "blockquote"}
VOID = {"br"}
DROP_WITH_CONTENT = {"script", "style", "iframe", "object", "embed", "noscript", "template",
                     "svg", "math", "form", "textarea", "select", "button"}
ALLOWED_CLASSES = {"kpj-sources", "kpj-faq", "kpj-summary", "kpj-table"}


def _safe_href(v: str) -> str | None:
    v = (v or "").strip()
    p = urlparse(v)
    if p.scheme in ("http", "https") and p.netloc:
        return v
    if not p.scheme and v.startswith("/") and not v.startswith("//"):
        return v
    return None  # javascript: / data: / vbscript: / プロトコル相対などは落とす


class _San(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.stack: list[str] = []
        self.removed: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:
            self.skip += 1
            self.removed.append(f"<{tag}>")
            return
        if self.skip:
            return
        if tag not in ALLOWED:
            self.removed.append(f"<{tag}>")
            return
        keep = []
        for k, v in attrs:
            if tag == "a" and k == "href":
                h = _safe_href(v)
                if h:
                    keep.append(f' href="{html.escape(h, quote=True)}"')
                else:
                    self.removed.append(f"href={str(v)[:40]}")
            elif k == "class":
                cls = [c for c in (v or "").split() if c in ALLOWED_CLASSES]
                if cls:
                    keep.append(f' class="{" ".join(cls)}"')
            elif tag in ("th", "td") and k in ("colspan", "rowspan") and str(v).isdigit():
                keep.append(f' {k}="{v}"')
            else:
                self.removed.append(f"{tag}[{k}]")
        if tag == "a":
            keep.append(' rel="noopener" target="_blank"')
        self.out.append(f"<{tag}{''.join(keep)}>")
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in self.stack and self.stack[-1] == tag and tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in DROP_WITH_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in ALLOWED or tag in VOID or tag not in self.stack:
            return
        while self.stack:
            t = self.stack.pop()
            self.out.append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))

    def handle_comment(self, data):
        self.removed.append("<!--comment-->")


def sanitize(body: str) -> tuple[str, list[str]]:
    """(消毒後 HTML, 落としたものの一覧)。"""
    p = _San()
    p.feed(body or "")
    p.close()
    out = "".join(p.out) + "".join(f"</{t}>" for t in reversed(p.stack))
    return out, p.removed
