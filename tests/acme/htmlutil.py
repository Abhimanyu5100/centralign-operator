"""A tiny HTML reader for page tests: links, buttons and form controls with their accessible names."""

from html.parser import HTMLParser


class Page(HTMLParser):
    def __init__(self, html: str):
        super().__init__()
        self.links: list[str] = []      # accessible name of every <a href>
        self.buttons: list[str] = []    # accessible name of every <button> / submit input
        self.controls: list[dict] = []  # input/select/textarea attributes (hidden and submit excluded)
        self.labels_for: set[str] = set()
        self.alerts: list[str] = []
        self.status: list[str] = []
        self._stack: list[tuple[str, list[str]]] = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("a", "button", "label", "span", "p", "div") or a.get("role"):
            self._stack.append((tag + ":" + a.get("role", ""), []))
        if tag == "label" and a.get("for"):
            self.labels_for.add(a["for"])
        if tag in ("input", "select", "textarea") and a.get("type") not in ("hidden", "submit"):
            self.controls.append(a)
        if tag == "input" and a.get("type") == "submit":
            self.buttons.append(a.get("value", ""))
        if tag == "a" and "href" in a:
            self._stack[-1] = ("a-link:", self._stack[-1][1])

    def handle_data(self, data):
        for _, parts in self._stack:
            parts.append(data)

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            kind, parts = self._stack[i]
            if kind.split(":")[0] in (tag, "a-link" if tag == "a" else tag):
                del self._stack[i:]
                text = " ".join("".join(parts).split())
                if kind == "a-link:":
                    self.links.append(text)
                elif kind.startswith("button"):
                    self.buttons.append(text)
                elif kind.endswith(":alert"):
                    self.alerts.append(text)
                elif kind.endswith(":status"):
                    self.status.append(text)
                break
