"""Unit tests for the API Lambda (no AWS calls: boto3 resources are stubbed)."""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.update(TABLE_NAME="t", WORKER_FUNCTION_NAME="w", IMAGE_BUCKET="b")

import api  # noqa: E402
import catalog  # noqa: E402


def post(body):
    return {"routeKey": "POST /api/portraits", "body": json.dumps(body)}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.table = mock.MagicMock()
        self.lam = mock.MagicMock()
        mock.patch.object(api, "TABLE", self.table).start()
        mock.patch.object(api, "LAMBDA", self.lam).start()
        self.addCleanup(mock.patch.stopall)

    def test_options(self):
        res = api.handler({"routeKey": "GET /api/options"}, None)
        self.assertEqual(res["statusCode"], 200)
        body = json.loads(res["body"])
        self.assertEqual(len(body["eras"]), len(catalog.ERAS))

    def test_create_valid_queues_worker(self):
        res = api.handler(post({"era": "ancient_rome", "role": "scholar", "style": "impressionist", "idea": "  likes   cats "}), None)
        self.assertEqual(res["statusCode"], 202)
        item = self.table.put_item.call_args.kwargs["Item"]
        self.assertEqual(item["idea"], "likes cats")
        self.assertEqual(item["status"], "QUEUED")
        self.lam.invoke.assert_called_once()
        self.assertEqual(self.lam.invoke.call_args.kwargs["InvocationType"], "Event")

    def test_create_rejects_unknown_option(self):
        res = api.handler(post({"era": "atlantis", "role": "scholar", "style": "impressionist"}), None)
        self.assertEqual(res["statusCode"], 400)
        self.table.put_item.assert_not_called()

    def test_create_rejects_long_idea(self):
        res = api.handler(post({"era": "ancient_rome", "role": "scholar", "style": "impressionist",
                                "idea": "x" * (catalog.MAX_IDEA_LENGTH + 1)}), None)
        self.assertEqual(res["statusCode"], 400)

    def test_create_rejects_non_json(self):
        res = api.handler({"routeKey": "POST /api/portraits", "body": "nope"}, None)
        self.assertEqual(res["statusCode"], 400)

    def test_get_invalid_id(self):
        res = api.handler({"routeKey": "GET /api/portraits/{id}", "pathParameters": {"id": "../etc"}}, None)
        self.assertEqual(res["statusCode"], 404)
        self.table.get_item.assert_not_called()

    def test_get_hides_private_fields(self):
        self.table.get_item.return_value = {"Item": {"id": "a" * 32, "status": "COMPLETE", "idea": "secret",
                                                     "era": "edo_japan", "ttl": 1}}
        res = api.handler({"routeKey": "GET /api/portraits/{id}", "pathParameters": {"id": "a" * 32}}, None)
        body = json.loads(res["body"])
        self.assertNotIn("idea", body)
        self.assertNotIn("ttl", body)
        self.assertEqual(body["eraLabel"], "Edo Japan")

    def test_gallery_bad_cursor(self):
        res = api.handler({"routeKey": "GET /api/gallery", "queryStringParameters": {"cursor": "!!!"}}, None)
        self.assertEqual(res["statusCode"], 400)


class WorkerJsonTests(unittest.TestCase):
    def test_extract_json_from_fenced_text(self):
        os.environ.update(TEXT_MODEL_ID="m", TEXT_MODEL_REGION="us-east-1", IMAGE_MODEL_ID="i", IMAGE_MODEL_REGION="us-west-2")
        import worker
        self.assertEqual(worker._extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        with self.assertRaises(ValueError):
            worker._extract_json("no json here")


if __name__ == "__main__":
    unittest.main()
