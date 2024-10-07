Terraform modules to automate the deployment of Kubecost in AWS and 
integrate it with your EKS clusters:

1. _aws-kubecost-iam_ (`aws-kubecost-iam/`) is a Terraform module 
configuring IAM for each EKS cluster.
2. _aws-kubecost-athena_ (`aws-kubecost-athena/`) is a Terraform module 
creating AWS resources: buckets, CUR (Cost and Usage Report), Spot feed,
and Athena.

They are accompanied by an example of values for the [official Helm chart](https://docs.kubecost.com/install-and-configure/install/helm-install-params)
to deploy Kubecost (`kubecost-helm-values.yaml`).

This code is used (and better described) in the following article:
* [“Kubecost with AWS integration: Implementing and automating with Terraform”](https://blog.palark.com/kubecost-aws-terraform-automation/)
(published in October 2024)
