variable "feed_cur_bucket_name" {
  description = "Name of the bucket to store spot data feed"
  type = string
}

variable "athena_bucket_name" {
  description = "Name of the bucket to output athena data"
  type = string
}
variable "cluster_name" {
  description = "Name of the EKS cluster"
  type = string
}

variable "eks_arn" {
  type = string
}

variable "eks_oidc_issuer" {
  description = "Should be like this: https://oidc.eks.eu-central-1.amazonaws.com/id/A719FC843915FABAA300709D79I85T11"
  type = string
}

variable "service_account" {
  type = string
}

variable "namespace" {
  type = string
}