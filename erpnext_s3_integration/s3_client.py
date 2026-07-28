import mimetypes
import os
import posixpath
import re
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils.password import get_decrypted_password


_INLINE_CONTENT_TYPES = {
	"application/pdf",
	"image/avif",
	"image/gif",
	"image/jpeg",
	"image/png",
	"image/webp",
}
_INVALID_HEADER_VALUE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _safe_content_type(content_type, filename):
	"""Return a valid MIME type, inferring it from the object key when necessary."""
	if content_type:
		content_type = content_type.strip().lower()
		if (
			not _INVALID_HEADER_VALUE.search(content_type)
			and "/" in content_type
			and content_type != "application/octet-stream"
		):
			return content_type

	inferred_type, _encoding = mimetypes.guess_type(filename)
	return inferred_type or "application/octet-stream"


def _content_disposition(filename, content_type):
	"""Build an injection-safe Content-Disposition with a Unicode filename."""
	filename = posixpath.basename(filename.replace("\\", "/")) or "download"
	filename = _INVALID_HEADER_VALUE.sub("", filename) or "download"
	ascii_filename = filename.encode("ascii", "ignore").decode() or "download"
	ascii_filename = ascii_filename.replace("\\", "_").replace('"', "_")
	encoded_filename = quote(filename, safe="")
	inferred_type, _encoding = mimetypes.guess_type(filename)
	disposition = (
		"inline"
		if content_type in _INLINE_CONTENT_TYPES and inferred_type == content_type
		else "attachment"
	)
	return f'{disposition}; filename="{ascii_filename}"; filename*=UTF-8\'\'{encoded_filename}'


def resolve_content_headers(filename, content_type=None):
	"""Resolve safe response/storage headers from a trusted MIME type or filename."""
	content_type = _safe_content_type(content_type, filename)
	return content_type, _content_disposition(filename, content_type)


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
		except Exception:
			# Password fields may contain a placeholder or encrypted payload. Never
			# pass that raw value to AWS; continue with site config/environment.
			return None

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
	aws_secret_access_key = _get_val(
		"aws_secret_access_key", "s3_secret_access_key", ["AWS_SECRET_ACCESS_KEY"], is_secret=True
	)
	region_name = _get_val("region_name", "s3_region", ["AWS_DEFAULT_REGION", "AWS_REGION"])
	bucket_name = _get_val("bucket_name", "s3_bucket", ["AWS_S3_BUCKET"])
	endpoint_url = _get_val("endpoint_url", "s3_endpoint_url", ["AWS_ENDPOINT_URL"])

	# Check fields do not have an "unset" state in Frappe: their default 0 is returned
	# even when the administrator has never configured the field. Treat the false
	# DocType default as empty so site_config/environment deployments can opt in.
	# An enabled DocType value remains the highest-priority source.
	use_path_style = False
	if settings and parse_bool(settings.get("use_path_style")):
		use_path_style = True
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
		content_type, content_disposition = resolve_content_headers(key, content_type)
		extra_args = {
			"ContentType": content_type,
			"ContentDisposition": content_disposition,
		}
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
				try:
					self._client.upload_fileobj(fileobj, self.bucket_name, key, ExtraArgs=extra_args)
					return True
				except Exception as retry_error:
					frappe.log_error(message=frappe.get_traceback(), title=f"S3 Upload Failed for {key}")
					raise frappe.ValidationError(
						f"Could not upload file to S3: {retry_error}"
					) from retry_error
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

	def generate_presigned_url(self, key, expires_in=3600, filename=None, content_type=None):
		try:
			params = {"Bucket": self.bucket_name, "Key": key}
			if filename:
				content_type, content_disposition = resolve_content_headers(filename, content_type)
				params["ResponseContentType"] = content_type
				params["ResponseContentDisposition"] = content_disposition
			url = self._client.generate_presigned_url(
				"get_object",
				Params=params,
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
