import datetime
import os

import frappe
from frappe.utils import get_datetime, now_datetime

BACKUP_JOB_ID = "erpnext_s3_integration_backup_sync"


def scheduled_backup_and_sync():
	"""Scheduler tick: enqueue a backup sync once the configured cron time has passed."""
	settings = frappe.get_single("S3 Integration Settings")
	if not settings.enable_backups_s3 or not settings.backup_cron_expression:
		return

	from croniter import croniter

	now = now_datetime()
	if settings.last_backup_sync:
		last_run = get_datetime(settings.last_backup_sync)
		if now < croniter(settings.backup_cron_expression, last_run).get_next(datetime.datetime):
			return
		enqueue_backup_and_sync(create_backup=bool(settings.create_new_backup_before_sync))

	# Record the attempt before the job runs so a failing sync is not retried on every tick.
	frappe.db.set_single_value("S3 Integration Settings", "last_backup_sync", now)


def enqueue_backup_and_sync(create_backup=True):
	frappe.enqueue(
		"erpnext_s3_integration.backup_hooks.run_backup_and_sync",
		queue="long",
		timeout=3600,
		job_id=BACKUP_JOB_ID,
		deduplicate=True,
		create_backup=create_backup,
	)


def run_backup_and_sync(create_backup=True):
	"""Take a new local backup (or reuse a recent one) and upload it to S3."""
	from frappe.utils.backups import scheduled_backup

	settings = frappe.get_single("S3 Integration Settings")
	try:
		backup = scheduled_backup(ignore_files=not settings.upload_files_backup, force=create_backup)
		upload_backup(settings, backup)
	except Exception as error:
		log_s3_sync("Failed", f"S3 backup sync failed: {error}\n\n{frappe.get_traceback()}")
		raise


def get_backup_paths(settings, backup):
	paths = []
	if settings.upload_db_backup:
		paths += [backup.backup_path_db, backup.backup_path_conf]
	if settings.upload_files_backup:
		paths += [backup.backup_path_files, backup.backup_path_private_files]
	return [path for path in paths if path and os.path.exists(path)]


def get_backup_prefix(settings):
	folder_prefix = settings.get("folder_prefix") or ""
	if folder_prefix and not folder_prefix.endswith("/"):
		folder_prefix += "/"

	backup_prefix = settings.get("backup_folder_prefix") or "backups"
	if not backup_prefix.endswith("/"):
		backup_prefix += "/"

	return f"{folder_prefix}{backup_prefix}{frappe.local.site}/"


def upload_backup(settings, backup):
	"""Upload the files of one backup run to `<prefix>/<site>/<YYYY-MM-DD>/`."""
	paths = get_backup_paths(settings, backup)
	if not paths:
		log_s3_sync("Failed", "No backup files were found to sync to S3.")
		return

	from erpnext_s3_integration.s3_client import S3Client

	s3_client = S3Client()
	prefix = get_backup_prefix(settings)
	date_folder = now_datetime().strftime("%Y-%m-%d")
	for path in paths:
		with open(path, "rb") as fileobj:  # nosemgrep
			s3_client.upload_fileobj(fileobj, f"{prefix}{date_folder}/{os.path.basename(path)}")
		if not settings.keep_local_backups:
			os.remove(path)

	log_s3_sync("Success", f"Synced {len(paths)} backup files to S3 for site {frappe.local.site}")

	retention_days = settings.get("delete_backups_older_than_days") or 0
	if retention_days > 0:
		cleanup_old_backups(s3_client, prefix, retention_days)


def cleanup_old_backups(s3_client, prefix, retention_days):
	cutoff_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=retention_days)
	deleted_count = 0

	try:
		paginator = s3_client.client.get_paginator("list_objects_v2")
		for page in paginator.paginate(Bucket=s3_client.bucket_name, Prefix=prefix):
			for obj in page.get("Contents", []):
				if obj["LastModified"] < cutoff_date:
					s3_client.delete_object(obj["Key"])
					deleted_count += 1

		if deleted_count > 0:
			log_s3_sync(
				"Success", f"Cleaned up {deleted_count} S3 backup(s) older than {retention_days} days."
			)
	except Exception as e:
		frappe.log_error(f"S3 Backup Cleanup Failed: {e}", "S3 Backup Sync Error")
		log_s3_sync("Failed", f"Backup cleanup failed: {e}")


def log_s3_sync(status, message):
	try:
		if frappe.db.exists("DocType", "S3 Sync Log"):
			log = frappe.new_doc("S3 Sync Log")
			log.status = status
			log.message = message
			log.insert(ignore_permissions=True)
			frappe.db.commit()  # nosemgrep
	except Exception as e:
		frappe.log_error(f"Failed to create S3 Sync Log: {e!s}", "S3 Sync Log Error")
