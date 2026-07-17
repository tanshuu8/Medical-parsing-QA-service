import abc
import logging
from typing import Any, Dict, List, Optional, Tuple, Set
import uuid
from rapidfuzz import fuzz
from sqlalchemy.orm import Session
from app.models.node import Node

logger = logging.getLogger("app.version_matcher")


class VersionMatcherInterface(abc.ABC):
    """
    Abstract interface for string matching, coordinate overlays,
    and document version structural alignments.
    """
    @abc.abstractmethod
    def calculate_bbox_overlap(self, bbox_sel: Dict[str, float], bbox_node: Dict[str, float]) -> float:
        """
        Computes coordinate overlap ratio.
        """
        pass

    @abc.abstractmethod
    def build_breadcrumb_path(self, node: Node, db: Session) -> str:
        """
        Builds a hierarchical path string for a node (e.g. "Root/Section 1/Sub-heading").
        """
        pass

    @abc.abstractmethod
    def align_versions(
        self,
        db: Session,
        nodes_v1: List[Node],
        nodes_v2: List[Node]
    ) -> Dict[str, Any]:
        """
        Aligns two versions of a document. Matches nodes, determines statuses,
        builds lightweight diffs, and returns a structured diff summary.
        """
        pass


class VersionMatcherService(VersionMatcherInterface):
    """
    Concrete service implementing fuzzy hierarchy matching and version alignments.
    
    ========================================================================
    EXPLANATION OF FAILURE CASES & SYSTEM LIMITATIONS:
    
    1. Title Refactoring / Renaming:
       If a heading title is completely rewritten (e.g. "Section 1.1: Scope" -> "Coverage Details"), 
       the fuzzy match score falls below the threshold, causing it to be logged as a REMOVED node 
       in V1 and a NEW node in V2, losing the logical connection.
       
    2. Hierarchy Restructuring:
       If a sub-section is moved to a completely different parent header (e.g. Section 1 -> Section 3),
       the breadcrumb path similarity drops. If the title is also modified slightly, the combined
       similarity score may drop below threshold, resulting in false negatives.
       
    3. Structural Layout Reflows:
       When pagination changes (e.g. a page is inserted), node page_numbers change. The matching engine 
       isolates page numbers from the comparison logic to prevent false positives/negatives, but 
       this means page shifts won't cause matching failures.
       
    4. Silently Merged / Aggregated Chunks:
       If a document version splits one large section into three separate nodes, only one node can match
       the original (the closest fuzzy fit), while the others are treated as NEW.
    ========================================================================
    """

    def calculate_bbox_overlap(self, bbox_sel: Dict[str, float], bbox_node: Dict[str, float]) -> float:
        """
        Simple rectangle intersection overlap calculation.
        """
        if not bbox_sel or not bbox_node:
            return 0.0
            
        try:
            # Coordinates dictionary keys: x0, y0, x1, y1
            x0 = max(bbox_sel.get("x0", 0), bbox_node.get("x0", 0))
            y0 = max(bbox_sel.get("y0", 0), bbox_node.get("y0", 0))
            x1 = min(bbox_sel.get("x1", 0), bbox_node.get("x1", 0))
            y1 = min(bbox_sel.get("y1", 0), bbox_node.get("y1", 0))

            if x1 < x0 or y1 < y0:
                return 0.0

            intersection_area = (x1 - x0) * (y1 - y0)
            sel_area = (bbox_sel.get("x1", 0) - bbox_sel.get("x0", 0)) * (bbox_sel.get("y1", 0) - bbox_sel.get("y0", 0))

            if sel_area <= 0:
                return 0.0

            return intersection_area / sel_area
        except Exception as e:
            logger.warning(f"Failed to calculate bbox overlap: {e}")
            return 0.0

    def build_breadcrumb_path(self, node: Node, db: Session) -> str:
        """
        Recursively builds parent breadcrumb titles path to avoid false matches
        on identical section headers located in different parts of a document.
        """
        path_segments = []
        current = node
        
        # Traverse parent hierarchy
        while current is not None:
            # Insert title at the beginning
            path_segments.insert(0, current.title)
            if current.parent_id:
                # Resolve parent node from DB session
                current = db.get(Node, current.parent_id)
            else:
                current = None
                
        return " > ".join(path_segments)

    def _generate_lightweight_diff(self, text1: str, text2: str) -> str:
        """
        Computes a lightweight diff summary showing character edit metrics.
        """
        if text1 == text2:
            return "No content changes."
            
        len1, len2 = len(text1), len(text2)
        diff_len = len2 - len1
        
        # Simple character counts metrics
        if diff_len > 0:
            change_str = f"Modified: content expanded by {diff_len} characters."
        elif diff_len < 0:
            change_str = f"Modified: content reduced by {abs(diff_len)} characters."
        else:
            change_str = "Modified: content changed (same length)."

        # Inline summary check
        if len1 < 100 and len2 < 100:
            change_str += f" From '{text1}' to '{text2}'"
            
        return change_str

    def align_versions(
        self,
        db: Session,
        nodes_v1: List[Node],
        nodes_v2: List[Node]
    ) -> Dict[str, Any]:
        """
        Performs multi-stage alignment (exact hash -> fuzzy title + hierarchy path).
        Maps matching logical_node_id and tags changes.
        """
        logger.info(f"Initiating structural version matching. V1 Nodes={len(nodes_v1)}, V2 Nodes={len(nodes_v2)}")

        # Build paths for all nodes
        paths_v1 = {n.id: self.build_breadcrumb_path(n, db) for n in nodes_v1}
        paths_v2 = {n.id: self.build_breadcrumb_path(n, db) for n in nodes_v2}

        matched_v1_ids: Set[uuid.UUID] = set()
        matched_v2_ids: Set[uuid.UUID] = set()
        
        # Results container
        aligned_nodes: List[Dict[str, Any]] = []

        # --- Phase 1: Match by exact content hash (avoiding false positives) ---
        # Match nodes that are completely identical in title, body, levels and paths
        for n2 in nodes_v2:
            for n1 in nodes_v1:
                if n1.id in matched_v1_ids:
                    continue
                if n2.content_hash == n1.content_hash and paths_v2[n2.id] == paths_v1[n1.id]:
                    # Exact Match!
                    matched_v1_ids.add(n1.id)
                    matched_v2_ids.add(n2.id)
                    
                    # Align logical_node_id
                    n2.logical_node_id = n1.logical_node_id
                    db.add(n2)
                    
                    aligned_nodes.append({
                        "logical_node_id": str(n1.logical_node_id),
                        "status": "UNCHANGED",
                        "title": n2.title,
                        "page_number_v1": n1.page_number,
                        "page_number_v2": n2.page_number,
                        "diff_summary": "Unchanged."
                    })
                    break

        # --- Phase 2: Match by Fuzzy Title + Hierarchy Path (MODIFIED nodes) ---
        for n2 in nodes_v2:
            if n2.id in matched_v2_ids:
                continue

            best_match: Optional[Node] = None
            best_score = 0.0

            for n1 in nodes_v1:
                if n1.id in matched_v1_ids:
                    continue

                # 1. Fuzzy match on titles
                title_sim = fuzz.token_sort_ratio(n2.title, n1.title)
                
                # 2. Fuzzy match on hierarchical breadcrumb path
                path_sim = fuzz.token_sort_ratio(paths_v2[n2.id], paths_v1[n1.id])

                # Combine scores (Title carries higher weight)
                combined_score = (title_sim * 0.6) + (path_sim * 0.4)

                if combined_score > best_score:
                    best_score = combined_score
                    best_match = n1

            # Match threshold of 70% to prevent false matching mismatches
            if best_match and best_score >= 70.0:
                n1 = best_match
                matched_v1_ids.add(n1.id)
                matched_v2_ids.add(n2.id)

                # Link logical tracking ID
                n2.logical_node_id = n1.logical_node_id
                db.add(n2)

                diff_summary = self._generate_lightweight_diff(n1.body, n2.body)

                aligned_nodes.append({
                    "logical_node_id": str(n1.logical_node_id),
                    "status": "MODIFIED",
                    "title": n2.title,
                    "page_number_v1": n1.page_number,
                    "page_number_v2": n2.page_number,
                    "diff_summary": diff_summary,
                    "match_confidence": round(best_score, 1)
                })

        # --- Phase 3: Unmatched V2 Nodes (NEW) ---
        for n2 in nodes_v2:
            if n2.id in matched_v2_ids:
                continue
            
            # Keeps its own generated logical_node_id
            aligned_nodes.append({
                "logical_node_id": str(n2.logical_node_id),
                "status": "NEW",
                "title": n2.title,
                "page_number_v1": None,
                "page_number_v2": n2.page_number,
                "diff_summary": "New section added."
            })

        # --- Phase 4: Unmatched V1 Nodes (REMOVED) ---
        for n1 in nodes_v1:
            if n1.id in matched_v1_ids:
                continue

            aligned_nodes.append({
                "logical_node_id": str(n1.logical_node_id),
                "status": "REMOVED",
                "title": n1.title,
                "page_number_v1": n1.page_number,
                "page_number_v2": None,
                "diff_summary": "Section deleted."
            })

        db.commit()

        # Compile summaries
        summary = {
            "total_nodes_v1": len(nodes_v1),
            "total_nodes_v2": len(nodes_v2),
            "unchanged_count": sum(1 for node in aligned_nodes if node["status"] == "UNCHANGED"),
            "modified_count": sum(1 for node in aligned_nodes if node["status"] == "MODIFIED"),
            "new_count": sum(1 for node in aligned_nodes if node["status"] == "NEW"),
            "removed_count": sum(1 for node in aligned_nodes if node["status"] == "REMOVED"),
            "nodes": aligned_nodes
        }

        return summary
