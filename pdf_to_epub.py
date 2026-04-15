#!/usr/bin/env python3
"""
pdf_to_epub.py — Convert a PDF to a fixed-layout EPUB.

Each PDF page is rendered at high DPI into a JPEG image, then embedded in a
fixed-layout EPUB so readers display each page exactly as it appears in the PDF.

Usage:
    python pdf_to_epub.py input.pdf [output.epub] [--dpi 150] [--quality 90] [--png]

Requirements:
    pip install pdf2image Pillow
    brew install poppler        # macOS
    apt-get install poppler-utils  # Debian/Ubuntu
"""

import argparse
import io
import os
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def check_dependencies():
    """Verify required packages are installed."""
    missing = []
    try:
        import pdf2image  # noqa: F401
    except ImportError:
        missing.append("pdf2image")
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        missing.append("Pillow")
    if missing:
        print(f"Missing packages: {', '.join(missing)}")
        print(f"Install with: pip install {' '.join(missing)}")
        sys.exit(1)


def render_pages(pdf_path: Path, dpi: int, fmt: str, quality: int) -> list[dict]:
    """Render every PDF page to an in-memory image. Returns list of page dicts."""
    from pdf2image import convert_from_path
    from pdf2image.exceptions import PDFInfoNotInstalledError

    print(f"Rendering '{pdf_path.name}' at {dpi} DPI …")
    try:
        pil_images = convert_from_path(
            str(pdf_path),
            dpi=dpi,
            fmt="ppm",          # intermediate; we encode below
            thread_count=4,
            use_cropbox=True,
        )
    except PDFInfoNotInstalledError:
        print("ERROR: poppler not found.")
        print("  macOS:  brew install poppler")
        print("  Linux:  sudo apt-get install poppler-utils")
        sys.exit(1)

    pages = []
    total = len(pil_images)
    for i, img in enumerate(pil_images, 1):
        print(f"  Encoding page {i}/{total} …", end="\r", flush=True)
        buf = io.BytesIO()
        if fmt == "png":
            img.save(buf, format="PNG", optimize=True)
            mime = "image/png"
            ext = "png"
        else:
            # Convert to RGB (JPEG doesn't support RGBA)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            mime = "image/jpeg"
            ext = "jpg"
        pages.append(
            {
                "index": i,
                "width": img.width,
                "height": img.height,
                "data": buf.getvalue(),
                "mime": mime,
                "ext": ext,
            }
        )
    print(f"\n  Done — {total} page(s) rendered.")
    return pages


# ---------------------------------------------------------------------------
# EPUB building helpers
# ---------------------------------------------------------------------------

CONTAINER_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

OPF_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0"
         xmlns="http://www.idpf.org/2007/opf"
         unique-identifier="uid"
         prefix="rendition: http://www.idpf.org/vocab/rendition/#">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">{uid}</dc:identifier>
    <dc:title>{title}</dc:title>
    <dc:language>en</dc:language>
    <dc:date>{date}</dc:date>
    <meta property="dcterms:modified">{modified}</meta>
    <!-- Fixed-layout declarations -->
    <meta property="rendition:layout">pre-paginated</meta>
    <meta property="rendition:orientation">auto</meta>
    <meta property="rendition:spread">none</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ncx" href="toc.ncx"   media-type="application/x-dtbncx+xml"/>
{manifest_items}
  </manifest>
  <spine toc="ncx">
{spine_items}
  </spine>
</package>
"""

NAV_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>{title}</title>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>Table of Contents</h1>
    <ol>
{nav_items}
    </ol>
  </nav>
</body>
</html>
"""

NCX_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<ncx version="2005-1" xmlns="http://www.daisy.org/z3986/2005/ncx/">
  <head>
    <meta name="dtb:uid" content="{uid}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{title}</text></docTitle>
  <navMap>
{nav_points}
  </navMap>
</ncx>
"""

PAGE_XHTML_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width={width}, height={height}"/>
  <title>Page {index}</title>
  <style>
    html, body {{
      margin: 0;
      padding: 0;
      width: {width}px;
      height: {height}px;
      overflow: hidden;
      background: #ffffff;
    }}
    img {{
      width: {width}px;
      height: {height}px;
      display: block;
    }}
  </style>
</head>
<body>
  <img src="../images/page_{index:04d}.{ext}"
       alt="Page {index}"
       width="{width}"
       height="{height}"/>
</body>
</html>
"""


def build_epub(pages: list[dict], title: str, output_path: Path):
    """Assemble the fixed-layout EPUB zip archive."""
    uid = f"urn:uuid:{uuid.uuid4()}"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    manifest_lines = []
    spine_lines = []
    nav_items = []
    ncx_points = []

    for p in pages:
        i = p["index"]
        img_id = f"img{i:04d}"
        page_id = f"page{i:04d}"
        img_href = f"images/page_{i:04d}.{p['ext']}"
        page_href = f"pages/page_{i:04d}.xhtml"

        manifest_lines.append(
            f'    <item id="{img_id}" href="{img_href}" media-type="{p["mime"]}"/>'
        )
        manifest_lines.append(
            f'    <item id="{page_id}" href="{page_href}" '
            f'media-type="application/xhtml+xml" '
            f'properties="rendition:layout-pre-paginated"/>'
        )
        spine_lines.append(
            f'    <itemref idref="{page_id}" linear="yes"/>'
        )
        nav_items.append(f'      <li><a href="{page_href}">Page {i}</a></li>')
        ncx_points.append(
            f'    <navPoint id="np{i:04d}" playOrder="{i}">\n'
            f'      <navLabel><text>Page {i}</text></navLabel>\n'
            f'      <content src="{page_href}"/>\n'
            f'    </navPoint>'
        )

    opf = OPF_TEMPLATE.format(
        uid=uid,
        title=title,
        date=today,
        modified=now,
        manifest_items="\n".join(manifest_lines),
        spine_items="\n".join(spine_lines),
    )
    nav = NAV_TEMPLATE.format(title=title, nav_items="\n".join(nav_items))
    ncx = NCX_TEMPLATE.format(uid=uid, title=title, nav_points="\n".join(ncx_points))

    print(f"Writing '{output_path}' …")
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # mimetype must be first and uncompressed
        zf.writestr(
            zipfile.ZipInfo("mimetype"), "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        zf.writestr("META-INF/container.xml", CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/nav.xhtml", nav)
        zf.writestr("OEBPS/toc.ncx", ncx)

        for p in pages:
            i = p["index"]
            # Page XHTML
            page_xhtml = PAGE_XHTML_TEMPLATE.format(
                index=i,
                width=p["width"],
                height=p["height"],
                ext=p["ext"],
            )
            zf.writestr(f"OEBPS/pages/page_{i:04d}.xhtml", page_xhtml)
            # Image
            zf.writestr(f"OEBPS/images/page_{i:04d}.{p['ext']}", p["data"])

    size_mb = output_path.stat().st_size / 1_048_576
    print(f"Done! '{output_path}' ({size_mb:.1f} MB)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    check_dependencies()

    parser = argparse.ArgumentParser(
        description="Convert a PDF to a pixel-perfect fixed-layout EPUB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("input", help="Input PDF file")
    parser.add_argument("output", nargs="?", help="Output EPUB file (default: <input>.epub)")
    parser.add_argument(
        "--dpi", type=int, default=150,
        help="Render resolution (default: 150). Higher = sharper but larger file.",
    )
    parser.add_argument(
        "--quality", type=int, default=85,
        help="JPEG quality 1-95 (default: 85). Ignored when --png is set.",
    )
    parser.add_argument(
        "--png", action="store_true",
        help="Use lossless PNG instead of JPEG (larger files, perfect fidelity).",
    )
    parser.add_argument(
        "--title", default=None,
        help="EPUB title metadata (default: PDF filename without extension).",
    )
    args = parser.parse_args()

    pdf_path = Path(args.input).expanduser().resolve()
    if not pdf_path.exists():
        print(f"ERROR: File not found: {pdf_path}")
        sys.exit(1)
    if pdf_path.suffix.lower() != ".pdf":
        print(f"WARNING: '{pdf_path.name}' does not have a .pdf extension — proceeding anyway.")

    if args.output:
        out_path = Path(args.output).expanduser().resolve()
    else:
        out_path = pdf_path.with_suffix(".epub")

    title = args.title or pdf_path.stem.replace("-", " ").replace("_", " ").title()
    fmt = "png" if args.png else "jpeg"

    pages = render_pages(pdf_path, dpi=args.dpi, fmt=fmt, quality=args.quality)
    build_epub(pages, title=title, output_path=out_path)


if __name__ == "__main__":
    main()
