###############################################################################
# main.tf — GKE (N2 nodes) + Milvus (Standalone) + Attu (Web UI)
# Goal: Fit a small GKE cluster by disabling heavy deps (Pulsar/BookKeeper/ZK),
#       using Rocksmq, and reducing resource requests.
###############################################################################

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

# -----------------------------------------------------------------------------
# GKE Cluster + N2 node pool
# -----------------------------------------------------------------------------
resource "google_container_cluster" "this" {
  name                 = var.cluster_name
  location             = var.zone
  deletion_protection  = false
  remove_default_node_pool = true
  initial_node_count       = 1

  networking_mode = "VPC_NATIVE"

  release_channel {
    channel = "REGULAR"
  }
}

resource "google_container_node_pool" "n2_pool" {
  name       = "${var.cluster_name}-n2"
  location   = var.zone
  cluster    = google_container_cluster.this.name
  node_count = var.node_count

  node_config {
    machine_type = var.machine_type

    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
    ]

    labels = {
      workload = "milvus"
    }

    metadata = {
      disable-legacy-endpoints = "true"
    }
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}

# -----------------------------------------------------------------------------
# Auth + cluster endpoint for Kubernetes/Helm providers
# -----------------------------------------------------------------------------
data "google_client_config" "default" {}

resource "null_resource" "wait_for_cluster" {
  depends_on = [
    google_container_cluster.this,
    google_container_node_pool.n2_pool
  ]

  provisioner "local-exec" {
    command = "gcloud container clusters get-credentials \"${var.cluster_name}\" --zone \"${var.zone}\" --project \"${var.project_id}\" >/dev/null 2>&1"
  }
}


provider "helm" {
  kubernetes = {
    config_path    = pathexpand("~/.kube/config")
    config_context = "gke_${var.project_id}_${var.zone}_${var.cluster_name}"
  }
}

# -----------------------------------------------------------------------------
# Namespace
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# Milvus (Standalone) + Attu (enabled inside Milvus chart)
# Downsized: disable Pulsar stack and reduce CPU/memory requests
# -----------------------------------------------------------------------------

resource "helm_release" "milvus" {
  name             = "milvus"
  namespace        = var.namespace
  create_namespace = true

  repository = "https://zilliztech.github.io/milvus-helm/"
  chart      = "milvus"

  timeout         = 900
  wait            = true
  wait_for_jobs   = true
  atomic          = true
  cleanup_on_fail = true

  values = [
    yamlencode({
      cluster    = { enabled = false }
      standalone = { 
        enabled = true 
    }

      pulsar   = { enabled = false }
      pulsarv3 = { enabled = false }
      kafka    = { enabled = false }
      rocksmq  = { enabled = true }

      service = { type = "LoadBalancer" }

      persistence = {
        enabled      = true
        size         = "20Gi"
        storageClass = "standard"
      }

      etcd = {
        replicaCount = 1
        persistence  = { enabled = true, size = "10Gi", storageClass = "standard" }

      }
        minio = {
            mode = "standalone"
            persistence = { enabled = true, size = "20Gi", storageClass = "standard" }

        }

      attu = {
        enabled = true
        service = { type = "LoadBalancer", port = 3000 }
      }

    })

  ]
  depends_on = [google_container_node_pool.n2_pool,
                null_resource.wait_for_cluster]
}



 
