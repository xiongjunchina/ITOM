"""知识文档导入（M3.10）：word/markdown/html/txt → 系统格式（净化 HTML 或原生 Markdown）。"""
import io
import re

import bleach
import mammoth
import markdown as md_lib

ALLOWED_TAGS = [
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "strong", "b", "em", "i",
    "a", "img", "table", "thead", "tbody", "tr", "td", "th", "blockquote", "pre", "code",
    "br", "hr", "span", "sup", "sub",
]
ALLOWED_ATTRS = {"a": ["href", "title"], "img": ["src", "alt"], "td": ["colspan", "rowspan"], "th": ["colspan", "rowspan"]}
ALLOWED_PROTOCOLS = ["http", "https", "mailto", "data"]  # data: 允许 docx 内嵌图片

MAX_DOC = 10 * 1024 * 1024


def sanitize_html(html: str) -> str:
    # 先整块移除 script/style（bleach strip 只删标签保留内文）
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    return bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, protocols=ALLOWED_PROTOCOLS, strip=True)


def _title_from_html(html: str, fallback: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    if m:
        text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if text:
            return text[:200]
    return fallback


def _title_from_markdown(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()[:200]
    return fallback


def convert_document(filename: str, content: bytes) -> dict:
    """返回 {title, content, content_format}。不支持的格式抛 ValueError。"""
    if len(content) > MAX_DOC:
        raise ValueError("文档不能超过 10MB")
    stem = re.sub(r"\.[^.]+$", "", filename or "导入文档")
    ext = (filename or "").lower().rsplit(".", 1)[-1] if "." in (filename or "") else ""

    if ext in ("md", "markdown"):
        text = content.decode("utf-8", errors="replace")
        return {"title": _title_from_markdown(text, stem), "content": text, "content_format": "markdown"}
    if ext == "docx":
        result = mammoth.convert_to_html(io.BytesIO(content))
        html = sanitize_html(result.value)
        if not re.sub(r"<[^>]+>", "", html).strip():
            raise ValueError("文档内容为空或无法解析")
        return {"title": _title_from_html(html, stem), "content": html, "content_format": "html"}
    if ext in ("html", "htm"):
        html = sanitize_html(content.decode("utf-8", errors="replace"))
        return {"title": _title_from_html(html, stem), "content": html, "content_format": "html"}
    if ext == "txt":
        text = content.decode("utf-8", errors="replace")
        return {"title": _title_from_markdown(text, stem), "content": text, "content_format": "markdown"}
    if ext == "doc":
        raise ValueError("暂不支持 .doc 旧格式，请另存为 .docx 后导入")
    raise ValueError(f"不支持的格式 .{ext}（支持：docx / md / html / txt）")


def markdown_to_html(text: str) -> str:
    """预览用：Markdown → 净化 HTML。"""
    return sanitize_html(md_lib.markdown(text, extensions=["tables", "fenced_code"]))
