import io
import unittest
from unittest.mock import Mock, patch

import boto3
import frappe
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from erpnext_s3_integration.s3_client import S3Client


class TestUploadStream(unittest.TestCase):
	def setUp(self):
		self.client = object.__new__(S3Client)
		self.client.bucket_name = "test-bucket"
		self.client._client = Mock()

	def check_retry(self, source, expected):
		payloads = []
		arguments = []

		def upload(stream, bucket, key, ExtraArgs):
			payloads.append(stream.read())
			arguments.append(dict(ExtraArgs))
			stream.close()
			if len(payloads) == 1:
				raise ClientError({"Error": {"Code": "AccessControlListNotSupported"}}, "PutObject")

		self.client._client.upload_fileobj.side_effect = upload
		self.assertTrue(self.client.upload_fileobj(source, "patient.csv", "text/csv", is_public=True))
		self.assertFalse(source.closed)
		self.assertEqual(payloads, [expected, expected])
		self.assertEqual(arguments, [{"ContentType": "text/csv", "ACL": "public-read"}, {"ContentType": "text/csv"}])

	def test_acl_retry_preserves_stream(self):
		with io.BytesIO(b"Patient,Mobile\nExample,1234567890\n") as source:
			self.check_retry(source, source.getvalue())

	def test_acl_retry_preserves_start_position(self):
		with io.BytesIO(b"prefix:payload") as source:
			source.seek(7)
			self.check_retry(source, b"payload")

	def test_private_upload_preserves_stream(self):
		self.client._client.upload_fileobj.side_effect = lambda stream, *args, **kwargs: stream.close()
		with io.BytesIO(b"private data") as source:
			self.client.upload_fileobj(source, "private.csv")
			self.assertFalse(source.closed)
		self.client._client.upload_fileobj.assert_called_once()
		self.assertNotIn("ACL", self.client._client.upload_fileobj.call_args.kwargs["ExtraArgs"])

	def test_other_s3_errors_are_not_retried(self):
		self.client._client.upload_fileobj.side_effect = ClientError({"Error": {"Code": "AccessDenied"}}, "PutObject")
		with patch("erpnext_s3_integration.s3_client.frappe.log_error"):
			with io.BytesIO(b"data") as source:
				with self.assertRaises(frappe.ValidationError):
					self.client.upload_fileobj(source, "data.txt", is_public=True)
		self.client._client.upload_fileobj.assert_called_once()

	def test_retry_with_real_sdk_and_stubbed_responses(self):
		self.client._client = boto3.client(
			"s3", aws_access_key_id="test", aws_secret_access_key="test", region_name="us-east-1",
		)
		with Stubber(self.client._client) as stub:
			stub.add_client_error("put_object", service_error_code="AccessControlListNotSupported", http_status_code=400)
			stub.add_response("put_object", {"ETag": '"test"'})
			with io.BytesIO(b"data") as source:
				self.assertTrue(self.client.upload_fileobj(source, "data.txt", is_public=True))
				self.assertFalse(source.closed)
			stub.assert_no_pending_responses()
