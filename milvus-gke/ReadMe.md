# 1 - Terraform Script to deploy Milvus to a GKE Cluster

1. This repository aims to simplify the process of deploying a Milvus cluster to GKE.
2. To use it, upload the entire folder (milvus-gke) to the Google Cloud CLI environment.
3. In the Google Cloud CLI, navigate to the milvus-gke/ directory.
4. Run `terraform init` in the terminal.
5. Run `terraform apply` in the terminal and follow the prompts. 
6. The Milvus IP address is the IP of the Milvus service.
7. If you want to delete the cluster, do not use the UI. Instead, navigate to the milvus-gke/ directory in the terminal and run `terraform destroy`.
8. This cluster consumes significant resources and will cost you much. Don't forget to disable the billing when it is not in-use. After enabling billing again, wait about 10 minutes and then check the Deployments section of your Milvus cluster. If any of the Milvus deployments appear in red, destroy the cluster using `terraform destroy` and rerun the deployment using `terraform apply`.
9. Keep in mind, if you run out of credits, it takes 24-48 hours to get a new coupon as stated in our GCP coupon redemption instructions. 

this folder is cited from the course material from the first homework