import os
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now_datetime

from erpnext_s3_integration import api, backup_hooks
from erpnext_s3_integration.file_hooks import delete_file_data_content, generate_s3_key
from erpnext_s3_integration.s3_client import S3Client


class TestS3Integration(IntegrationTestCase):
	def setUp(self):
		self.settings = frappe._dict(
			aws_access_key_id="test_key",
			aws_secret_access_key="test_secret",
			region_name="us-east-1",
			bucket_name="test-bucket",
			folder_prefix="test-prefix",
			enable_attachments_s3=1,
			delete_from_s3_on_file_delete=1,
			stream_from_s3=0,
			enable_backups_s3=1,
			backup_cron_expression="0 2 * * *",
			create_new_backup_before_sync=1,
		)
		get_single = frappe.get_single
		self.start_patch(
			"frappe.get_single",
			side_effect=lambda doctype: (
				self.settings if doctype == "S3 Integration Settings" else get_single(doctype)
			),
		)
		self.s3_client = self.start_patch("erpnext_s3_integration.s3_client.S3Client").return_value

	def start_patch(self, target, **kwargs):
		patcher = patch(target, **kwargs)
		self.addCleanup(patcher.stop)
		return patcher.start()

	def insert_file(self, **values):
		file_doc = frappe.get_doc({"doctype": "File", "file_name": "s3_test.txt", **values})
		file_doc.insert(ignore_permissions=True)
		return file_doc

	def insert_s3_file_record(self, file_url, content_hash):
		file_doc = frappe.get_doc(
			{"doctype": "File", "file_name": "shared.txt", "file_url": file_url, "content_hash": content_hash}
		)
		file_doc.flags.copy_from_existing_file = True
		file_doc.insert(ignore_permissions=True)
		return file_doc

	def test_upload_stores_file_on_s3_only(self):
		file_doc = self.insert_file(content=frappe.generate_hash(), is_private=1)

		_stream, key, content_type = self.s3_client.upload_fileobj.call_args.args
		self.assertTrue(key.startswith("test-prefix/private/"))
		self.assertEqual(content_type, "text/plain")
		self.assertFalse(self.s3_client.upload_fileobj.call_args.kwargs["is_public"])
		self.assertEqual(file_doc.file_url, f"/s3/{key}")
		self.assertFalse(os.path.exists(frappe.get_site_path("private", "files", file_doc.file_name)))

	def test_upload_writes_to_disk_when_disabled(self):
		self.settings.enable_attachments_s3 = 0
		file_doc = self.insert_file(content=frappe.generate_hash(), is_private=1)
		self.addCleanup(file_doc.delete_file_from_filesystem)

		self.s3_client.upload_fileobj.assert_not_called()
		self.assertTrue(file_doc.file_url.startswith("/private/files/"))
		self.assertTrue(os.path.exists(file_doc.get_full_path()))

	def test_delete_keeps_shared_object_and_waits_for_commit(self):
		file_url = f"/s3/test-prefix/{frappe.generate_hash()}.txt"
		first = self.insert_s3_file_record(file_url, content_hash=frappe.generate_hash())
		second = self.insert_s3_file_record(file_url, content_hash=frappe.generate_hash())

		first.delete(ignore_permissions=True)
		frappe.db.after_commit.run()
		self.s3_client.delete_object.assert_not_called()

		second.delete(ignore_permissions=True)
		self.s3_client.delete_object.assert_not_called()
		frappe.db.after_commit.run()
		self.s3_client.delete_object.assert_called_once_with(file_url.removeprefix("/s3/"))

	def test_rolled_back_insert_deletes_object_at_once(self):
		file_doc = frappe.new_doc("File", file_url="/s3/test-prefix/rolled_back.txt")
		file_doc.flags.new_file = True

		delete_file_data_content(file_doc)

		self.s3_client.delete_object.assert_called_once_with("test-prefix/rolled_back.txt")

	def test_generate_s3_key(self):
		new_file = frappe.new_doc("File", file_name="My test file.txt", is_private=0)
		key = generate_s3_key(new_file, self.settings)
		self.assertRegex(key, r"^test-prefix/public/\w{10}-My_test_file\.txt$")

		local_file = frappe.new_doc("File", file_url="/private/files/a.txt")
		self.assertEqual(generate_s3_key(local_file, self.settings), "test-prefix/private/files/a.txt")

		s3_file = frappe.new_doc("File", file_url="/s3/other/a.txt")
		self.assertEqual(generate_s3_key(s3_file, self.settings), "other/a.txt")

	def test_existing_s3_file_access_still_works_when_uploads_disabled(self):
		self.settings.enable_attachments_s3 = 0
		self.s3_client.generate_presigned_url.return_value = "https://example.com/test-file"
		key = f"test-prefix/{frappe.generate_hash()}.txt"
		self.insert_s3_file_record(f"/s3/{key}", content_hash=None)

		frappe.local.form_dict = frappe._dict({"key": key})
		frappe.local.response = frappe._dict()
		api.get_file()

		self.assertEqual(frappe.local.response["type"], "redirect")
		self.assertEqual(frappe.local.response["location"], "https://example.com/test-file")


class TestS3Client(IntegrationTestCase):
	@patch("boto3.client")
	def test_s3_client_init(self, mock_boto_client):
		settings = MagicMock(
			aws_access_key_id="test_key",
			region_name="us-east-1",
			bucket_name="test-bucket",
			endpoint_url="http://localhost:9000",
			use_path_style=1,
		)
		settings.get_password.return_value = "test_secret"
		with patch("frappe.get_single", return_value=settings):
			S3Client()

		kwargs = mock_boto_client.call_args.kwargs
		self.assertEqual(kwargs["aws_secret_access_key"], "test_secret")
		self.assertEqual(kwargs["endpoint_url"], "http://localhost:9000")
		self.assertEqual(kwargs["config"].s3["addressing_style"], "path")


class TestBackupSync(IntegrationTestCase):
	def setUp(self):
		self.settings = frappe._dict(
			enable_backups_s3=1,
			backup_cron_expression="0 2 * * *",
			create_new_backup_before_sync=1,
		)
		for target, attribute in [
			("frappe.get_single", "get_single"),
			("frappe.enqueue", "enqueue"),
			("frappe.db.set_single_value", "set_single_value"),
		]:
			patcher = patch(target, return_value=self.settings if attribute == "get_single" else None)
			self.addCleanup(patcher.stop)
			setattr(self, attribute, patcher.start())

	def test_first_tick_only_records_start_time(self):
		backup_hooks.scheduled_backup_and_sync()

		self.enqueue.assert_not_called()
		self.set_single_value.assert_called_once()

	def test_tick_before_due_time_does_nothing(self):
		self.settings.last_backup_sync = now_datetime()

		backup_hooks.scheduled_backup_and_sync()

		self.enqueue.assert_not_called()
		self.set_single_value.assert_not_called()

	def test_due_tick_enqueues_one_long_job_and_records_attempt(self):
		self.settings.last_backup_sync = add_days(now_datetime(), -2)

		backup_hooks.scheduled_backup_and_sync()

		self.enqueue.assert_called_once()
		self.assertEqual(self.enqueue.call_args.kwargs["queue"], "long")
		self.assertTrue(self.enqueue.call_args.kwargs["deduplicate"])
		self.set_single_value.assert_called_once()

	@patch("erpnext_s3_integration.backup_hooks.log_s3_sync")
	@patch("erpnext_s3_integration.s3_client.S3Client")
	def test_upload_backup_uploads_only_this_runs_files(self, mock_client_class, mock_log):
		settings = frappe._dict(upload_db_backup=1, upload_files_backup=0, keep_local_backups=0)
		with tempfile.TemporaryDirectory() as directory:
			paths = {}
			for name in ["database.sql.gz", "site_config_backup.json", "files.tar", "private-files.tar"]:
				paths[name] = os.path.join(directory, f"20261121_020000-site-{name}")
				open(paths[name], "w").close()
			backup = SimpleNamespace(
				backup_path_db=paths["database.sql.gz"],
				backup_path_conf=paths["site_config_backup.json"],
				backup_path_files=paths["files.tar"],
				backup_path_private_files=paths["private-files.tar"],
			)

			backup_hooks.upload_backup(settings, backup)

			uploaded_keys = [
				call.args[1] for call in mock_client_class.return_value.upload_fileobj.call_args_list
			]
			self.assertEqual(len(uploaded_keys), 2)
			self.assertTrue(all(key.startswith(f"backups/{frappe.local.site}/") for key in uploaded_keys))
			self.assertFalse(os.path.exists(backup.backup_path_db))
			self.assertTrue(os.path.exists(backup.backup_path_files))
		mock_log.assert_called_once_with(
			"Success", f"Synced 2 backup files to S3 for site {frappe.local.site}"
		)

	@patch("erpnext_s3_integration.backup_hooks.log_s3_sync")
	def test_cleanup_old_backups_uses_public_client(self, mock_log_s3_sync):
		s3_client = MagicMock()
		s3_client.bucket_name = "test-bucket"
		paginator = s3_client.client.get_paginator.return_value
		paginator.paginate.return_value = [
			{
				"Contents": [
					{
						"Key": "backups/site/old-file.sql.gz",
						"LastModified": add_days(frappe.utils.now_datetime(), -10).astimezone(),
					}
				]
			}
		]

		backup_hooks.cleanup_old_backups(s3_client, "backups/site/", 7)

		s3_client.client.get_paginator.assert_called_once_with("list_objects_v2")
		s3_client.delete_object.assert_called_once_with("backups/site/old-file.sql.gz")
		self.assertTrue(mock_log_s3_sync.called)
