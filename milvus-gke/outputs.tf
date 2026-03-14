output "cluster_name" {
  value = google_container_cluster.this.name
}

output "cluster_zone" {
  value = var.zone
}

output "namespace" {
  value = var.namespace
}
