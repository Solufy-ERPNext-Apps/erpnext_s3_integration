import os

import frappe


def after_backup():
	"""Uploads database and file backups to S3 after a Frappe backup runs."""
	settings = frappe.get_single("S3 Integration Settings")
	if not settings.enable_backups_s3:
		return

	if not settings.upload_db_backup and not settings.upload_files_backup:
		return

	site_name = frappe.local.site
	# standard frappe backup path: sites/site_name/private/backups
	backup_path = frappe.utils.get_site_path("private", "backups")

	if not os.path.exists(backup_path):
		error_msg = f"Backup directory not found at {backup_path}"
		frappe.log_error(error_msg, "S3 Backup Sync Error")
		log_s3_sync("Failed", error_msg)
		return

	from erpnext_s3_integration.s3_client import S3Client

	s3_client = S3Client()

	# Get folders
	folder_prefix = settings.get("folder_prefix") or ""
	if folder_prefix and not folder_prefix.endswith("/"):
		folder_prefix += "/"

	backup_prefix = settings.get("backup_folder_prefix") or "backups"
	if backup_prefix and not backup_prefix.endswith("/"):
		backup_prefix += "/"

	# Frappe creates these 3 files typically:
	# YYYYMMDD_HHMMSS-site_name-database.sql.gz
	# YYYYMMDD_HHMMSS-site_name-files.tar
	# YYYYMMDD_HHMMSS-site_name-private-files.tar

	import datetime

	today = datetime.datetime.now()
	date_str = today.strftime("%Y-%m-%d")
	today_str = today.strftime("%Y%m%d")

	# Find today's backups
	files = os.listdir(backup_path)

	uploaded_count = 0
	for file in files:
		if file.startswith(today_str):
			# Determine type
			is_db = "-database.sql.gz" in file
			is_files = "-files.tar" in file or "-private-files.tar" in file

			if (is_db and not settings.upload_db_backup) or (is_files and not settings.upload_files_backup):
				continue

			# Construct S3 Key
			# Pattern: [{folder_prefix}/]{backup_folder_prefix}/{site_name}/YYYY-MM-DD/{filename}
			s3_key = f"{folder_prefix}{backup_prefix}{site_name}/{date_str}/{file}"
			full_path = os.path.join(backup_path, file)

			try:
				with open(full_path, "rb") as fileobj:  # nosemgrep
					s3_client.upload_fileobj(fileobj, s3_key, None, False)
					uploaded_count += 1

				# Optionally remove local
				if not settings.keep_local_backups:
					os.remove(full_path)
			except Exception as e:
				error_msg = f"S3 Backup Sync Failed for {file}: {e}"
				frappe.log_error(error_msg, "S3 Backup Sync")
				log_s3_sync("Failed", error_msg)

	if uploaded_count > 0:
		msg = f"Successfully synced {uploaded_count} backup files to S3 for site {site_name}"
		frappe.logger().info(msg)
		log_s3_sync("Success", msg)
	else:
		log_s3_sync("Failed", "No backup files were found or synced to S3.")

	# Cleanup old backups
	retention_days = settings.get("delete_backups_older_than_days") or 0
	if retention_days > 0:
		cleanup_old_backups(s3_client, f"{folder_prefix}{backup_prefix}{site_name}/", retention_days)


def cleanup_old_backups(s3_client, prefix, retention_days):
	import datetime

	cutoff_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=retention_days)
	deleted_count = 0

	try:
		paginator = s3_client.client.get_paginator("list_objects_v2")
		for page in paginator.paginate(Bucket=s3_client.bucket_name, Prefix=prefix):
			if "Contents" in page:
				for obj in page["Contents"]:
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


def scheduled_backup_and_sync():
	"""Triggered by Frappe scheduler 'all' event (runs every ~4 mins). Evaluates the frontend CRON."""
	settings = frappe.get_single("S3 Integration Settings")
	if not settings.enable_backups_s3 or not settings.backup_cron_expression:
		return

	import datetime

	from croniter import CroniterBadCronError, croniter
	from frappe.utils import get_datetime, now_datetime

	try:
		now = now_datetime()
		# Fallback to creation if never run
		last_run = get_datetime(settings.last_backup_sync or (now - datetime.timedelta(days=1)))

		cron = croniter(settings.backup_cron_expression, last_run)
		next_run = cron.get_next(datetime.datetime)

		if now >= next_run:
			if settings.get("create_new_backup_before_sync", 1):
				from frappe.utils.backups import backup

				backup(with_files=settings.upload_files_backup)

			after_backup()

			# Update the last sync time
			frappe.db.set_single_value(
				"S3 Integration Settings",
				"last_backup_sync",
				now,
			)
			frappe.db.commit()  # nosemgrep

	except CroniterBadCronError:
		frappe.log_error(
			f"Invalid CRON expression in S3 Settings: {settings.backup_cron_expression}",
			"S3 Backup Sync Error",
		)
	except Exception as e:
		log_s3_sync(
			"Failed",
			f"Scheduled S3 Backup Failed: {e!s}\n\n{frappe.get_traceback()}",
		)
