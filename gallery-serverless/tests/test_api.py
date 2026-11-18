"""Unit tests for the API Lambda (no AWS calls: boto3 resources are stubbed)."""
import base64
import io
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
        self.s3 = mock.MagicMock()
        mock.patch.object(api, "S3", self.s3).start()
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

    def _photo_body(self, **extra):
        jpeg = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0fakejpeg").decode()
        return {"era": "victorian", "role": "inventor", "style": "baroque_oil", "photo": jpeg, **extra}

    def test_create_with_photo_stores_private_upload(self):
        res = api.handler(post(self._photo_body(consent=True, likeness="faithful")), None)
        self.assertEqual(res["statusCode"], 202)
        item = self.table.put_item.call_args.kwargs["Item"]
        put = self.s3.put_object.call_args.kwargs
        self.assertEqual(put["Key"], f"uploads/{item['id']}.jpg")
        self.assertEqual(put["ContentType"], "image/jpeg")
        self.assertTrue(put["Body"].startswith(b"\xff\xd8\xff"))
        self.assertEqual(item["photoKey"], put["Key"])
        self.assertEqual(item["likeness"], "faithful")
        self.assertTrue(item["fromPhoto"])

    def test_create_with_photo_requires_consent(self):
        res = api.handler(post(self._photo_body()), None)
        self.assertEqual(res["statusCode"], 400)
        self.s3.put_object.assert_not_called()
        self.table.put_item.assert_not_called()

    def test_create_rejects_non_image_photo(self):
        body = self._photo_body(consent=True)
        body["photo"] = base64.b64encode(b"<svg onload=alert(1)>").decode()
        res = api.handler(post(body), None)
        self.assertEqual(res["statusCode"], 400)
        self.s3.put_object.assert_not_called()

    def test_create_rejects_oversized_photo(self):
        body = self._photo_body(consent=True)
        body["photo"] = "A" * (catalog.MAX_PHOTO_BYTES * 2)
        self.assertEqual(api.handler(post(body), None)["statusCode"], 400)

    def test_create_rejects_unknown_likeness(self):
        res = api.handler(post(self._photo_body(consent=True, likeness="exact")), None)
        self.assertEqual(res["statusCode"], 400)

    def test_public_hides_photo_key(self):
        self.table.get_item.return_value = {"Item": {"id": "b" * 32, "status": "COMPLETE", "photoKey": "uploads/x.jpg",
                                                     "fromPhoto": True, "likeness": "balanced"}}
        res = api.handler({"routeKey": "GET /api/portraits/{id}", "pathParameters": {"id": "b" * 32}}, None)
        body = json.loads(res["body"])
        self.assertNotIn("photoKey", body)
        self.assertTrue(body["fromPhoto"])
        self.assertEqual(body["likenessLabel"], "Balanced")

    def test_gallery_bad_cursor(self):
        res = api.handler({"routeKey": "GET /api/gallery", "queryStringParameters": {"cursor": "!!!"}}, None)
        self.assertEqual(res["statusCode"], 400)


os.environ.update(TEXT_MODEL_ID="m", TEXT_MODEL_REGION="us-east-1", IMAGE_MODEL_ID="i", IMAGE_MODEL_REGION="us-west-2",
                  PHOTO_MODEL_ID="p", PHOTO_MODEL_REGION="us-west-2")
import worker  # noqa: E402


def _bedrock_image_response():
    payload = json.dumps({"images": [base64.b64encode(b"painted").decode()], "finish_reasons": [None]}).encode()
    return {"body": io.BytesIO(payload)}


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.table = mock.MagicMock()
        self.s3 = mock.MagicMock()
        self.text = mock.MagicMock()
        self.photo = mock.MagicMock()
        self.image = mock.MagicMock()
        for name, value in (("TABLE", self.table), ("S3", self.s3), ("TEXT_CLIENT", self.text),
                            ("PHOTO_CLIENT", self.photo), ("IMAGE_CLIENT", self.image)):
            mock.patch.object(worker, name, value).start()
        self.addCleanup(mock.patch.stopall)
        brief = {"rejected": False, "title": "T", "caption": "C", "story": "You are...", "prompt": "P",
                 "negative_prompt": "N", "palette": ["#112233"]}
        self.text.converse.return_value = {"output": {"message": {"content": [{"text": json.dumps(brief)}]}}}
        self.s3.get_object.return_value = {"Body": io.BytesIO(b"\xff\xd8\xffphoto")}
        self.photo.invoke_model.return_value = _bedrock_image_response()
        self.image.invoke_model.return_value = _bedrock_image_response()

    def test_photo_job_uses_control_structure_and_deletes_upload(self):
        self.table.get_item.return_value = {"Item": {"id": "c" * 32, "status": "QUEUED", "era": "victorian",
                                                     "role": "inventor", "style": "baroque_oil",
                                                     "photoKey": "uploads/c.jpg", "likeness": "artistic"}}
        worker.handler({"id": "c" * 32}, None)
        content = self.text.converse.call_args.kwargs["messages"][0]["content"]
        self.assertEqual(content[0]["image"]["format"], "jpeg")
        self.assertIn("photo of the visitor", self.text.converse.call_args.kwargs["system"][0]["text"])
        body = json.loads(self.photo.invoke_model.call_args.kwargs["body"])
        self.assertEqual(body["control_strength"], catalog.LIKENESS["artistic"]["strength"])
        self.image.invoke_model.assert_not_called()
        self.s3.delete_object.assert_called_once_with(Bucket="b", Key="uploads/c.jpg")
        self.assertEqual(self.s3.put_object.call_args.kwargs["Key"], f"gallery/{'c' * 32}.jpg")

    def test_photo_deleted_even_when_rejected(self):
        self.text.converse.return_value = {"output": {"message": {"content": [
            {"text": json.dumps({"rejected": True, "reason": "No person visible."})}]}}}
        self.table.get_item.return_value = {"Item": {"id": "d" * 32, "status": "QUEUED", "era": "victorian",
                                                     "role": "inventor", "style": "baroque_oil",
                                                     "photoKey": "uploads/d.jpg"}}
        worker.handler({"id": "d" * 32}, None)
        self.photo.invoke_model.assert_not_called()
        self.s3.delete_object.assert_called_once_with(Bucket="b", Key="uploads/d.jpg")

    def test_text_only_job_uses_ultra(self):
        self.table.get_item.return_value = {"Item": {"id": "e" * 32, "status": "QUEUED", "era": "victorian",
                                                     "role": "inventor", "style": "baroque_oil"}}
        worker.handler({"id": "e" * 32}, None)
        self.image.invoke_model.assert_called_once()
        self.photo.invoke_model.assert_not_called()
        self.s3.delete_object.assert_not_called()
        self.assertEqual(len(self.text.converse.call_args.kwargs["messages"][0]["content"]), 1)


class WorkerJsonTests(unittest.TestCase):
    def test_extract_json_from_fenced_text(self):
        self.assertEqual(worker._extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        with self.assertRaises(ValueError):
            worker._extract_json("no json here")


if __name__ == "__main__":
    unittest.main()
