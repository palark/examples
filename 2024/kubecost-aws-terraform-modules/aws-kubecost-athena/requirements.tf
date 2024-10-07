terraform {
  required_version = ">= 1.0.4"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 3.53.0"
      configuration_aliases = [
        aws.aws_your_region,
        aws.aws_us_east1
      ]
    }
  }
}