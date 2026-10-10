"""Create the media bucket on the S3-compatible store if it does not exist yet."""

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the media bucket (no-op when files are stored on local disk)."

    def handle(self, *args, **options):
        if not settings.AWS_S3_ENDPOINT_URL:
            self.stdout.write("Local file storage: nothing to do.")
            return
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME,
            config=Config(s3={"addressing_style": "path"}),
        )
        bucket = settings.AWS_STORAGE_BUCKET_NAME
        try:
            s3.head_bucket(Bucket=bucket)
        except ClientError:
            s3.create_bucket(Bucket=bucket)
            self.stdout.write(f"Created bucket {bucket}.")
        else:
            self.stdout.write(f"Bucket {bucket} already exists.")
