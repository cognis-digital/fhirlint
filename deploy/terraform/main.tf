terraform {
  required_providers {
    docker = { source = "kreuzwerker/docker", version = "~> 3.0" }
  }
}
# Minimal container deploy. Swap the provider block for aws_ecs_service,
# azurerm_container_app, or google_cloud_run_v2_service as needed.
provider "docker" {}
resource "docker_image" "fhirlint" { name = "ghcr.io/cognis-digital/fhirlint:latest" }
resource "docker_container" "fhirlint" {
  name  = "fhirlint"
  image = docker_image.fhirlint.image_id
  ports { internal = 8000 external = 8000 }
}
