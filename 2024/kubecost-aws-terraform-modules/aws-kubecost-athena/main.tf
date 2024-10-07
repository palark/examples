locals {
  cur_report_name                  = "kubecost"
  feed_bucket_prefix               = "feed"
  cur_bucket_prefix                = "costs-report"
  cloudformation_athena_stack_name = "kubecost-athena"
}

# Bucket to store AWS spot feed data and CUR, policy and acl
resource "aws_s3_bucket" "feed_cur" {
  bucket        = var.feed_cur_bucket_name
  force_destroy = true
}

data "aws_caller_identity" "current" {}


## Resource us-east-1 region because CUR exists only in this region
data "aws_iam_policy_document" "bucket_policy" {
  statement {
    principals {
      type        = "Service"
      identifiers = ["billingreports.amazonaws.com", "bcm-data-exports.amazonaws.com"]
    }
    actions = [
      "s3:GetBucketAcl",
      "s3:GetBucketPolicy",
      "s3:PutObject"
    ]
    resources = [aws_s3_bucket.feed_cur.arn, "${aws_s3_bucket.feed_cur.arn}/*"]
    condition  {
      test     = "StringLike"
      variable = "aws:SourceArn"
      values = ["arn:aws:cur:us-east-1:${data.aws_caller_identity.current.account_id}:definition/*", "arn:aws:bcm-data-exports:us-east-1:${data.aws_caller_identity.current.account_id}:export/*"]
    }
    condition  {
      test     = "StringLike"
      variable = "aws:SourceAccount"
      values = ["${data.aws_caller_identity.current.account_id}"]
    }
  }
}

resource "aws_s3_bucket_policy" "billing" {
  bucket = aws_s3_bucket.feed_cur.id
  policy = data.aws_iam_policy_document.bucket_policy.json
}

resource "aws_s3_bucket_acl" "default" {
  bucket = aws_s3_bucket.feed_cur.id
  acl    = "private"
  depends_on = [aws_s3_bucket_ownership_controls.s3_bucket_acl_ownership]
}

resource "aws_s3_bucket_ownership_controls" "s3_bucket_acl_ownership" {
  bucket = aws_s3_bucket.feed_cur.id
  rule {
    object_ownership = "ObjectWriter"
  }
}

# Feed subscription
resource "aws_spot_datafeed_subscription" "default" {
  bucket = aws_s3_bucket.feed_cur.id
  prefix = local.feed_bucket_prefix
  depends_on = [aws_s3_bucket_acl.default, aws_s3_bucket_policy.billing]
}

# CUR
## Resource exist only in us-east-1 region, so have to use provider with this region and pass it to the module
resource "aws_cur_report_definition" "default" {
  provider                   = aws.aws_us_east1
  report_name                = local.cur_report_name
  time_unit                  = "HOURLY"
  format                     = "Parquet"
  compression                = "Parquet"
  additional_schema_elements = ["RESOURCES"]
  s3_bucket                  = aws_s3_bucket.feed_cur.bucket
  #The AWS Cost and Usage Report service is only available in us-east-1 currently
  s3_region                  = var.s3_region
  s3_prefix                  = local.cur_bucket_prefix
  additional_artifacts       = ["ATHENA"]
  report_versioning          = "OVERWRITE_REPORT"
  depends_on = [aws_s3_bucket_policy.billing]
}

## bucket athena

resource "aws_s3_bucket" "athena" {
  bucket = var.athena_bucket_name
  force_destroy = true
}

resource "aws_s3_bucket_lifecycle_configuration" "bucket-config" {
  bucket = aws_s3_bucket.athena.id
  rule {
    id = "retention"

    expiration {
      days = 1
    }
    status = "Enabled"
  }
}

## Athena
#Cloud formation template can be downloaded from s3 bucket, but it took 1 day to CUR create it, so we added it to module as tempalte.
resource "aws_cloudformation_stack" "athena_integration" {
  name = local.cloudformation_athena_stack_name
  template_body = templatefile("${path.module}/templates/crawler-cfn.tftpl", { cur_report_name = local.cur_report_name, cur_bucket_prefix = local.cur_bucket_prefix, feed_cur_bucket_name = var.feed_cur_bucket_name  })
  capabilities = ["CAPABILITY_IAM"]
  depends_on = [aws_s3_bucket.athena]
}
