import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext_s3_integration import api
from erpnext_s3_integration.file_hooks import generate_s3_key
from erpnext_s3_integration.s3_client import S3Client


class TestS3Integration(FrappeTestCase):
	def setUp(self):
		self.settings = frappe.get_doc("S3 Integration Settings", "S3 Integration Settings")
		self.settings.aws_access_key_id = "test_key"
		self.settings.aws_secret_access_key = "test_secret"
		self.settings.region_name = "us-east-1"
		self.settings.bucket_name = "test-bucket"
		self.settings.folder_prefix = "test-prefix"
		self.settings.enable_attachments_s3 = 1
		self.settings.delete_from_s3_on_file_delete = 1

		# Save to DB so get_single works natively during tests
		self.settings.flags.ignore_mandatory = True
		self.settings.save(ignore_permissions=True)

		# For tests we won't actually encrypt to DB to avoid complexities
		# We'll mock get_password
		patcher = patch(
			"erpnext_s3_integration.s3_client.S3Client.get_password",
			return_value="test_secret",
		)
		self.mock_get_password = patcher.start()
		self.addCleanup(patcher.stop)

	@patch("boto3.client")
	def test_s3_client_init(self, mock_boto_client):
		S3Client()
		mock_boto_client.assert_called_once()

		# Test path style config
		self.settings.use_path_style = 1
		self.settings.endpoint_url = "http://localhost:9000"
		self.settings.save(ignore_permissions=True)
		S3Client()

		kwargs = mock_boto_client.call_args[1]
		self.assertEqual(kwargs["endpoint_url"], "http://localhost:9000")
		self.assertTrue(kwargs["config"].s3["addressing_style"] == "path")

	@patch("frappe.utils.redis_wrapper.RedisWrapper.lpush")
	@patch("erpnext_s3_integration.s3_client.S3Client.upload_fileobj")
	def test_file_upload_hook(self, mock_upload, mock_lpush):
		# Create a dummy file doc via quick method directly to mimic upload behavior
		import base64

		# We use frappe.get_doc but ensure content is handled like an upload
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "test_s3_upload.txt",
				"content": b"test content",  # Bytes
				"is_private": 1,
			}
		)

		# Bypass frappe's local path validation for S3 urls in tests
		file_doc.validate_file_path = lambda: None
		file_doc.validate_file_url = lambda: None
		file_doc.validate_file_on_disk = lambda: None

		file_doc.insert()

		# Check if upload was called
		self.assertTrue(mock_upload.called)

		# Check if file URL was updated appropriately
		self.assertTrue(file_doc.file_url.startswith("/s3/test-prefix/attachments/private/"))

		# Assert content is cleared so it isn't saved to disk
		self.assertIsNone(file_doc.content)

	@patch("frappe.utils.redis_wrapper.RedisWrapper.lpush")
	@patch("erpnext_s3_integration.s3_client.S3Client.delete_object")
	@patch("erpnext_s3_integration.s3_client.S3Client.upload_fileobj")
	def test_file_delete_hook(
		self,
		mock_upload,
		mock_delete,
		mock_lpush,
	):
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "test_s3_delete.txt",
				"content": b"test content",
				"is_private": 1,
			}
		)

		file_doc.validate_file_path = lambda: None
		file_doc.validate_file_url = lambda: None
		file_doc.validate_file_on_disk = lambda: None

		file_doc.insert()

		# Now delete it
		file_doc.delete()

		# Verify S3 delete was called
		self.assertTrue(mock_delete.called)

	def test_generate_s3_key(self):
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "My test file 123.txt",
				"attached_to_doctype": "Sales Invoice",
				"is_private": 0,
			}
		)

		key = generate_s3_key(file_doc, self.settings)
		self.assertTrue(key.startswith("test-prefix/attachments/public/"))
		self.assertIn("/Sales_Invoice/", key)
		self.assertTrue(key.endswith("My_test_file_123.txt"))

	@patch("erpnext_s3_integration.s3_client.S3Client.generate_presigned_url")
	def test_existing_s3_file_access_still_works_when_uploads_disabled(self, mock_generate_presigned_url):
		mock_generate_presigned_url.return_value = "https://example.com/test-file"

		self.settings.enable_attachments_s3 = 0
		self.settings.stream_from_s3 = 0
		self.settings.save(ignore_permissions=True)

		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "existing_on_s3.txt",
				"file_url": "/s3/test-prefix/existing_on_s3.txt",
				"is_private": 0,
			}
		).insert(ignore_permissions=True)

		self.addCleanup(lambda: frappe.delete_doc("File", file_doc.name, force=1, ignore_permissions=True))

		frappe.local.form_dict = frappe._dict({"key": "test-prefix/existing_on_s3.txt"})
		frappe.local.response = frappe._dict()

		api.get_file()

		self.assertEqual(frappe.local.response["type"], "redirect")
		self.assertEqual(frappe.local.response["location"], "https://example.com/test-file")
