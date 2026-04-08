# pdf-to-epub

Convert a PDF to a pixel-perfect fixed-layout EPUB. Each page is rendered as a high-quality image — exactly as it appears in the PDF — and embedded in a fixed-layout EPUB that preserves the original layout on any EPUB reader.

While this is not the best way to consume PDFs, I wanted files that I could use in Apple Books to read between my devices which would keep track of the page I left off on. When reading PDFs, because the Mac uses the Preview app, it does not keep track of what page you left off on.

## How it works

1. Each PDF page is rasterized via **poppler** (the same engine used by print drivers) at the specified DPI.
2. Pages are encoded as JPEG or PNG images.
3. Everything is packaged into a **fixed-layout EPUB** (`rendition:layout="pre-paginated"`) where each XHTML page has a viewport sized to that page's exact pixel dimensions.

## Requirements

**Python packages:**
```bash
pip install pdf2image Pillow
```

**System dependency (poppler):**
```bash
# macOS
brew install poppler

# Debian / Ubuntu
sudo apt-get install poppler-utils
```

## Usage

```bash
# Basic — output saved alongside input as input.epub
python3 pdf_to_epub.py document.pdf

# Specify output path
python3 pdf_to_epub.py document.pdf ~/Desktop/output.epub

# High quality (300 DPI JPEG)
python3 pdf_to_epub.py document.pdf --dpi 300 --quality 95

# Lossless PNG (pixel-perfect, larger files)
python3 pdf_to_epub.py document.pdf --png --dpi 200

# Custom EPUB title in metadata
python3 pdf_to_epub.py report.pdf --title "Q4 Annual Report"
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--dpi` | `150` | Render resolution. Higher = sharper, larger file. |
| `--quality` | `85` | JPEG quality (1–95). Ignored with `--png`. |
| `--png` | off | Use lossless PNG instead of JPEG. |
| `--title` | filename | EPUB title metadata. |

## DPI guide

| DPI | Use case |
|-----|----------|
| 96  | Screen reading, smallest file |
| 150 | Default — good balance |
| 200 | Sharp on tablets / large screens |
| 300 | Print-quality archival |

## Output format

The EPUB uses the IDPF fixed-layout spec (`rendition:layout="pre-paginated"`), which is supported by:
- Apple Books
- Kindle (via Send to Kindle / Calibre conversion)
- Kobo
- Adobe Digital Editions
- Most modern EPUB readers
