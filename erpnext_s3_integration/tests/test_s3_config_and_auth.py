import os
from unittest.mock import MagicMock, patch

import frappe
from botocore.exceptions import ClientError
from frappe.tests.utils import FrappeTestCase

from erpnext_s3_integration import api
from erpnext_s3_integration.s3_client import (
	S3Client,
	parse_bool,
	resolve_content_headers,
	resolve_s3_config,
)


class TestS3ConfigAndAuth(FrappeTestCase):
	def setUp(self):
		original_user = frappe.session.user
		self.addCleanup(frappe.set_user, original_user)
		self.settings = frappe.get_doc("S3 Integration Settings", "S3 Integration Settings")
		self.settings.aws_access_key_id = ""
		self.settings.aws_secret_access_key = ""
		self.settings.region_name = ""
		self.settings.bucket_name = ""
		self.settings.use_path_style = 0
		self.settings.use_public_read_acl = 0
		self.settings.enable_attachments_s3 = 0
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

	@patch.dict(os.environ, {"AWS_S3_USE_PATH_STYLE": "0"}, clear=False)
	def test_resolve_s3_config_doc_type_true_overrides_environment(self):
		self.settings.use_path_style = 1

		config = resolve_s3_config(self.settings)

		self.assertTrue(config["use_path_style"])

	@patch.dict(os.environ, {"AWS_S3_USE_PATH_STYLE": "1"}, clear=False)
	def test_resolve_s3_config_site_config_false_overrides_environment(self):
		with patch.dict(frappe.conf, {"s3_use_path_style": "0"}):
			config = resolve_s3_config(self.settings)

		self.assertFalse(config["use_path_style"])

	@patch.dict(
		os.environ,
		{
			"AWS_ACCESS_KEY_ID": "env_key",
			"AWS_SECRET_ACCESS_KEY": "env_secret",
			"AWS_DEFAULT_REGION": "env-region",
			"AWS_S3_BUCKET": "env-bucket",
			"AWS_ENDPOINT_URL": "https://env.example.test",
		},
		clear=False,
	)
	def test_resolve_s3_config_from_site_config_before_environment(self):
		site_config = {
			"s3_access_key_id": "site_key",
			"s3_secret_access_key": "site_secret",
			"s3_region": "site-region",
			"s3_bucket": "site-bucket",
			"s3_endpoint_url": "https://site.example.test",
		}
		with patch.dict(frappe.conf, site_config):
			config = resolve_s3_config(self.settings)

		self.assertEqual(config["aws_access_key_id"], "site_key")
		self.assertEqual(config["aws_secret_access_key"], "site_secret")
		self.assertEqual(config["region_name"], "site-region")
		self.assertEqual(config["bucket_name"], "site-bucket")
		self.assertEqual(config["endpoint_url"], "https://site.example.test")

	@patch.dict(
		os.environ,
		{
			"AWS_ACCESS_KEY_ID": "env_key",
			"AWS_SECRET_ACCESS_KEY": "env_secret",
			"AWS_DEFAULT_REGION": "env-region",
			"AWS_S3_BUCKET": "env-bucket",
			"AWS_ENDPOINT_URL": "https://env.example.test",
		},
		clear=False,
	)
	@patch("erpnext_s3_integration.s3_client.get_decrypted_password", return_value="doc_secret")
	def test_resolve_s3_config_from_doc_type_before_site_and_environment(self, _mock_password):
		self.settings.aws_access_key_id = "doc_key"
		self.settings.aws_secret_access_key = "stored-password-placeholder"
		self.settings.region_name = "doc-region"
		self.settings.bucket_name = "doc-bucket"
		self.settings.endpoint_url = "https://doc.example.test"
		site_config = {
			"s3_access_key_id": "site_key",
			"s3_secret_access_key": "site_secret",
			"s3_region": "site-region",
			"s3_bucket": "site-bucket",
			"s3_endpoint_url": "https://site.example.test",
		}

		with patch.dict(frappe.conf, site_config):
			config = resolve_s3_config(self.settings)

		self.assertEqual(config["aws_access_key_id"], "doc_key")
		self.assertEqual(config["aws_secret_access_key"], "doc_secret")
		self.assertEqual(config["region_name"], "doc-region")
		self.assertEqual(config["bucket_name"], "doc-bucket")
		self.assertEqual(config["endpoint_url"], "https://doc.example.test")

	@patch.dict(
		os.environ,
		{
			"AWS_REGION": "env-fallback-region",
			"AWS_ENDPOINT_URL": "https://env-fallback.example.test",
		},
		clear=True,
	)
	def test_resolve_s3_config_supports_partial_fallback_and_aws_region(self):
		self.settings.aws_access_key_id = "doc_key"
		with patch.dict(
			frappe.conf,
			{
				"s3_secret_access_key": "site_secret",
				"s3_bucket": "site-bucket",
			},
			clear=True,
		):
			config = resolve_s3_config(self.settings)

		self.assertEqual(config["aws_access_key_id"], "doc_key")
		self.assertEqual(config["aws_secret_access_key"], "site_secret")
		self.assertEqual(config["bucket_name"], "site-bucket")
		self.assertEqual(config["region_name"], "env-fallback-region")
		self.assertEqual(config["endpoint_url"], "https://env-fallback.example.test")

	@patch.dict(os.environ, {"AWS_SECRET_ACCESS_KEY": "env_secret"}, clear=True)
	@patch(
		"erpnext_s3_integration.s3_client.get_decrypted_password",
		side_effect=RuntimeError("cannot decrypt"),
	)
	def test_secret_decryption_failure_falls_back_to_environment(self, _mock_password):
		self.settings.aws_secret_access_key = "stored-password-placeholder"

		with patch.dict(frappe.conf, {}, clear=True):
			config = resolve_s3_config(self.settings)

		self.assertEqual(config["aws_secret_access_key"], "env_secret")

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
		self.settings.enable_attachments_s3 = 1
		self.settings.validate()
		self.assertEqual(self.settings.aws_access_key_id, "")
		self.assertEqual(self.settings.aws_secret_access_key, "")
		self.assertEqual(self.settings.region_name, "")
		self.assertEqual(self.settings.bucket_name, "")

	@patch.dict(os.environ, {}, clear=True)
	def test_validate_fails_when_effective_required_config_is_missing(self):
		self.settings.enable_attachments_s3 = 1
		with patch.dict(frappe.conf, {}, clear=True), self.assertRaises(frappe.ValidationError):
			self.settings.validate()

		self.assertEqual(self.settings.aws_access_key_id, "")
		self.assertEqual(self.settings.aws_secret_access_key, "")
		self.assertEqual(self.settings.region_name, "")
		self.assertEqual(self.settings.bucket_name, "")

	@patch("erpnext_s3_integration.s3_client._load_boto3", return_value=(None, ClientError))
	def test_acl_emission_when_use_public_read_acl_enabled(self, _mock_load_boto3):
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
			ExtraArgs={
				"ContentType": "text/plain",
				"ContentDisposition": 'attachment; filename="test_key"; filename*=UTF-8\'\'test_key',
				"ACL": "public-read",
			},
		)

	@patch("erpnext_s3_integration.s3_client._load_boto3", return_value=(None, ClientError))
	def test_acl_non_emission_when_use_public_read_acl_disabled(self, _mock_load_boto3):
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
			ExtraArgs={
				"ContentType": "text/plain",
				"ContentDisposition": 'attachment; filename="test_key"; filename*=UTF-8\'\'test_key',
			},
		)

	@patch("erpnext_s3_integration.s3_client._load_boto3", return_value=(None, ClientError))
	def test_acl_non_emission_for_private_file_when_public_read_acl_enabled(self, _mock_load_boto3):
		s3_client = S3Client.__new__(S3Client)
		s3_client.bucket_name = "test-bucket"
		s3_client.use_public_read_acl = True
		s3_client._client = MagicMock()

		fileobj = MagicMock()
		s3_client.upload_fileobj(fileobj, "private_key", content_type="text/plain", is_public=False)

		s3_client._client.upload_fileobj.assert_called_once_with(
			fileobj,
			"test-bucket",
			"private_key",
			ExtraArgs={
				"ContentType": "text/plain",
				"ContentDisposition": 'attachment; filename="private_key"; filename*=UTF-8\'\'private_key',
			},
		)

	def test_content_headers_preview_only_safe_types(self):
		for filename, supplied_type, expected_type, expected_disposition in (
			("invoice.pdf", None, "application/pdf", "inline"),
			("photo.JPG", None, "image/jpeg", "inline"),
			("vector.svg", None, "image/svg+xml", "attachment"),
			("page.html", None, "text/html", "attachment"),
			("archive.unknown", None, "application/octet-stream", "attachment"),
			("legacy.pdf", "application/octet-stream", "application/pdf", "inline"),
			("spoofed.html", "image/png", "image/png", "attachment"),
			("mismatch.png", "text/html", "text/html", "attachment"),
		):
			with self.subTest(filename=filename):
				content_type, disposition = resolve_content_headers(filename, supplied_type)
				self.assertEqual(content_type, expected_type)
				self.assertTrue(disposition.startswith(f"{expected_disposition};"))

	def test_content_disposition_sanitizes_and_encodes_filename(self):
		content_type, disposition = resolve_content_headers('private/factura "año"\r\n.pdf')

		self.assertEqual(content_type, "application/pdf")
		self.assertTrue(disposition.startswith('inline; filename="factura _ao_.pdf";'))
		self.assertIn("filename*=UTF-8''factura%20%22a%C3%B1o%22.pdf", disposition)
		self.assertNotIn("\r", disposition)
		self.assertNotIn("\n", disposition)

	def test_presigned_url_overrides_legacy_object_response_headers(self):
		s3_client = S3Client.__new__(S3Client)
		s3_client.bucket_name = "test-bucket"
		s3_client._client = MagicMock()
		s3_client._client.generate_presigned_url.return_value = "https://example.test/signed"

		url = s3_client.generate_presigned_url(
			"legacy/object-key",
			expires_in=900,
			filename='factura "año".pdf',
			content_type="application/octet-stream",
		)

		self.assertEqual(url, "https://example.test/signed")
		params = s3_client._client.generate_presigned_url.call_args.kwargs["Params"]
		self.assertEqual(params["ResponseContentType"], "application/pdf")
		self.assertTrue(params["ResponseContentDisposition"].startswith("inline;"))

	@patch("erpnext_s3_integration.s3_client._load_boto3", return_value=(None, ClientError))
	def test_public_acl_unsupported_retries_once_without_acl(self, _mock_load_boto3):
		s3_client = S3Client.__new__(S3Client)
		s3_client.bucket_name = "test-bucket"
		s3_client.use_public_read_acl = True
		s3_client._client = MagicMock()
		acl_error = ClientError(
			{"Error": {"Code": "AccessControlListNotSupported", "Message": "ACLs disabled"}},
			"PutObject",
		)
		attempts = []

		def upload_with_acl_fallback(_fileobj, _bucket, _key, ExtraArgs):
			attempts.append(dict(ExtraArgs))
			if len(attempts) == 1:
				raise acl_error

		s3_client._client.upload_fileobj.side_effect = upload_with_acl_fallback
		fileobj = MagicMock()

		s3_client.upload_fileobj(fileobj, "public_key", content_type="text/plain", is_public=True)

		self.assertEqual(s3_client._client.upload_fileobj.call_count, 2)
		self.assertEqual(attempts[0]["ACL"], "public-read")
		self.assertNotIn("ACL", attempts[1])
		fileobj.seek.assert_called_once_with(0)

	@patch("erpnext_s3_integration.s3_client._load_boto3", return_value=(None, ClientError))
	def test_public_acl_retry_failure_raises_validation_error(self, _mock_load_boto3):
		s3_client = S3Client.__new__(S3Client)
		s3_client.bucket_name = "test-bucket"
		s3_client.use_public_read_acl = True
		s3_client._client = MagicMock()
		acl_error = ClientError(
			{"Error": {"Code": "AccessControlListNotSupported", "Message": "ACLs disabled"}},
			"PutObject",
		)
		retry_error = ClientError(
			{"Error": {"Code": "AccessDenied", "Message": "denied"}},
			"PutObject",
		)
		s3_client._client.upload_fileobj.side_effect = [acl_error, retry_error]

		with self.assertRaises(frappe.ValidationError):
			s3_client.upload_fileobj(MagicMock(), "public_key", is_public=True)

		self.assertEqual(s3_client._client.upload_fileobj.call_count, 2)

	@patch("erpnext_s3_integration.s3_client.S3Client")
	@patch("erpnext_s3_integration.api.frappe.get_doc")
	@patch("erpnext_s3_integration.api.frappe.db.get_value", return_value="public-file")
	def test_api_get_file_guest_access_public_file(self, _mock_get_value, mock_get_doc, mock_s3_client):
		file_obj = MagicMock()
		file_obj.is_private = 0
		file_obj.file_name = "public.txt"
		file_obj.is_downloadable.return_value = True
		mock_get_doc.return_value = file_obj
		mock_s3_client.return_value.generate_presigned_url.return_value = "https://example.com/pub"
		frappe.set_user("Guest")
		frappe.local.form_dict = frappe._dict({"key": "pub_test_key"})
		frappe.local.response = frappe._dict()

		api.get_file()

		file_obj.is_downloadable.assert_called_once_with()
		self.assertEqual(frappe.local.response["type"], "redirect")
		self.assertEqual(frappe.local.response["location"], "https://example.com/pub")

	@patch("erpnext_s3_integration.s3_client.S3Client")
	@patch("erpnext_s3_integration.api.frappe.get_doc")
	@patch("erpnext_s3_integration.api.frappe.db.get_value", return_value="private-file")
	def test_api_get_file_guest_access_private_file_raises_permission_error(
		self, _mock_get_value, mock_get_doc, mock_s3_client
	):
		file_obj = MagicMock()
		file_obj.is_private = 1
		file_obj.is_downloadable.return_value = True
		mock_get_doc.return_value = file_obj
		frappe.set_user("Guest")
		frappe.local.form_dict = frappe._dict({"key": "priv_test_key"})
		frappe.local.response = frappe._dict()

		with self.assertRaises(frappe.PermissionError):
			api.get_file()

		file_obj.is_downloadable.assert_not_called()
		mock_s3_client.assert_not_called()

	@patch("erpnext_s3_integration.s3_client.S3Client")
	@patch("erpnext_s3_integration.api.frappe.get_doc")
	@patch("erpnext_s3_integration.api.frappe.db.get_value", return_value="private-file")
	def test_api_get_file_authenticated_authorized_private_file(
		self, _mock_get_value, mock_get_doc, mock_s3_client
	):
		file_obj = MagicMock()
		file_obj.is_private = 1
		file_obj.file_name = "authorized.txt"
		file_obj.is_downloadable.return_value = True
		mock_get_doc.return_value = file_obj
		mock_s3_client.return_value.generate_presigned_url.return_value = "https://example.com/private"

		frappe.set_user("Administrator")
		frappe.local.form_dict = frappe._dict({"key": "authorized_private_key"})
		frappe.local.response = frappe._dict()

		api.get_file()

		file_obj.is_downloadable.assert_called_once_with()
		self.assertEqual(frappe.local.response["type"], "redirect")
		self.assertEqual(frappe.local.response["location"], "https://example.com/private")

	@patch("erpnext_s3_integration.s3_client.S3Client")
	@patch("erpnext_s3_integration.api.frappe.get_doc")
	@patch("erpnext_s3_integration.api.frappe.db.get_value", return_value="private-file")
	def test_api_get_file_authenticated_unauthorized_private_file(
		self, _mock_get_value, mock_get_doc, mock_s3_client
	):
		file_obj = MagicMock()
		file_obj.is_private = 1
		file_obj.is_downloadable.return_value = False
		mock_get_doc.return_value = file_obj

		frappe.set_user("Administrator")
		frappe.local.form_dict = frappe._dict({"key": "unauthorized_private_key"})
		frappe.local.response = frappe._dict()

		with self.assertRaises(frappe.PermissionError):
			api.get_file()

		file_obj.is_downloadable.assert_called_once_with()
		mock_s3_client.assert_not_called()

	def test_api_get_file_non_existent_file_raises_does_not_exist_error(self):
		frappe.set_user("Administrator")
		frappe.local.form_dict = frappe._dict({"key": "non_existent_key_12345"})
		frappe.local.response = frappe._dict()

		with self.assertRaises(frappe.DoesNotExistError):
			api.get_file()
