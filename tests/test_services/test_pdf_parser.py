import pytest
from unittest.mock import MagicMock, patch
import fitz
from app.services.pdf_parser import PDFParserService, ParsedNode, validate_parsed_tree


class MockSpan:
    def __init__(self, text: str, size: float, flags: int):
        self.text = text
        self.size = size
        self.flags = flags


class MockLine:
    def __init__(self, spans: list):
        self.spans = [{"text": s.text, "size": s.size, "flags": s.flags} for s in spans]


class MockBlock:
    def __init__(self, lines: list, bbox: tuple = (0, 0, 100, 100)):
        self.lines = lines
        self.bbox = bbox

    def to_dict(self):
        return {
            "type": 0,
            "lines": [line.spans for line in self.lines],
            "bbox": self.bbox
        }


def test_calculate_hash() -> None:
    """Verifies that content hash changes when properties change."""
    node1 = ParsedNode(title="Intro", body="Body content", level=0, page_number=1)
    node2 = ParsedNode(title="Intro", body="Body content", level=0, page_number=1)
    node3 = ParsedNode(title="Intro", body="Body content changed", level=0, page_number=1)

    assert node1.content_hash == node2.content_hash
    assert node1.content_hash != node3.content_hash


def test_tree_validation_success() -> None:
    """Verifies validation utility passes with clean hierarchies."""
    root = ParsedNode(title="H1 Title", body="", level=0, page_number=1)
    child = ParsedNode(title="H2 Subtitle", body="Text content", level=1, page_number=1)
    root.add_child(child)

    is_valid, errors = validate_parsed_tree([root])
    assert is_valid is True
    assert len(errors) == 0


def test_tree_validation_failure() -> None:
    """Verifies validation utility raises errors on invalid parent assignments."""
    root = ParsedNode(title="H1 Title", body="", level=1, page_number=1)
    # Level error: child has level equal to or less than parent
    child = ParsedNode(title="H2 Title Invalid Level", body="Text", level=1, page_number=1)
    root.children.append(child)  # Direct append without add_child (creates parent pointer mismatch)

    is_valid, errors = validate_parsed_tree([root])
    assert is_valid is False
    assert any("pointer" in err.lower() or "level" in err.lower() for err in errors)


@patch("fitz.open")
def test_parser_hierarchy_tree(mock_fitz_open) -> None:
    """
    Test structural layout and hierarchy tree reconstruction using mocked PDF blocks.
    """
    # 1. Setup mock pages
    mock_doc = MagicMock()
    mock_page1 = MagicMock()
    
    # Text block structure simulating font sizes
    # Mode font size: 10.0 (Body)
    # H1 size: 15.0
    # H2 size: 12.0 (Bold: flag 4)
    blocks_dict = {
        "blocks": [
            {
                "type": 0,
                "bbox": (10, 10, 100, 30),
                "lines": [
                    {
                        "spans": [{"text": "Main Medical Section", "size": 15.0, "flags": 0}]
                    }
                ]
            },
            {
                "type": 0,
                "bbox": (10, 40, 100, 60),
                "lines": [
                    {
                        "spans": [{"text": "Subsection Topic", "size": 12.0, "flags": 4}]
                    }
                ]
            },
            {
                "type": 0,
                "bbox": (10, 70, 100, 100),
                "lines": [
                    {
                        "spans": [{"text": "This is standard oncology research body text.", "size": 10.0, "flags": 0}]
                    }
                ]
            }
        ]
    }
    
    mock_page1.get_text.side_effect = lambda format_type: (
        "Main Medical Section\nSubsection Topic\nThis is standard oncology research body text."
        if format_type == "text" else blocks_dict
    )
    mock_page1.find_tables.return_value = MagicMock(tables=[])
    
    mock_doc.__len__.return_value = 1
    mock_doc.__getitem__.return_value = mock_page1
    mock_fitz_open.return_value = mock_doc

    # 2. Run Parser Service
    parser = PDFParserService(fallback_ocr_enabled=False)
    roots = parser.parse_document("dummy_path.pdf")

    # 3. Assertions
    assert len(roots) == 1
    root = roots[0]
    assert root.title == "Main Medical Section"
    assert root.level == 0
    
    assert len(root.children) == 1
    sub_node = root.children[0]
    assert sub_node.title == "Subsection Topic"
    assert sub_node.level == 1
    
    assert len(sub_node.children) == 1
    body_node = sub_node.children[0]
    assert body_node.body == "This is standard oncology research body text."
    assert body_node.level == 2


def test_is_bbox_inside_tables() -> None:
    """Verifies that bounding box overlap logic correctly evaluates >50% intersection ratio."""
    parser = PDFParserService()
    
    # 1. Exact overlap
    bbox = (10, 10, 20, 20)
    table_bboxes = [(10, 10, 20, 20)]
    assert parser._is_bbox_inside_tables(bbox, table_bboxes) is True

    # 2. >50% overlap (e.g. 60%)
    # block area: 10 * 10 = 100
    # intersection: width 6, height 10 = 60 (which is 60%)
    bbox = (10, 10, 20, 20)
    table_bboxes = [(14, 10, 25, 20)]
    assert parser._is_bbox_inside_tables(bbox, table_bboxes) is True

    # 3. <50% overlap (e.g. 30%)
    # intersection: width 3, height 10 = 30 (which is 30%)
    bbox = (10, 10, 20, 20)
    table_bboxes = [(17, 10, 25, 20)]
    assert parser._is_bbox_inside_tables(bbox, table_bboxes) is False

    # 4. No overlap
    bbox = (10, 10, 20, 20)
    table_bboxes = [(50, 50, 60, 60)]
    assert parser._is_bbox_inside_tables(bbox, table_bboxes) is False

