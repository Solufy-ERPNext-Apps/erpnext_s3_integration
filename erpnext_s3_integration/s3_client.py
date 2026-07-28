import os

import frappe
from frappe import _
from frappe.utils.password import get_decrypted_password


def _load_boto3():
	"""Import boto3 lazily so Desk boot is not blocked by optional S3 dependencies."""
	try:
		import boto3
		from botocore.exceptions import ClientError
	except Exception:
		frappe.throw(
			_(
				"S3 dependencies could not be loaded. Please verify the boto3/OpenSSL environment before using S3 features."
			),
			exc=frappe.ValidationError,
		)

	return boto3, ClientError


def parse_bool(val) -> bool:
	"""Parses boolean inputs from strings ('1', 'true', '0', 'false'), ints, or bools."""
	if isinstance(val, bool):
		return val
	if isinstance(val, (int, float)):
		return bool(val)
	if isinstance(val, str):
		val_lower = val.strip().lower()
		if val_lower in ("1", "true", "yes", "on"):
			return True
		if val_lower in ("0", "false", "no", "off", ""):
			return False
	return bool(val)


def resolve_s3_config(settings=None) -> dict:
	"""Resolves effective S3 configuration in order: DocType -> site_config.json -> Environment Variables."""
	if settings is None:
		try:
			settings = frappe.get_single("S3 Integration Settings")
		except Exception:
			settings = None

	def _get_secret(fieldname):
		if not settings or not settings.get(fieldname):
			return None
		try:
			return get_decrypted_password("S3 Integration Settings", "S3 Integration Settings", fieldname)
		except frappe.exceptions.SecretNotFoundError:
			return settings.get(fieldname)
		except Exception:
			return settings.get(fieldname)

	def _get_val(fieldname, site_config_key, env_keys, is_secret=False):
		if settings:
			val = _get_secret(fieldname) if is_secret else settings.get(fieldname)
			if val:
				return val
		if site_config_key:
			val = frappe.conf.get(site_config_key)
			if val:
				return val
		for env_key in env_keys:
			val = os.getenv(env_key)
			if val:
				return val
		return None

	aws_access_key_id = _get_val("aws_access_key_id", "s3_access_key_id", ["AWS_ACCESS_KEY_ID"])
	aws_secret_access_key = _get_val("aws_secret_access_key", "s3_secret_access_key", ["AWS_SECRET_ACCESS_KEY"], is_secret=True)
	region_name = _get_val("region_name", "s3_region", ["AWS_DEFAULT_REGION", "AWS_REGION"])
	bucket_name = _get_val("bucket_name", "s3_bucket", ["AWS_S3_BUCKET"])
	endpoint_url = _get_val("endpoint_url", "s3_endpoint_url", ["AWS_ENDPOINT_URL"])

	use_path_style = False
	if settings and settings.get("use_path_style") is not None:
		use_path_style = parse_bool(settings.use_path_style)
	elif frappe.conf.get("s3_use_path_style") is not None:
		use_path_style = parse_bool(frappe.conf.get("s3_use_path_style"))
	elif os.getenv("AWS_S3_USE_PATH_STYLE") is not None:
		use_path_style = parse_bool(os.getenv("AWS_S3_USE_PATH_STYLE"))

	# Managed strictly from Desk (DocType), default 0 (False). No env fallback for ACL to avoid ambiguity.
	use_public_read_acl = False
	if settings and settings.get("use_public_read_acl") is not None:
		use_public_read_acl = parse_bool(settings.use_public_read_acl)

	folder_prefix = settings.get("folder_prefix") if settings else None

	return {
		"aws_access_key_id": aws_access_key_id,
		"aws_secret_access_key": aws_secret_access_key,
		"region_name": region_name,
		"bucket_name": bucket_name,
		"endpoint_url": endpoint_url,
		"use_path_style": use_path_style,
		"use_public_read_acl": use_public_read_acl,
		"folder_prefix": folder_prefix,
	}


class S3Client:
	def __init__(self):
		self.settings = frappe.get_single("S3 Integration Settings")
		self._client = None
		self.setup_client()

	@property
	def client(self):
		"""Expose the underlying boto3 client for internal callers like backup cleanup."""
		return self._client

	def get_password(self, fieldname):
		# frappe.get_single doesn't decrypt passwords automatically by default in all contexts
		if not self.settings.get(fieldname):
			return None
		try:
			return get_decrypted_password("S3 Integration Settings", "S3 Integration Settings", fieldname)
		except frappe.exceptions.SecretNotFoundError:
			return self.settings.get(fieldname)
		except Exception:
			return self.settings.get(fieldname)

	def setup_client(self):
		boto3, _ = _load_boto3()
		config_data = resolve_s3_config(self.settings)

		aws_access_key_id = config_data.get("aws_access_key_id")
		aws_secret_access_key = config_data.get("aws_secret_access_key")
		region_name = config_data.get("region_name")
		endpoint_url = config_data.get("endpoint_url")
		self.bucket_name = config_data.get("bucket_name")
		self.use_public_read_acl = config_data.get("use_public_read_acl", False)

		if not (aws_access_key_id and aws_secret_access_key):
			frappe.throw(_("AWS Credentials are required to initialize the S3 client."))

		if not self.bucket_name:
			frappe.throw(_("AWS Bucket Name is required."))

		config = boto3.session.Config(signature_version="s3v4")
		if config_data.get("use_path_style"):
			config = boto3.session.Config(signature_version="s3v4", s3={"addressing_style": "path"})

		client_kwargs = {
			"service_name": "s3",
			"aws_access_key_id": aws_access_key_id,
			"aws_secret_access_key": aws_secret_access_key,
			"config": config,
		}

		if region_name:
			client_kwargs["region_name"] = region_name
		if endpoint_url:
			client_kwargs["endpoint_url"] = endpoint_url

		self._client = boto3.client(**client_kwargs)

	def test_connection(self):
		_, client_error = _load_boto3()
		try:
			# Trying to list a bounded number of objects is a good way to verify bucket access
			self._client.list_objects_v2(Bucket=self.bucket_name, MaxKeys=1)
			return True, "Connection successful! Bucket is accessible."
		except client_error as e:
			frappe.log_error(message=frappe.get_traceback(), title="S3 Test Connection Error")
			return False, f"Connection Failed: {e}"
		except Exception as e:
			frappe.log_error(message=frappe.get_traceback(), title="S3 Test Connection Failed")
			return False, f"Connection Failed: {e!s}"

	def upload_fileobj(self, fileobj, key, content_type=None, is_public=False):
		_, client_error = _load_boto3()
		extra_args = {}
		if content_type:
			extra_args["ContentType"] = content_type
		# Only send ACL="public-read" if is_public AND use_public_read_acl is enabled in Desk
		if is_public and getattr(self, "use_public_read_acl", False):
			extra_args["ACL"] = "public-read"

		try:
			self._client.upload_fileobj(fileobj, self.bucket_name, key, ExtraArgs=extra_args)
			return True
		except client_error as e:
			error_code = (e.response or {}).get("Error", {}).get("Code")
			# Buckets with Object Ownership "Bucket owner enforced" reject ACLs.
			# Retry once without ACL so uploads still succeed.
			if error_code == "AccessControlListNotSupported" and "ACL" in extra_args:
				try:
					fileobj.seek(0)
				except Exception:
					pass
				extra_args.pop("ACL", None)
				self._client.upload_fileobj(fileobj, self.bucket_name, key, ExtraArgs=extra_args)
				return True
			frappe.log_error(message=frappe.get_traceback(), title=f"S3 Upload Failed for {key}")
			raise frappe.ValidationError(f"Could not upload file to S3: {e}")
		except Exception as e:
			frappe.log_error(message=frappe.get_traceback(), title=f"S3 Upload Failed for {key}")
			raise frappe.ValidationError(f"Could not upload file to S3: {e}")

	def delete_object(self, key):
		try:
			self._client.delete_object(Bucket=self.bucket_name, Key=key)
			return True
		except Exception:
			frappe.log_error(message=frappe.get_traceback(), title=f"S3 Delete Failed for {key}")
			# We don't raise here, so file deletion won't be blocked if S3 fails
			return False

	def generate_presigned_url(self, key, expires_in=3600):
		try:
			url = self._client.generate_presigned_url(
				"get_object",
				Params={"Bucket": self.bucket_name, "Key": key},
				ExpiresIn=expires_in,
			)
			return url
		except Exception:
			frappe.log_error(
				message=frappe.get_traceback(),
				title=f"S3 URL Generation Failed for {key}",
			)
			return None

	def download_as_stream(self, key):
		try:
			response = self._client.get_object(Bucket=self.bucket_name, Key=key)
			return response["Body"]
		except Exception:
			frappe.log_error(message=frappe.get_traceback(), title=f"S3 Downoad Failed for {key}")
			frappe.throw(f"File {key} not found on S3 or could not be streamed.")
