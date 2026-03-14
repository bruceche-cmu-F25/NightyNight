variable "project_id" { type = string }

variable "region" {
  type    = string
  default = "us-central1"
}

variable "zone" {
  type    = string
  default = "us-central1-a"
}

variable "cluster_name" {
  type    = string
  default = "milvus-gke"
}

variable "kubernetes_version" {
  type    = string
  default = "1.29"
}

variable "node_count" {
  type    = number
  default = 1
}

variable "machine_type" {
  type    = string
  default = "n2-standard-4"
}

variable "milvus_mode" {
  type    = string
  default = "standalone"
}

variable "namespace" {
  type    = string
  default = "milvus"
}
