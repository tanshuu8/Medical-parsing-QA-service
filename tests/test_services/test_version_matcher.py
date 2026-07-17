import uuid
import pytest
from sqlalchemy.orm import Session
from app.models.node import Node
from app.services.version_matcher import VersionMatcherService


def test_calculate_bbox_overlap() -> None:
    """Tests intersection ratio of two coordinate blocks."""
    matcher = VersionMatcherService()
    box_sel = {"x0": 0.0, "y0": 0.0, "x1": 50.0, "y1": 50.0}
    box_node = {"x0": 0.0, "y0": 0.0, "x1": 100.0, "y1": 100.0}

    overlap = matcher.calculate_bbox_overlap(box_sel, box_node)
    assert overlap == 1.0  # Selection is completely inside node


def test_build_breadcrumb_path(db_session: Session) -> None:
    """Verifies that parent breadcrumb strings build correctly recursively."""
    matcher = VersionMatcherService()

    doc_id = uuid.uuid4()
    h1 = Node(
        id=uuid.uuid4(),
        document_id=doc_id,
        logical_node_id=uuid.uuid4(),
        title="Chapter 1",
        body="",
        level=0,
        page_number=1,
        content_hash="hash1"
    )
    db_session.add(h1)
    db_session.commit()

    h2 = Node(
        id=uuid.uuid4(),
        document_id=doc_id,
        logical_node_id=uuid.uuid4(),
        parent_id=h1.id,
        title="Section 1.1",
        body="Text body",
        level=1,
        page_number=1,
        content_hash="hash2"
    )
    db_session.add(h2)
    db_session.commit()

    path = matcher.build_breadcrumb_path(h2, db_session)
    assert path == "Chapter 1 > Section 1.1"


def test_align_versions_all_statuses(db_session: Session) -> None:
    """
    Test version alignment matching statuses: UNCHANGED, MODIFIED, NEW, REMOVED.
    """
    matcher = VersionMatcherService()
    doc_v1 = uuid.uuid4()
    doc_v2 = uuid.uuid4()

    # V1 Nodes
    n1_unchanged = Node(
        id=uuid.uuid4(),
        document_id=doc_v1,
        logical_node_id=uuid.uuid4(),
        title="Welcome Introduction",
        body="This is standard overview intro.",
        level=0,
        page_number=1,
        content_hash="hash_unchanged"
    )
    n1_modified = Node(
        id=uuid.uuid4(),
        document_id=doc_v1,
        logical_node_id=uuid.uuid4(),
        title="Patient Details",
        body="Age: 45, Sex: M.",
        level=0,
        page_number=2,
        content_hash="hash_mod_v1"
    )
    n1_removed = Node(
        id=uuid.uuid4(),
        document_id=doc_v1,
        logical_node_id=uuid.uuid4(),
        title="Old Diagnostic Methodology",
        body="This section has redundant content.",
        level=0,
        page_number=3,
        content_hash="hash_rem"
    )
    
    # Save V1
    db_session.add_all([n1_unchanged, n1_modified, n1_removed])
    db_session.commit()

    # V2 Nodes (matching counterparts)
    n2_unchanged = Node(
        id=uuid.uuid4(),
        document_id=doc_v2,
        logical_node_id=uuid.uuid4(),  # Different logical initially
        title="Welcome Introduction",
        body="This is standard overview intro.",
        level=0,
        page_number=1,
        content_hash="hash_unchanged"  # Matches hash exactly
    )
    n2_modified = Node(
        id=uuid.uuid4(),
        document_id=doc_v2,
        logical_node_id=uuid.uuid4(),
        title="Patient Details Summary",  # Fuzzy match title
        body="Age: 45, Sex: Male. Diagnosis updated.",  # Content modified
        level=0,
        page_number=2,
        content_hash="hash_mod_v2"
    )
    n2_new = Node(
        id=uuid.uuid4(),
        document_id=doc_v2,
        logical_node_id=uuid.uuid4(),
        title="Updated Guidelines",
        body="New guidelines regarding oncology treatment.",
        level=0,
        page_number=3,
        content_hash="hash_new"
    )

    db_session.add_all([n2_unchanged, n2_modified, n2_new])
    db_session.commit()

    # Run alignment
    summary = matcher.align_versions(
        db_session,
        nodes_v1=[n1_unchanged, n1_modified, n1_removed],
        nodes_v2=[n2_unchanged, n2_modified, n2_new]
    )

    # Assert statuses counts
    assert summary["unchanged_count"] == 1
    assert summary["modified_count"] == 1
    assert summary["new_count"] == 1
    assert summary["removed_count"] == 1

    # Assert logical node matching linking
    # Unchanged
    aligned_unchanged = next(n for n in summary["nodes"] if n["title"] == "Welcome Introduction")
    assert aligned_unchanged["status"] == "UNCHANGED"
    assert aligned_unchanged["logical_node_id"] == str(n1_unchanged.logical_node_id)
    assert n2_unchanged.logical_node_id == n1_unchanged.logical_node_id

    # Modified
    aligned_modified = next(n for n in summary["nodes"] if "Patient Details" in n["title"])
    assert aligned_modified["status"] == "MODIFIED"
    assert aligned_modified["logical_node_id"] == str(n1_modified.logical_node_id)
    assert "expanded" in aligned_modified["diff_summary"].lower()

    # New
    aligned_new = next(n for n in summary["nodes"] if n["title"] == "Updated Guidelines")
    assert aligned_new["status"] == "NEW"

    # Removed
    aligned_removed = next(n for n in summary["nodes"] if n["title"] == "Old Diagnostic Methodology")
    assert aligned_removed["status"] == "REMOVED"
