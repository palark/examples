output "feed_cur" {
  value = {
    arn    = aws_s3_bucket.feed_cur.arn
    bucket = var.feed_cur_bucket_name
    feed_bucket_prefix = local.feed_bucket_prefix
    cur_bucket_prefix = local.cur_bucket_prefix
  }
}


output "athena" {
  value = {
    arn    = aws_s3_bucket.athena.arn
    bucket = var.athena_bucket_name
  }
}
