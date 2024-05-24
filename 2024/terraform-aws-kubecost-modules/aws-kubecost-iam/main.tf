resource "aws_iam_role" "kubecost_role" {
  name = "eks-${var.cluster_name}-kubecost-feed-access"
  assume_role_policy = jsonencode({
    Statement = [
      {
        Action    = "sts:AssumeRoleWithWebIdentity"
        Effect    = "Allow"
        Principal = {
          Federated = var.eks_arn
        }
        Condition = {
          StringEquals = {
            format("%s%s", trimprefix(var.eks_oidc_issuer, "https://"), ":aud") : "sts.amazonaws.com",
            format("%s%s", trimprefix(var.eks_oidc_issuer, "https://"), ":sub") : "system:serviceaccount:${var.namespace}:${var.service_account}"
          }
        }
      }
    ]
    Version = "2012-10-17"
  })

  tags = {
    Name  = "eks-${var.cluster_name}-kubecost-feed-access"
    Owner = var.cluster_name
  }
}


resource "aws_iam_policy" "s3_athena_access" {
  name = "eks-${var.cluster_name}-kubecost-s3-access"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
          "Sid": "AthenaAccess",
          "Effect": "Allow",
          "Action": [
            "athena:*"
          ],
          "Resource": [
            "*"
          ]
      },
      {
          "Sid": "ReadAccessToAthenaCurDataViaGlue",
          "Effect": "Allow",
          "Action": [
            "glue:GetDatabase*",
            "glue:GetTable*",
            "glue:GetPartition*",
            "glue:GetUserDefinedFunction",
            "glue:BatchGetPartition"
          ],
          "Resource": [
            "arn:aws:glue:*:*:catalog",
            "arn:aws:glue:*:*:database/athenacurcfn*",
            "arn:aws:glue:*:*:table/athenacurcfn*/*"
          ]
      },
      {
          "Sid": "AthenaQueryResultsOutput",
          "Effect": "Allow",
          "Action": [
            "s3:GetBucketLocation",
            "s3:GetObject",
            "s3:ListBucket",
            "s3:ListBucketMultipartUploads",
            "s3:ListMultipartUploadParts",
            "s3:AbortMultipartUpload",
            "s3:CreateBucket",
            "s3:PutObject"
          ],
          "Resource": [
            "arn:aws:s3:::${var.athena_bucket_name}*"
          ]
      },
      {
          "Sid": "S3ReadAccessToAwsBillingData",
          "Effect": "Allow",
          "Action": [
            "s3:Get*",
            "s3:List*"
          ],
          "Resource": [
            "arn:aws:s3:::${var.feed_cur_bucket_name}*"
          ]
      },
      {
          "Sid": "SpotDataAccess",
          "Effect": "Allow",
          "Action": [
            "s3:ListAllMyBuckets",
            "s3:ListBucket",
            "s3:HeadBucket",
            "s3:HeadObject",
            "s3:List*",
            "s3:Get*"
          ],
          "Resource": "arn:aws:s3:::${var.feed_cur_bucket_name}*"
      }
    ]
  })
  tags = {
    Name = "eks-${var.cluster_name}-kubecost-s3-access"
    Owner = var.cluster_name
  }
}

resource "aws_iam_policy" "ec2_access" {
  name = "eks-${var.cluster_name}-kubecost-ec2-access"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "ec2:DescribeAddresses",
          "ec2:DescribeVolumes"
        ],
        Effect = "Allow"
        Resource = "*"
        Sid = "ReadEC2"
      }
    ]
  })
  tags = {
    Name = "eks-${var.cluster_name}-kubecost-ec2-access"
    Owner = var.cluster_name
  }
}

resource "aws_iam_role_policy_attachment" "kubecost_s3_athena_access" {
  policy_arn = aws_iam_policy.s3_athena_access.arn
  role       = aws_iam_role.kubecost_role.name
  depends_on = [
    aws_iam_role.kubecost_role,
    aws_iam_policy.s3_athena_access
  ]
}

resource "aws_iam_role_policy_attachment" "kubecost_eks_access" {
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
  role       = aws_iam_role.kubecost_role.name
  depends_on = [
    aws_iam_role.kubecost_role,
  ]
}

resource "aws_iam_role_policy_attachment" "kubecost_ec2_access" {
  policy_arn = aws_iam_policy.ec2_access.arn
  role       = aws_iam_role.kubecost_role.name
  depends_on = [
    aws_iam_role.kubecost_role,
    aws_iam_policy.ec2_access
  ]
}
