import os
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext_s3_integration import api
from erpnext_s3_integration.s3_client import S3Client, parse_bool, resolve_s3_config


class TestS3ConfigAndAuth(FrappeTestCase):
	def setUp(self):
		self.settings = frappe.get_doc("S3 Integration Settings", "S3 Integration Settings")
		self.settings.aws_access_key_id = ""
		self.settings.aws_secret_access_key = ""
		self.settings.region_name = ""
		self.settings.bucket_name = ""
		self.settings.use_path_style = 0
		self.settings.use_public_read_acl = 0
		self.settings.enable_attachments_s3 = 1
		self.settings.flags.ignore_mandatory = True
		self.settings.save(ignore_permissions=True)

	def test_parse_bool(self):
		self.assertTrue(parse_bool("1"))
		self.assertTrue(parse_bool("true"))
		self.assertTrue(parse_bool("True"))
		self.assertTrue(parse_bool(True))
		self.assertTrue(parse_bool(1))

		self.assertFalse(parse_bool("0"))
		self.assertFalse(parse_bool("false"))
		self.assertFalse(parse_bool("False"))
		self.assertFalse(parse_bool(False))
		self.assertFalse(parse_bool(0))
		self.assertFalse(parse_bool(""))

	@patch.dict(
		os.environ,
		{
			"AWS_ACCESS_KEY_ID": "env_key",
			"AWS_SECRET_ACCESS_KEY": "env_secret",
			"AWS_DEFAULT_REGION": "us-west-2",
			"AWS_S3_BUCKET": "env-bucket",
			"AWS_S3_USE_PATH_STYLE": "1",
		},
		clear=False,
	)
	def test_resolve_s3_config_from_environment(self):
		config = resolve_s3_config(self.settings)
		self.assertEqual(config["aws_access_key_id"], "env_key")
		self.assertEqual(config["aws_secret_access_key"], "env_secret")
		self.assertEqual(config["region_name"], "us-west-2")
		self.assertEqual(config["bucket_name"], "env-bucket")
		self.assertTrue(config["use_path_style"])
		self.assertFalse(config["use_public_read_acl"])

	@patch.dict(
		os.environ,
		{
			"AWS_ACCESS_KEY_ID": "env_key",
			"AWS_SECRET_ACCESS_KEY": "env_secret",
			"AWS_DEFAULT_REGION": "us-west-2",
			"AWS_S3_BUCKET": "env-bucket",
		},
		clear=False,
	)
	def test_validate_passes_with_environment_credentials(self):
		# Settings DocType is empty for key/secret/bucket, but env has them
		# Validation should pass without throwing or mutating DocType fields
		self.settings.validate()
		self.assertEqual(self.settings.aws_access_key_id, "")

	def test_acl_emission_when_use_public_read_acl_enabled(self):
		s3_client = S3Client.__new__(S3Client)
		s3_client.bucket_name = "test-bucket"
		s3_client.use_public_read_acl = True
		s3_client._client = MagicMock()

		fileobj = MagicMock()
		s3_client.upload_fileobj(fileobj, "test_key", content_type="text/plain", is_public=True)

		# ACL='public-read' should be emitted when use_public_read_acl is True
		s3_client._client.upload_fileobj.assert_called_once_with(
			fileobj,
			"test-bucket",
			"test_key",
			ExtraArgs={"ContentType": "text/plain", "ACL": "public-read"},
		)

	def test_acl_non_emission_when_use_public_read_acl_disabled(self):
		s3_client = S3Client.__new__(S3Client)
		s3_client.bucket_name = "test-bucket"
		s3_client.use_public_read_acl = False
		s3_client._client = MagicMock()

		fileobj = MagicMock()
		s3_client.upload_fileobj(fileobj, "test_key", content_type="text/plain", is_public=True)

		# ACL='public-read' must NOT be emitted when use_public_read_acl is False
		s3_client._client.upload_fileobj.assert_called_once_with(
			fileobj,
			"test-bucket",
			"test_key",
			ExtraArgs={"ContentType": "text/plain"},
		)

	@patch("erpnext_s3_integration.s3_client.S3Client.generate_presigned_url", return_value="https://example.com/pub")
	def test_api_get_file_guest_access_public_file(self, mock_url):
		pub_file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "pub_test.txt",
				"file_url": "/s3/pub_test_key",
				"is_private": 0,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("File", pub_file.name, force=1, ignore_permissions=True))

		frappe.set_user("Guest")
		frappe.local.form_dict = frappe._dict({"key": "pub_test_key"})
		frappe.local.response = frappe._dict()

		api.get_file()
		self.assertEqual(frappe.local.response["type"], "redirect")
		self.assertEqual(frappe.local.response["location"], "https://example.com/pub")

	def test_api_get_file_guest_access_private_file_raises_permission_error(self):
		priv_file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "priv_test.txt",
				"file_url": "/s3/priv_test_key",
				"is_private": 1,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("File", priv_file.name, force=1, ignore_permissions=True))

		frappe.set_user("Guest")
		frappe.local.form_dict = frappe._dict({"key": "priv_test_key"})
		frappe.local.response = frappe._dict()

		with self.assertRaises(frappe.PermissionError):
			api.get_file()

	def test_api_get_file_non_existent_file_raises_does_not_exist_error(self):
		frappe.set_user("Administrator")
		frappe.local.form_dict = frappe._dict({"key": "non_existent_key_12345"})
		frappe.local.response = frappe._dict()

		with self.assertRaises(frappe.DoesNotExistError):
			api.get_file()
