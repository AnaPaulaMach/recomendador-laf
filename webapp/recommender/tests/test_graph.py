from django.test import SimpleTestCase

from recommender.graph.contracts import GraphNode
from recommender.graph.service import ArgumentGraphService


class GraphTests(SimpleTestCase):
    def test_null_fields_are_normalized(self):
        node = GraphNode.from_dict(
            {
                "id": "n1",
                "label": None,
                "literal": None,
                "polarity": None,
                "confidence": None,
                "preference": None,
                "metadata": None,
            }
        )
        self.assertEqual(node.label, "n1")
        self.assertEqual(node.literal, "n1")
        self.assertEqual(node.confidence, 0)
        self.assertEqual(node.acceptability_status, "undetermined")

    def test_depth_crops_explanatory_subgraph(self):
        data = {
            "root_id": "root",
            "total_nodes": 10,
            "total_edges": 9,
            "nodes": [
                {"id": "root", "label": "root"},
                {"id": "a", "label": "a"},
                {"id": "b", "label": "b"},
                {"id": "c", "label": "c"},
            ],
            "edges": [
                {"id": "e1", "source": "a", "target": "root"},
                {"id": "e2", "source": "b", "target": "a"},
                {"id": "e3", "source": "c", "target": "b"},
            ],
        }
        service = ArgumentGraphService(data)
        self.assertEqual(service.fragment(depth=1).visible_nodes, 2)
        self.assertEqual(service.fragment(depth=2).visible_nodes, 3)
        self.assertTrue(service.fragment(depth=2).truncated)

    def test_visible_limit_is_never_greater_than_250(self):
        nodes = [{"id": "root", "label": "root"}]
        edges = []
        for index in range(300):
            node_id = f"n{index}"
            nodes.append({"id": node_id, "label": node_id})
            edges.append({"id": f"e{index}", "source": node_id, "target": "root"})
        service = ArgumentGraphService(
            {"root_id": "root", "nodes": nodes, "edges": edges, "total_nodes": 301},
            maximum_limit=999,
        )
        self.assertEqual(service.fragment(depth=1, limit=999).visible_nodes, 250)

    def test_filters_support_conflict_and_thresholds(self):
        data = {
            "root_id": "root",
            "nodes": [
                {"id": "root", "label": "root", "confidence": 1},
                {"id": "positive", "label": "sabor", "confidence": 0.8, "node_type": "fact"},
                {"id": "weak", "label": "aroma", "confidence": 0.2, "node_type": "fact"},
            ],
            "edges": [
                {"id": "e1", "source": "positive", "target": "root", "edge_type": "support"},
                {"id": "e2", "source": "weak", "target": "root", "edge_type": "conflict"},
            ],
        }
        fragment = ArgumentGraphService(data).fragment(
            depth=1,
            filters={"edge_types": ["support"], "min_confidence": 0.5},
        )
        self.assertEqual({node.id for node in fragment.nodes}, {"root", "positive"})
        self.assertEqual(fragment.visible_edges, 1)
