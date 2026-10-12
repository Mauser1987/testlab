"""Text of a rendered HTML document template in reading order, for regression comparisons (AT-2).

Page header, body, page footer; a table row is one line (cells joined by
spaces).
"""

import tinyhtml5


def html_lines(html):
    """Non-empty lines: header, body (<main>), footer."""
    root = tinyhtml5.parse(html, namespace_html_elements=False)
    lines = []
    for part in ("header", "main", "footer"):
        lines += _block_lines(root.find(f".//{part}"))
    return [line for line in lines if line]


def _block_lines(element):
    lines = []
    for child in element:
        if child.tag == "table":
            for row in child.iter("tr"):
                cells = [_text(cell) for cell in row if cell.tag in ("td", "th")]
                lines.append(" ".join(cell for cell in cells if cell))
        elif child.tag in ("p", "h1", "h2", "h3"):
            lines.append(_text(child))
        else:
            lines += _block_lines(child)
    return lines


def _text(element):
    parts = [element.text or ""]
    for child in element:
        parts.append(" " if child.tag == "br" else _text(child))
        parts.append(child.tail or "")
    return " ".join("".join(parts).split())


def normalized(lines):
    """Whitespace-normalised text (line breaks and repeated spaces are layout, not content)."""
    return " ".join(" ".join(lines).split())
