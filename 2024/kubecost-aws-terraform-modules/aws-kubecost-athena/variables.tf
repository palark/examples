variable "feed_cur_bucket_name" {
  description = "Name of the bucket to store spot data feed"
  type        = string
}

variable "athena_bucket_name" {
  description = "Name of the bucket to output athena data"
  type        = string
}

variable "s3_region" {
  description = "S3 bucket region"
  type        = string
}