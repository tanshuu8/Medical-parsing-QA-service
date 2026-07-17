import abc
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
import fitz  # PyMuPDF

logger = logging.getLogger("app.pdf_parser")


class ParsedNode:
    """
    In-memory representation of a document structural tree node.
    """
    def __init__(
        self,
        title: str,
        body: str,
        level: int,
        page_number: int,
        parent: Optional["ParsedNode"] = None
    ):
        self.title = title
        self.body = body
        self.level = level
        self.page_number = page_number
        self.parent = parent
        self.children: List["ParsedNode"] = []
        
        # Calculate initial content hash based on title and body
        self.content_hash = self._calculate_hash()

    def _calculate_hash(self) -> str:
        sha256 = hashlib.sha256()
        sha256.update(self.title.encode("utf-8"))
        sha256.update(self.body.encode("utf-8"))
        sha256.update(str(self.level).encode("utf-8"))
        sha256.update(str(self.page_number).encode("utf-8"))
        return sha256.hexdigest()

    def add_child(self, child: "ParsedNode") -> None:
        child.parent = self
        self.children.append(child)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize node structure to dictionary (recursive for children)."""
        return {
            "title": self.title,
            "body": self.body,
            "level": self.level,
            "page_number": self.page_number,
            "content_hash": self.content_hash,
            "children": [child.to_dict() for child in self.children]
        }

    def __repr__(self) -> str:
        parent_title = self.parent.title if self.parent else "None"
        return f"<ParsedNode title='{self.title}' level={self.level} page={self.page_number} children={len(self.children)}>"


class PDFParserInterface(abc.ABC):
    """
    Abstract interface for parsing and extracting structural text nodes from PDFs.
    """
    @abc.abstractmethod
    def parse_document(self, file_path: str) -> List[ParsedNode]:
        """
        Parses a PDF file and returns a list of root ParsedNode objects representing the tree.
        """
        pass


class PDFParserService(PDFParserInterface):
    """
    Production-grade parser utilizing PyMuPDF for structural text block analysis,
    table detection, caption extraction, layout-based heading inference,
    and automatic OCR fallback.
    """

    def __init__(self, fallback_ocr_enabled: bool = True):
        self.fallback_ocr_enabled = fallback_ocr_enabled

    def parse_document(self, file_path: str) -> List[ParsedNode]:
        """
        Ingest a medical device PDF, detect hierarchy, tables, captions,
        perform fallback OCR if necessary, and reconstruct the segment tree.
        """
        logger.info(f"Opening PDF document for structural parsing: {file_path}")
        
        try:
            doc = fitz.open(file_path)
        except Exception as e:
            logger.error(f"Failed to open PDF document path {file_path}: {e}")
            raise ValueError(f"Could not open PDF file: {e}")

        # Step 1: Document statistics pass to calibrate header font-size thresholds dynamically
        font_sizes = self._gather_font_statistics(doc)
        body_font_size, header_threshold, subheader_threshold = self._calibrate_thresholds(font_sizes)
        logger.info(f"Calibrated thresholds: Body={body_font_size}pt, H2(Sub)>={subheader_threshold}pt, H1(Head)>={header_threshold}pt")

        flat_elements: List[Dict[str, Any]] = []

        # Step 2: Iterate pages to extract blocks (text headers, paragraphs, tables, images)
        for page_num in range(len(doc)):
            page = doc[page_num]
            page_index = page_num + 1  # 1-indexed for user visibility
            
            # Extract native text blocks
            page_blocks = page.get_text("dict")["blocks"]
            text_blocks = [b for b in page_blocks if b.get("type") == 0]  # Type 0 is text

            # Trigger OCR fallback if page text is entirely empty or only whitespaces
            if not text_blocks or len(page.get_text("text").strip()) == 0:
                if self.fallback_ocr_enabled:
                    logger.warning(f"Page {page_index} has no extractable text. Initiating OCR Fallback.")
                    ocr_blocks = self._perform_ocr_fallback(page, page_index)
                    flat_elements.extend(ocr_blocks)
                else:
                    logger.warning(f"Page {page_index} is empty and OCR fallback is disabled.")
                continue

            # Log unsupported non-text blocks (like vector graphics drawings/draw blocks or mathematical equations structures)
            unsupported_blocks = [b for b in page_blocks if b.get("type") not in (0, 1)]
            if unsupported_blocks:
                logger.info(f"Logged {len(unsupported_blocks)} unsupported layout elements (drawings/forms) on Page {page_index}")

            # Identify tables on page
            tables = []
            try:
                # find_tables is available in modern PyMuPDF packages
                tables = page.find_tables()
            except Exception as ex:
                logger.warning(f"Native table parser failed or not supported on Page {page_index}: {ex}")

            # Extract tables details
            table_bboxes = []
            if tables:
                for idx, table in enumerate(tables.tables):
                    table_bboxes.append(table.bbox)
                    # Convert table grid cells into a clean Markdown representation
                    md_table = self._convert_table_to_markdown(table.extract())
                    flat_elements.append({
                        "type": "table",
                        "body": md_table,
                        "page_number": page_index,
                        "bbox": table.bbox
                    })
                    logger.info(f"Extracted Table {idx + 1} on Page {page_index}")

            # Process text blocks, skipping coordinates matching tables bboxes to avoid duplication
            for block in text_blocks:
                bbox = block["bbox"]
                if self._is_bbox_inside_tables(bbox, table_bboxes):
                    continue  # Already captured as structured table markdown

                # Extract lines and clean spans
                block_lines = []
                for line in block["lines"]:
                    line_text = "".join([span["text"] for span in line["spans"]]).strip()
                    if not line_text:
                        continue
                    
                    # Compute mean size and bold face checks
                    sizes = [span["size"] for span in line["spans"]]
                    mean_size = sum(sizes) / len(sizes) if sizes else body_font_size
                    is_bold = any(bool(span["flags"] & 4) for span in line["spans"])  # bit 4 = bold flag in fitz

                    block_lines.append({
                        "text": line_text,
                        "size": mean_size,
                        "bold": is_bold
                    })

                if not block_lines:
                    continue

                # Analyze block lines to detect headings
                self._process_text_block_lines(block_lines, page_index, header_threshold, subheader_threshold, flat_elements)

        doc.close()

        # Step 3: Reconstruct Parent-Child Tree hierarchy
        tree = self._reconstruct_hierarchy(flat_elements)
        return tree

    def _gather_font_statistics(self, doc: fitz.Document) -> List[float]:
        """Scan document font sizes to get dynamic header threshold estimates."""
        sizes = []
        for page in doc:
            try:
                blocks = page.get_text("dict")["blocks"]
                for b in blocks:
                    if b.get("type") == 0:
                        for line in b["lines"]:
                            for span in line["spans"]:
                                text_clean = span["text"].strip()
                                if text_clean and len(text_clean) > 3:
                                    sizes.append(span["size"])
            except Exception:
                pass
        return sizes

    def _calibrate_thresholds(self, font_sizes: List[float]) -> Tuple[float, float, float]:
        """Compute standard text body modes and offset targets for H1/H2."""
        if not font_sizes:
            return 10.0, 14.0, 12.0  # Safe fallbacks
            
        # Count frequency of sizes to identify the standard body text mode
        size_counts: Dict[float, int] = {}
        for sz in font_sizes:
            rounded = round(sz, 1)
            size_counts[rounded] = size_counts.get(rounded, 0) + 1
            
        body_size = max(size_counts, key=size_counts.get)
        
        # Define header thresholds relative to the body size
        header_threshold = body_size + 3.0
        subheader_threshold = body_size + 1.5
        return body_size, header_threshold, subheader_threshold

    def _is_bbox_inside_tables(self, bbox: Tuple[float, float, float, float], table_bboxes: List[Tuple[float, float, float, float]]) -> bool:
        """Check if a text block overlaps significantly (>50%) with any detected tables."""
        bx0, by0, bx1, by1 = bbox
        block_area = (bx1 - bx0) * (by1 - by0)
        if block_area <= 0:
            return False
            
        for tx0, ty0, tx1, ty1 in table_bboxes:
            # Intersection rectangle coordinates
            ix0 = max(bx0, tx0)
            iy0 = max(by0, ty0)
            ix1 = min(bx1, tx1)
            iy1 = min(by1, ty1)
            
            if ix1 > ix0 and iy1 > iy0:
                intersection_area = (ix1 - ix0) * (iy1 - iy0)
                if (intersection_area / block_area) > 0.5:
                    return True
        return False

    def _convert_table_to_markdown(self, cells: List[List[str]]) -> str:
        """Serializes table cell matrices into a Markdown table structure."""
        if not cells:
            return ""
        md_lines = []
        # Filter None and clean strings
        clean_rows = [[(val.replace("\n", " ").strip() if val else "") for val in row] for row in cells]
        
        # Header Row
        md_lines.append("| " + " | ".join(clean_rows[0]) + " |")
        # Divider Row
        md_lines.append("| " + " | ".join(["---"] * len(clean_rows[0])) + " |")
        
        # Body Rows
        for row in clean_rows[1:]:
            md_lines.append("| " + " | ".join(row) + " |")
            
        return "\n".join(md_lines)

    def _process_text_block_lines(
        self,
        lines: List[Dict[str, Any]],
        page_num: int,
        header_threshold: float,
        subheader_threshold: float,
        flat_elements: List[Dict[str, Any]]
    ) -> None:
        """
        Classifies lines inside blocks into headings or bodies.
        Does NOT silently merge sections: splitting headers dynamically.
        """
        # Figure caption match rule (e.g. Figure 1: oncology graph)
        caption_pattern = re.compile(r"^(figure|fig|table|chart)\s+\d+[:.]", re.IGNORECASE)

        for line in lines:
            text = line["text"]
            size = line["size"]
            is_bold = line["bold"]

            # Match captions
            if caption_pattern.match(text):
                flat_elements.append({
                    "type": "caption",
                    "title": "Caption Match",
                    "body": text,
                    "level": 3,
                    "page_number": page_num
                })
                logger.info(f"Extracted figure/table caption on Page {page_num}: {text[:40]}")
                continue

            # Compare rounded font sizes to avoid floating point anomalies (13.999 vs 14.0)
            rounded_size = round(size, 1)
            rounded_header = round(header_threshold, 1)
            rounded_subheader = round(subheader_threshold, 1)

            if rounded_size >= rounded_header or (rounded_size >= rounded_subheader and is_bold):
                level = 0 if rounded_size >= rounded_header else 1
                flat_elements.append({
                    "type": "heading",
                    "title": text,
                    "body": "",  # Empty body initially, gets children
                    "level": level,
                    "page_number": page_num
                })
            else:
                flat_elements.append({
                    "type": "body",
                    "title": "Paragraph Segment",
                    "body": text,
                    "level": 2,
                    "page_number": page_num
                })

    def _perform_ocr_fallback(self, page: fitz.Page, page_num: int) -> List[Dict[str, Any]]:
        """
        Converts the page to a pixmap and triggers pytesseract OCR.
        Gracefully handles missing binaries with descriptive logs.
        """
        ocr_blocks = []
        try:
            from PIL import Image
            import io
            import pytesseract
            
            # Render page to high-res image
            pix = page.get_pixmap(dpi=150)
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            
            # Run Tesseract OCR parsing text orientation & blocks
            ocr_text = pytesseract.image_to_string(img).strip()
            if ocr_text:
                logger.info(f"OCR successfully extracted {len(ocr_text)} characters on Page {page_num}")
                # Treat raw OCR output chunks as simple body nodes
                for line in ocr_text.split("\n\n"):
                    clean_line = line.replace("\n", " ").strip()
                    if clean_line:
                        ocr_blocks.append({
                            "type": "body",
                            "title": "OCR Extracted Segment",
                            "body": clean_line,
                            "level": 2,
                            "page_number": page_num
                        })
            else:
                logger.warning(f"OCR returned empty results for Page {page_num}")
                
        except ImportError:
            logger.error("Failed to perform OCR fallback: 'pytesseract' or 'PIL' libraries not installed.")
            # Graceful placeholder to avoid app crashing in test setups lacking environment config
            ocr_blocks.append({
                "type": "body",
                "title": "OCR Pending",
                "body": "[OCR Fallback triggered but python dependencies 'pytesseract' or 'pillow' are missing]",
                "level": 2,
                "page_number": page_num
            })
        except Exception as e:
            logger.error(f"Tesseract OCR binaries missing or failed on Page {page_num}: {e}")
            ocr_blocks.append({
                "type": "body",
                "title": "OCR Execution Error",
                "body": f"[OCR Failed: Tesseract binary not configured or missing on host machine. Details: {e}]",
                "level": 2,
                "page_number": page_num
            })
            
        return ocr_blocks

    def _reconstruct_hierarchy(self, flat_elements: List[Dict[str, Any]]) -> List[ParsedNode]:
        """
        Assembles flat layout tags into a nested hierarchical tree structure.
        """
        roots: List[ParsedNode] = []
        stack: List[ParsedNode] = []

        for elem in flat_elements:
            elem_type = elem["type"]
            page_num = elem["page_number"]

            if elem_type == "heading":
                title = elem["title"]
                level = elem["level"]
                new_node = ParsedNode(title=title, body="", level=level, page_number=page_num)

                # Pop active stack elements until finding a parent with lower level
                while stack and stack[-1].level >= level:
                    stack.pop()

                if stack:
                    stack[-1].add_child(new_node)
                else:
                    roots.append(new_node)

                stack.append(new_node)

            elif elem_type in ("body", "table", "caption"):
                body_content = elem["body"]
                if not body_content or not body_content.strip():
                    continue  # Skip empty or whitespace-only nodes
                title_label = elem.get("title", "Paragraph Segment")
                
                # Determine hierarchy level
                node_level = elem.get("level", 2)
                
                new_node = ParsedNode(
                    title=title_label,
                    body=body_content,
                    level=node_level,
                    page_number=page_num
                )

                # Find appropriate heading parent
                while stack and stack[-1].level >= node_level:
                    stack.pop()

                if stack:
                    stack[-1].add_child(new_node)
                else:
                    roots.append(new_node)

        return roots


# Validation Utilities
def validate_parsed_tree(roots: List[ParsedNode]) -> Tuple[bool, List[str]]:
    """
    Validation utility checking parsing integrity.
    Checks:
      - Valid parent-child pointers.
      - Levels depth constraints (child level must be strictly greater than parent level).
      - No duplicate hash IDs.
      - Empty strings checks.
    """
    errors = []
    seen_hashes = set()

    def traverse(node: ParsedNode) -> None:
        # Check hashes
        if node.content_hash in seen_hashes:
            errors.append(f"Duplicate content hash detected: {node.content_hash} for node '{node.title}'")
        seen_hashes.add(node.content_hash)

        # Check content integrity
        if not node.title.strip() and not node.body.strip():
            errors.append(f"Empty node content on page {node.page_number}")

        # Check children structures
        for child in node.children:
            if child.parent != node:
                errors.append(f"Mismatched parent pointer: Child '{child.title}' has incorrect parent assignment.")
            if child.level <= node.level:
                errors.append(f"Hierarchical level error: Child '{child.title}' (level {child.level}) cannot reside under parent '{node.title}' (level {node.level}).")
            
            traverse(child)

    for r in roots:
        traverse(r)

    is_valid = len(errors) == 0
    return is_valid, errors
